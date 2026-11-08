"""Public API contract a host application can rely on, with real Monty execution."""
import threading
from decimal import Decimal
from importlib.metadata import version

import scriptspell as ss


def proposal(source, **extra):
    return dict(source=source, summary='Synthetic test', assumptions=[],
                unmet_requirements=[], **extra)


def test_library_version_agrees_with_metadata_and_profile():
    assert ss.__version__ == version('scriptSpell') == ss.profile()['version']


def test_author_validate_test_and_execute_saved_source():
    materials = ss.prepare_authoring('Apply an exact threshold.', {
        'inputs': {'vaf': 'Decimal'}, 'outputs': {'eligible': 'boolean'}})
    assert materials['profile']['version'] == ss.__version__
    candidate = proposal('from decimal import Decimal\ndef transform(inputs):\n'
                         '    return {"eligible": inputs["vaf"] >= Decimal("0.05")}')
    assert ss.validate_proposal(candidate)['outcome'] == 'ok'
    for value, expected in [('0.049999999999999999', False), ('0.05', True)]:
        result = ss.run(candidate['source'], {'vaf': Decimal(value)}, ['eligible'])
        assert result['outcome'] == 'ok', result
        assert result['values'] == {'eligible': expected}
        assert result['metadata']['version'] == ss.__version__
        assert result['metadata']['profile'] == materials['profile']['profile']


def test_validation_is_not_runtime_or_business_acceptance():
    candidate = proposal('def transform(inputs):\n    return {"wrong_name": 1}')
    candidate['unmet_requirements'] = ['Needs human review']
    assert ss.validate_proposal(candidate)['outcome'] == 'ok'
    result = ss.run(candidate['source'], {}, ['expected_name'])
    assert result['outcome'] != 'ok'
    assert 'values' not in result


def test_repair_keeps_interface_and_has_bounded_schema():
    interface = {'inputs': {'text': 'string'}, 'outputs': {'out': 'string'}}
    materials = ss.prepare_authoring('Trim', interface,
                                     diagnostics={'outcome': 'source_rejected'})
    assert 'source_rejected' in materials['user']
    for name in ('assumptions', 'unmet_requirements'):
        spec = materials['response_schema']['properties'][name]
        assert spec['items']['maxLength'] == 4096
        candidate = proposal('def transform(inputs):\n    return {"out": "ok"}')
        candidate[name] = ['x' * 4097]
        assert ss.validate_proposal(candidate)['outcome'] == 'invalid_proposal'


def test_host_stop_and_invalid_data_never_publish_values():
    stop = threading.Event()
    stop.set()
    source = 'def transform(inputs):\n    return {"out": 1}'
    cancelled = ss.run(source, {}, ['out'], cancel=stop)
    assert cancelled['outcome'] == 'cancelled'
    assert 'values' not in cancelled
    invalid = ss.run(source, {'unsupported': 0.5}, ['out'])
    assert invalid['outcome'] == 'invalid_inputs'
    assert 'values' not in invalid
