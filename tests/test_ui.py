"""Browser adapter behavior through real loopback HTTP and offline model replies."""
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from scriptspell import prepare_authoring
from scriptspell.workflow import same_value

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / 'ui/server.py').exists(), reason='repository-only developer UI')


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT))
    from ui.server import UIServer
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    server = UIServer(runs=tmp_path)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield server
    server.shutdown()
    server.close()
    thread.join(3)
    assert not thread.is_alive()


def request(server, path, body=None, token=True, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    hdr = {'Content-Type': 'application/json'}
    if token:
        hdr['X-Session-Token'] = server.token
    hdr.update(headers or {})
    conn.request('GET' if body is None else 'POST', path, body=None if body is None else json.dumps(body), headers=hdr)
    response = conn.getresponse()
    status, data = response.status, json.loads(response.read())
    conn.close()
    return status, data


def test_http_key_protection_and_single_operation(server, monkeypatch):
    import modelspell
    assert request(server, '/api/state', token=False)[0] == 403
    assert request(server, '/api/key', {'api_key': 'secret'}, headers={'Origin': 'https://evil.invalid'})[0] == 403
    assert request(server, '/api/state', headers={'Host': 'evil.invalid'})[0] == 403
    assert request(server, '/api/key', {'api_key': 'secret'})[0] == 200
    status, state = request(server, '/api/state')
    assert status == 200 and 'secret' not in str(state) and len(state['presets']) == 20
    captured = []
    monkeypatch.setattr(modelspell, 'list_models', lambda endpoint, **kw: captured.append(endpoint) or [SimpleNamespace(
        id='test/model', name='Test', supports_reasoning=False)])
    status, data = request(server, '/api/models', {})
    assert status == 200 and data['models'][0]['id'] == 'test/model'
    assert captured[0].api_key == 'secret'
    with server.operation:
        assert request(server, '/api/models', {})[0] == 409
    assert request(server, '/api/generate', {'model': 'test/model', 'instruction': 'Trim', 'reasoning': 'low'}) == (
        502, {'error': 'UnsupportedSetting'})
    assert b'secret' not in (server.session.directory / 'journal.json').read_bytes()


def test_http_generation_edits_correction_and_preserves_draft_on_failure(server, monkeypatch):
    import modelspell
    calls = []
    source = 'def transform(inputs):\n    return {"out": inputs["n"]}'
    proposal = dict(source=source, summary='Echo', assumptions=[], unmet_requirements=[],
                    example_input={'n': 9007199254740993}, expected_output={'out': None})

    def complete(endpoint, model, messages, **settings):
        calls.append((messages, settings))
        payload = proposal if len(calls) == 1 else {'expected_output': {'out': 9007199254740993}}
        return SimpleNamespace(text=json.dumps(payload), truncated=len(calls) > 2, finish_reason='stop')

    monkeypatch.setattr(modelspell, 'complete', complete)
    body = {'model': 'test/model', 'instruction': 'Echo', 'temperature': 0.25,
            'max_tokens': 300, 'reasoning': 'medium'}
    status, data = request(server, '/api/generate', body)
    assert status == 200 and len(calls) == 1
    materials = prepare_authoring('Echo')
    assert calls[0][0][0].content.startswith(materials['system'])
    assert calls[0][0][1].content == materials['user']
    assert {k: calls[0][1][k] for k in ('temperature', 'max_tokens', 'reasoning')} == {
        k: body[k] for k in ('temperature', 'max_tokens', 'reasoning')}
    active = data['active_id']
    case = data['revision']['draft']['examples'][0]
    assert case['result'] is None and '9007199254740993' in case['input_json']

    status, data = request(server, '/api/run', {'revision_id': active, 'source': 'evil'})
    assert status == 200
    assert data['revision']['draft']['examples'][0]['result']['status'] == 'mismatch'
    assert request(server, '/api/run', {'revision_id': 'old-tab'})[1]['error'] == 'stale_revision'

    status, data = request(server, '/api/correct', dict(body, revision_id=active, example_id=case['id'],
                                                        guidance='Return the input number'))
    assert status == 200 and data['active_id'] == active
    attempt = data['attempt']
    assert json.loads(attempt['previous_expected_json']) == {'out': None}
    assert '9007199254740993' in attempt['candidate']['examples'][0]['expected_json']
    status, data = request(server, '/api/decide', {'revision_id': active, 'attempt_id': attempt['id'], 'accept': True})
    assert status == 200 and data['active_id'] != active
    assert data['revision']['draft']['examples'][0]['result']['status'] == 'pass'
    active = data['active_id']

    status, data = request(server, '/api/generate', dict(body, revision_id=active))
    assert status == 400 and data['error'] == 'incomplete_model_response'
    assert request(server, '/api/state')[1]['active_id'] == active
    status, data = request(server, '/api/edit', {'revision_id': active, 'example_id': case['id'],
                                                 'input_json': '{"n":7}', 'expected_json': '{"out":7}'})
    assert status == 200 and data['revision']['draft']['examples'][0]['result'] is None
    assert json.loads(data['revision']['draft']['examples'][0]['expected_json']) == {'out': 7}


@pytest.mark.parametrize('invalid', ['{"n":1,"n":2}', '{"n":NaN}', '{"n":0.5}', '[]', '{'])
def test_bad_edited_json_is_refused(server, monkeypatch, invalid):
    import modelspell
    proposal = dict(source='def transform(inputs):\n    return {"out": inputs["n"]}',
                    summary='Echo', assumptions=[], unmet_requirements=[], example_input={'n': 1},
                    expected_output={'out': 1})
    monkeypatch.setattr(modelspell, 'complete', lambda *a, **k: SimpleNamespace(
        text=json.dumps(proposal), truncated=False, finish_reason='stop'))
    status, data = request(server, '/api/generate', {'model': 'test/model', 'instruction': 'Echo'})
    assert status == 200
    assert request(server, '/api/edit', {'revision_id': data['active_id'],
                                        'example_id': data['revision']['draft']['examples'][0]['id'],
                                        'input_json': invalid, 'expected_json': '{"out":1}'})[0] == 400


def test_exact_comparison():
    assert not same_value({'x': True}, {'x': 1})
    assert not same_value({'x': [1, 2]}, {'x': [2, 1]})
    assert same_value({'a': 1, 'b': None}, {'b': None, 'a': 1})
