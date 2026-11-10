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
    status, preview = request(server, '/api/authoring-preview', body)
    assert status == 200
    assert calls[0][0][0].content == preview['full_system']
    assert calls[0][0][1].content == preview['user']
    assert preview['user'].startswith('Task\n\nEcho')
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


def test_staged_previews_paste_execution_and_upstream_replacement(server, monkeypatch):
    import modelspell
    calls = []
    interface = {'inputs': {'n': 'integer'}, 'outputs': {'out': 'integer'}}
    body = dict(instruction='Double n', example_count=2, revision_id=None, stage='inputs',
                model='test/model', interface_text=json.dumps(interface))
    status, preview = request(server, '/api/authoring-preview', body)
    assert status == 200 and preview['user'].startswith('Task\n\nDouble n')

    def complete(endpoint, model, messages, **kwargs):
        calls.append(messages)
        return SimpleNamespace(text='{"examples":[{"n":1},{"n":9007199254740993}]}',
                               finish_reason='stop', truncated=False)

    monkeypatch.setattr(modelspell, 'complete', complete)
    status, inputs = request(server, '/api/stage', body)
    assert status == 200 and inputs['has_inputs']
    assert [message.content for message in calls[0]] == [preview['full_system'], preview['user']]
    outputs_body = dict(body, stage='expectations', stage_token=inputs['stage_token'])
    status, outputs = request(server, '/api/stage',
                              dict(outputs_body, reply='{"outputs":{"1":{"out":2},"2":{"out":18014398509481986}}}'))
    assert status == 200 and outputs['has_outputs']
    python_body = dict(body, stage='python', stage_token=outputs['stage_token'])
    assert request(server, '/api/authoring-preview', dict(python_body, stage_token=inputs['stage_token']))[1]['error'] == 'stale_stage'
    status, preview = request(server, '/api/authoring-preview', python_body)
    assert status == 200 and preview['schema'] is None
    assert '9007199254740993' not in preview['user']
    status, completed = request(server, '/api/stage', dict(
        python_body, reply='def transform(inputs):\n    return {"out": 2 * inputs["n"]}'))
    assert status == 200 and completed['completed_revision'] == completed['active_id']
    status, tested = request(server, '/api/run', {'revision_id': completed['active_id']})
    assert status == 200
    assert [case['visible'] for case in tested['revision']['draft']['examples']] == [True, False]
    assert all(case['result']['status'] == 'pass' for case in tested['revision']['draft']['examples'])

    status, replaced = request(server, '/api/stage', dict(
        body, stage_token=completed['stage_token'], revision_id=completed['active_id'],
        reply='{"examples":[{"n":3},{"n":4}]}'))
    assert status == 200 and not replaced['has_outputs'] and replaced['completed_revision'] is None
    assert request(server, '/api/authoring-preview', dict(
        python_body, stage_token=replaced['stage_token']))[1]['error'] == 'stage_not_ready'
    assert len(calls) == 1


def test_one_shot_paste_uses_proposal_validation_without_model_call(server, monkeypatch):
    import modelspell

    def unexpected(*args, **kwargs):
        pytest.fail('pasting a reply must not call the model')

    monkeypatch.setattr(modelspell, 'complete', unexpected)
    body = dict(instruction='Echo', example_count=1, revision_id=None)
    assert request(server, '/api/generate', dict(body, reply='{}'))[1]['error'] == 'invalid_proposal'
    reply = dict(source='def transform(inputs):\n    return {"out": inputs["n"]}',
                 summary='', assumptions=[], unmet_requirements=[],
                 example_input={'n': 7}, expected_output={'out': 7})
    status, view = request(server, '/api/generate', dict(body, reply=json.dumps(reply)))
    assert status == 200 and view['revision']['action'] == 'paste'


def test_yaml_ui_previews_retries_pastes_and_invalidates_working_python(server, monkeypatch):
    import modelspell

    yaml_examples = """interface:
  inputs: [{value: float}]
  outputs: [{out: float}]
examples:
  - inputs: [{value: 0.1}]
    outputs: [{out: 0.3}]
  - inputs: [{value: 198.25}]
    outputs: [{out: 198.45}]
"""
    rejected = 'interface: [\n'
    calls = []
    replies = iter([rejected, yaml_examples])

    def complete(endpoint, model, messages, **kwargs):
        calls.append(messages)
        return SimpleNamespace(text=next(replies), finish_reason='stop', truncated=False)

    monkeypatch.setattr(modelspell, 'complete', complete)
    body = dict(mode='two-call', stage='examples', instruction='Add 0.2', example_count=2,
                model='test/model', revision_id=None)
    status, preview = request(server, '/api/authoring-preview', body)
    assert status == 200 and preview['schema'] is None
    status, data = request(server, '/api/stage', body)
    assert status == 200 and data['retry_issues'] and len(calls) == 2
    assert [message.content for message in calls[0]] == [preview['full_system'], preview['user']]
    assert calls[1][1].content.endswith(rejected)
    python_body = dict(body, stage='python', stage_token=data['stage_token'])
    status, preview = request(server, '/api/authoring-preview', python_body)
    assert status == 200 and '198.25' not in preview['system']
    code = 'def transform(inputs):\n    return {"out": inputs["value"] + 0.2}'
    status, data = request(server, '/api/stage', dict(python_body, reply=code))
    assert status == 200 and data['completed_revision']
    revision = data['active_id']
    status, view = request(server, '/api/run', {'revision_id': revision})
    assert status == 200
    cases = view['revision']['draft']['examples']
    assert [case['visible'] for case in cases] == [True, False]
    assert [case['result']['status'] for case in cases] == ['pass', 'pass']

    edited = dict(body, revision_id=revision, stage_token=data['stage_token'])
    status, error = request(server, '/api/stage', dict(edited, reply=rejected))
    assert status == 400 and error['details']['issues'] and len(calls) == 2
    status, replaced = request(server, '/api/stage', dict(edited, reply=yaml_examples))
    assert status == 200 and replaced['completed_revision'] is None
    assert request(server, '/api/authoring-preview', python_body)[1]['error'] == 'stale_stage'
    assert request(server, '/api/revision', {'revision_id': revision})[0] == 200

    one_shot = yaml_examples + 'source: |\n' + ''.join('  ' + line + '\n' for line in code.splitlines())
    status, data = request(server, '/api/stage', dict(body, mode='one-shot-yaml', stage='one-shot',
                                                     revision_id=revision, reply=one_shot))
    assert status == 200 and len(calls) == 2
    assert all(case['visible'] for case in data['revision']['draft']['examples'])
