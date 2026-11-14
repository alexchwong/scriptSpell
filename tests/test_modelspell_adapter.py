"""Offline contract checks for the optional adapter and injected authoring dispatch."""
import json
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

import pytest

from scriptspell import (AuthoringError, YamlAuthoring, correct_expected, generate_draft,
                         improve_python, model_messages)
from scriptspell.modelspell_adapter import make_dispatch
from scriptspell.staged import StagedAuthoring
from scriptspell.workflow import accept_generation_reply

MATERIALS = {'system': 'system', 'user': 'user', 'response_schema': {'type': 'object'},
             'request_context': {'stage': 'json_draft', 'attempt': 1}}
SOURCE = "def transform(inputs):\n    return {'out': inputs['n']}"
PROPOSAL = dict(source=SOURCE, summary='Echo', assumptions=[], unmet_requirements=[],
                example_input={'n': 1}, expected_output={'out': 1})
YAML = """interface:
  inputs: {n: int}
  outputs: {out: int}
examples:
  - inputs: {n: 1}
    outputs: {out: 1}
"""


@pytest.fixture
def sdk():
    return pytest.importorskip('modelspell')


@pytest.fixture
def completions(sdk, monkeypatch):
    calls = []
    result = object()

    def complete(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(sdk, 'complete', complete)
    return calls, result


@pytest.mark.parametrize('kind, options', [
    ('openrouter', {'temperature': 0}),
    ('openai_compat', {'temperature': 2.5}),
    ('lmstudio', {}),
    ('lmstudio', {'reasoning': 'off', 'temperature': 0, 'top_k': 10}),
])
def test_route_binding_preserves_identity_and_omissions(sdk, completions, kind, options):
    endpoint = sdk.Endpoint(kind, base_url='http://localhost:1234/v1')
    model = sdk.ModelInfo('host/model', None, None, None, None, True, ('off',), None, {})
    cancel = sdk.CancelHandle()
    calls, result = completions
    dispatch = make_dispatch(endpoint, model, options=options, cancel=cancel)
    assert not calls
    assert dispatch(MATERIALS, {}) is result
    [(args, kwargs)] = calls
    assert args[0] is endpoint and args[1] is model
    assert args[2] == [{'role': 'system', 'content': 'system\nJSON response schema: {"type": "object"}'},
                       {'role': 'user', 'content': 'user'}]
    assert kwargs == dict(options, cancel=cancel) and kwargs['cancel'] is cancel


def test_provider_snapshot_and_wire_compatibility(sdk, completions):
    endpoint = sdk.Endpoint('openrouter')
    caps = {'prompt': 0.5}
    tags = ['Alpha']
    options = {'provider': {'max_price': MappingProxyType(caps), 'order': tags,
                            'only': tags, 'allow_fallbacks': False}, 'stop': ('end',)}
    send = make_dispatch(endpoint, 'host/model', options=MappingProxyType(options))
    caps['prompt'] = 2
    tags.append('Beta')
    options['stop'] = ('changed',)
    send(MATERIALS, {})
    calls, _ = completions
    assert calls[-1][1] == {'cancel': None, 'stop': ['end'], 'provider': {
        'max_price': {'prompt': 0.5}, 'order': ['Alpha'], 'only': ['Alpha'], 'allow_fallbacks': False}}
    for policy in ({}, None):
        make_dispatch(endpoint, 'host/model', options={'provider': policy})(MATERIALS, {})
        assert calls[-1][1]['provider'] == policy
    make_dispatch(endpoint, 'host/model')(MATERIALS, {})
    assert calls[-1][1] == {'cancel': None}


def test_policy_checks_use_installed_preflight(sdk, completions, monkeypatch):
    endpoint = sdk.Endpoint('openrouter')
    decimal_policy = {'max_price': {'prompt': Decimal('0.5')}}
    if hasattr(sdk, 'check_completion'):
        reject = sdk.ConfigError
        pattern = 'JSON|provider'
        from modelspell import _provider

        row = sdk.ProviderInfo('Alpha', 'Alpha/Fast', None, None, None, None, (), {})
        monkeypatch.setattr(_provider, '_providers', lambda *args: [row])
        target = sdk.Endpoint('openrouter', api_key='test-only-key')
        selection = sdk.choose_provider(target, 'host/model', mode='manual', pin='Alpha/Fast',
                                        provider=decimal_policy)
        make_dispatch(target, 'host/model', options={'provider': selection.policy})(MATERIALS, {})
        assert completions[0][-1][1]['provider']['order'] == ['Alpha/Fast']
        make_dispatch(endpoint, 'host/model', options={'provider': decimal_policy})(MATERIALS, {})
        assert completions[0][-1][1]['provider'] == decimal_policy
    else:
        reject = AuthoringError
        pattern = '^unencodable_dispatch_options$'
        make_dispatch(endpoint, 'host/model', options={'provider': {'order': ['Alpha'],
                                                                    'allow_fallbacks': False}})(MATERIALS, {})
        with pytest.raises(reject, match=pattern):
            make_dispatch(endpoint, 'host/model', options={'provider': decimal_policy})
    before = len(completions[0])
    with pytest.raises(reject, match=pattern):
        make_dispatch(endpoint, 'host/model', options={'provider': {'only': {'Alpha'}}})
    assert len(completions[0]) == before


def test_adapter_rejects_invalid_setup_and_overrides_before_send(sdk, completions):
    endpoint = sdk.Endpoint('openrouter')
    cyclic = []
    cyclic.append(cyclic)
    for args, kwargs, code in [
        ((object(), 'm'), {}, 'invalid_dispatch_endpoint'),
        ((endpoint, 'm'), {'cancel': object()}, 'invalid_dispatch_cancel'),
        ((endpoint, 'm'), {'options': {'rate_limit_retries': 0}}, 'unsupported_dispatch_option'),
        ((endpoint, 'm'), {'options': {'provider': {'only': cyclic}}}, 'cyclic_dispatch_options'),
    ]:
        with pytest.raises(AuthoringError, match=f'^{code}$'):
            make_dispatch(*args, **kwargs)
    with pytest.raises(sdk.ConfigError, match='temperature'):
        make_dispatch(sdk.Endpoint('lmstudio'), 'm', options={'reasoning': 'off', 'temperature': 1.5})
    with pytest.raises(sdk.UnsupportedSetting, match='top_k'):
        make_dispatch(sdk.Endpoint('lmstudio'), 'm', options={'top_k': 2})
    send = make_dispatch(endpoint, 'm', options={'temperature': 0})
    for settings in ({'temperature': 0}, {'temperature': None}, {'top_p': None}, {'model': 'm'}):
        with pytest.raises(AuthoringError, match='^bound_dispatch_requires_empty_settings$'):
            send(MATERIALS, settings)
    assert not completions[0]


def _author(send):
    draft = generate_draft(send, {}, 'Echo n')
    legacy = StagedAuthoring('Echo n', 1)
    for stage in ('inputs', 'expectations', 'python'):
        legacy.generate(stage, send, {})
    yaml = YamlAuthoring('Echo n', 1)
    for stage in ('examples', 'python'):
        yaml.generate(stage, send, {})
    one = YamlAuthoring('Echo n', one_shot=True)
    one.generate('one-shot', send, {})
    case_id = draft['examples'][0]['id']
    corrected = correct_expected(send, {}, draft, case_id, 'Expect two')
    reports = [dict(example_id=case_id, status='mismatch', outcome='ok', actual={'out': 1})]
    repaired, results = improve_python(send, {}, corrected, reports, [case_id])
    assert results[0]['status'] == 'pass'
    drafts = [draft, legacy.draft(), yaml.draft(), one.draft(), corrected, repaired]
    for item in drafts:
        for case in item['examples']:
            del case['id']
    return drafts


def test_bound_and_injected_workflow_parity(sdk, monkeypatch):
    responses = [
        '{', json.dumps(PROPOSAL),
        '{"interface":{"inputs":{"n":"integer"},"outputs":{"out":"integer"}},"examples":[{"n":1}]}',
        '{"outputs":{"1":{"out":1}}}', SOURCE, 'invalid: [', YAML, SOURCE,
        YAML + 'source: |\n' + '\n'.join('  ' + line for line in SOURCE.splitlines()),
        '{"expected_output":{"out":2}}',
        json.dumps({'source': "def transform(inputs):\n    return {'out': 2}"}),
    ]
    calls, contexts = [], []

    def make_complete(replies, captured):
        def complete(endpoint, model, messages, **kwargs):
            captured.append(messages)
            return SimpleNamespace(text=next(replies), finish_reason='stop', truncated=False)
        return complete

    endpoint = sdk.Endpoint('openrouter')
    monkeypatch.setattr(sdk, 'complete', make_complete(iter(responses), calls))
    bound = _author(make_dispatch(endpoint, 'host/model'))
    injected_calls = []
    complete = make_complete(iter(responses), injected_calls)

    def injected(materials, settings):
        assert settings == {}
        contexts.append(materials['request_context'])
        return complete(endpoint, 'host/model', model_messages(materials))

    assert _author(injected) == bound
    assert injected_calls == calls
    assert contexts == [dict(stage=stage, attempt=attempt) for stage, attempt in [
        ('json_draft', 1), ('json_draft', 2), ('json_inputs', 1), ('json_expectations', 1),
        ('json_python', 1), ('yaml_examples', 1), ('yaml_examples', 2), ('yaml_python', 1),
        ('yaml_one_shot', 1), ('correct_expected', 1), ('improve_python', 1),
    ]]
    assert calls[6][1]['content'].endswith(responses[5])
    manual = accept_generation_reply(json.dumps(PROPOSAL), 'Echo n', 1)
    del manual['examples'][0]['id']
    assert manual == bound[0]


@pytest.mark.parametrize('metadata, accepted', [
    ({'transport': 'lmstudio_native', 'finish_reason': None}, True),
    ({'transport': 'lmstudio_native', 'finish_reason': None, 'usage': None}, True),
    ({'transport': 'lmstudio_native', 'finish_reason': None, 'truncated': True}, False),
    ({'finish_reason': None}, False),
    ({'finish_reason': 'length'}, False),
    ({'finish_reason': 'stop', 'truncated': True}, False),
])
def test_completion_gate_matches_for_injected_and_bound(sdk, monkeypatch, metadata, accepted):
    reply = dict(text=json.dumps(PROPOSAL), finish_reason='stop', truncated=False)
    reply.update(metadata)
    result = SimpleNamespace(**reply)
    monkeypatch.setattr(sdk, 'complete', lambda *a, **kw: result)
    bound = make_dispatch(sdk.Endpoint('lmstudio'), 'm', options={'reasoning': 'off'})
    for dispatch in (bound, lambda materials, settings: result):
        if accepted:
            assert generate_draft(dispatch, {}, 'Echo')['examples'][0]['expected_output'] == {'out': 1}
        else:
            with pytest.raises(AuthoringError, match='^incomplete_model_response$'):
                generate_draft(dispatch, {}, 'Echo')


def test_cancellation_with_valid_partial_propagates(sdk, monkeypatch):
    error = sdk.Cancelled()
    error.partial = SimpleNamespace(text=json.dumps(PROPOSAL), finish_reason='stop', truncated=False)

    def cancelled(*args, **kwargs):
        raise error

    monkeypatch.setattr(sdk, 'complete', cancelled)
    for dispatch in (cancelled, make_dispatch(sdk.Endpoint('openrouter'), 'm')):
        with pytest.raises(sdk.Cancelled) as raised:
            generate_draft(dispatch, {}, 'Echo')
        assert raised.value is error


@pytest.mark.parametrize('settings, expected', [
    ({'model': ' m ', 'temperature': 1}, {'model': 'm', 'temperature': 1, 'reasoning': None, 'max_tokens': None}),
    ({'model': ' m ', 'temperature': 1, 'top_p': 0.8}, {'model': ' m ', 'temperature': 1, 'top_p': 0.8}),
    ({'model': ' m ', 'max_token': 1}, {'model': ' m ', 'max_token': 1}),
])
def test_legacy_normalization_and_passthrough_make_fresh_mappings(settings, expected):
    calls = []

    def dispatch(materials, config):
        assert config is not settings and config == expected
        calls.append(config)
        config.clear()
        return SimpleNamespace(text='{' if len(calls) == 1 else json.dumps(PROPOSAL),
                               finish_reason='stop', truncated=False)

    generate_draft(dispatch, settings, 'Echo')
    assert len(calls) == 2 and calls[0] is not calls[1]
