"""Developer UI behavior through the consumer adapter and real loopback HTTP."""
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

# The release wheel intentionally has no UI or model transport dependency.
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / 'ui/server.py').exists(), reason='repository-only developer UI')


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from ui import service
    return service


def proposal():
    return {'source': 'def transform(inputs):\n    return {"out": inputs["text"].strip()}',
            'summary': 'Trim', 'assumptions': [], 'unmet_requirements': [],
            'example_input': {'text': ' a '}, 'expected_output': {'out': 'a'}}


def test_ui_generation_uses_production_materials_once(ui, monkeypatch):
    from scriptspell import prepare_authoring
    calls = []
    def complete(endpoint, model, messages, **kwargs):
        calls.append((endpoint, model, messages, kwargs))
        return SimpleNamespace(text=json.dumps(proposal()), truncated=False, finish_reason='stop')
    monkeypatch.setattr(ui.modelspell, 'complete', complete)
    p = ui.generate(ui.modelspell.Endpoint('openrouter', api_key='FAKE_KEY'), 'test/model', 'Trim whitespace', None)
    assert p == proposal() and len(calls) == 1
    materials = prepare_authoring('Trim whitespace')
    assert calls[0][2][0].content.startswith(materials['system'])
    assert calls[0][2][1].content == materials['user']
    assert calls[0][3]['max_tokens'] == 4096


def test_ui_rejects_code_only_or_truncated_proposals(ui, monkeypatch):
    for p, truncated in [({'source': proposal()['source']}, False), (proposal(), True)]:
        monkeypatch.setattr(ui.modelspell, 'complete', lambda *a, **k: SimpleNamespace(
            text=json.dumps(p), truncated=truncated, finish_reason='stop'))
        with pytest.raises(ui.UIError):
            ui.generate(ui.modelspell.Endpoint('openrouter'), 'test/model', 'Trim', None)


def test_edited_examples_execute_and_compare_strictly(ui):
    stop = threading.Event()
    result = ui.execute(proposal(), '{"text":" b "}', '{"out":"b"}', stop)
    assert result['status'] == 'match' and json.loads(result['actual_json']) == {'out': 'b'}
    assert ui.execute(proposal(), '{"text":" b "}', '{"out":"a"}', stop)['status'] == 'mismatch'
    assert not ui.same_value({'x': True}, {'x': 1})
    assert not ui.same_value({'x': [1, 2]}, {'x': [2, 1]})
    assert ui.same_value({'a': 1, 'b': None}, {'b': None, 'a': 1})
    stop.set()
    stopped = ui.execute(proposal(), '{"text":" b "}', '{"out":"b"}', stop)
    assert stopped['status'] == 'error' and stopped['outcome'] == 'cancelled'
    stop.clear()
    bad = proposal(); bad['source'] = 'def transform(inputs):\n    return {"bad": 1}'
    assert ui.execute(bad, '{}', '{}', stop)['status'] == 'error'
    bad['unmet_requirements'] = ['Host I/O unavailable']
    with pytest.raises(ui.UIError, match='requirements_unmet'):
        ui.execute(bad, '{}', '{}', stop)


@pytest.mark.parametrize('text', ['{"x":1,"x":2}', '{"x":NaN}', '{"x":0.5}', '[]', '{'])
def test_bad_example_json_refused(ui, text):
    with pytest.raises(ui.UIError):
        ui.parse_example(text)


def test_large_integer_survives_format_and_run(ui):
    p = proposal(); p['source'] = 'def transform(inputs):\n    return {"out": inputs["n"]}'
    text = '{"n":9007199254740993}'
    assert ui.parse_example(ui.pretty(ui.parse_example(text)))['n'] == 9007199254740993
    result = ui.execute(p, text, '{"out":9007199254740993}', threading.Event())
    assert result['status'] == 'match' and '9007199254740993' in result['actual_json']


@pytest.fixture
def server(ui, monkeypatch):
    from ui.server import UIServer
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    s = UIServer()
    thread = threading.Thread(target=s.serve_forever)
    thread.start()
    yield s
    s.shutdown(); s.close(); thread.join(3)
    assert not thread.is_alive()


def request(server, path, body=None, token=True, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    hdr = {'Content-Type': 'application/json'}
    if token:
        hdr['X-Session-Token'] = server.token
    hdr.update(headers or {})
    conn.request('GET' if body is None else 'POST', path, body=None if body is None else json.dumps(body), headers=hdr)
    response = conn.getresponse()
    status, data = response.status, response.read()
    conn.close()
    return status, data


def test_http_key_protection_and_single_operation(server, ui, monkeypatch):
    assert request(server, '/api/state', token=False)[0] == 403
    assert request(server, '/api/key', {'api_key': 'secret'}, headers={'Origin': 'https://evil.invalid'})[0] == 403
    assert request(server, '/api/state', headers={'Host': 'evil.invalid'})[0] == 403
    assert request(server, '/api/key', {'api_key': 'secret'})[0] == 200
    assert b'secret' not in request(server, '/api/state')[1]
    captured = []
    monkeypatch.setattr(ui.modelspell, 'list_models', lambda endpoint, **kw: captured.append(endpoint) or [SimpleNamespace(id='test/model', name='Test')])
    status, data = request(server, '/api/models', {})
    assert status == 200 and json.loads(data)['models'][0]['id'] == 'test/model'
    assert captured[0].api_key == 'secret'
    with server.operation:
        assert request(server, '/api/models', {})[0] == 409
    status, data = request(server, '/api/format', {'text': '{"n":9007199254740993}'})
    assert status == 200 and '9007199254740993' in json.loads(data)['text']


def test_http_generate_does_not_execute_and_run_uses_server_source(server, ui, monkeypatch):
    monkeypatch.setattr(ui.modelspell, 'complete', lambda *a, **kw: SimpleNamespace(text=json.dumps(proposal()), truncated=False, finish_reason='stop'))
    real_run = ui.run
    calls = []
    def counted(*a, **kw):
        calls.append(a)
        return real_run(*a, **kw)
    monkeypatch.setattr(ui, 'run', counted)
    status, data = request(server, '/api/generate', {'model': 'test/model', 'instruction': 'Trim'})
    assert status == 200 and not calls
    candidate_id = json.loads(data)['proposal_id']
    assert json.loads(data)['example_input_json'] == ui.pretty(proposal()['example_input'])
    status, data = request(server, '/api/run', {'proposal_id': candidate_id, 'source': 'evil', 'input_json': '{"text":"z "}', 'expected_json': '{"out":"z"}'})
    assert status == 200 and json.loads(data)['status'] == 'match'
    assert len(calls) == 1 and calls[0][0] == proposal()['source']
    assert request(server, '/api/run', {'proposal_id': 'old-tab', 'input_json': '{}', 'expected_json': '{}'})[0] == 400
    assert len(calls) == 1
    # A rejected regeneration cannot leave the previous candidate executable.
    monkeypatch.setattr(ui.modelspell, 'complete', lambda *a, **kw: SimpleNamespace(text='{}', truncated=False, finish_reason='stop'))
    assert request(server, '/api/generate', {'model': 'test/model', 'instruction': 'Other'})[0] == 400
    assert request(server, '/api/run', {'input_json': '{}', 'expected_json': '{}'})[0] == 400
