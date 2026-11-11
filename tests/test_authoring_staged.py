"""Exercise staged authoring without paid requests."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scriptspell.prompt_files import task_text

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / 'scripts/check_authoring_staged.py').exists(),
                                reason='repository-only authoring tooling')


@pytest.fixture
def staged(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts import check_authoring_staged
    return check_authoring_staged


SETTINGS = {'model': 'test/model'}
INTERFACE = {'inputs': {'n': 'integer'}, 'outputs': {'out': 'integer'}}


def test_three_stages_execute_and_hold_back_cases(staged):
    calls = []
    replies = iter([
        json.dumps(dict(interface=INTERFACE, examples=[{'n': 1}, {'n': 2}, {'n': 3}])),
        json.dumps(dict(outputs={'1': {'out': 2}, '2': {'out': 4}, '3': {'out': 6}})),
        '```python\ndef transform(inputs):\n    return {"out": inputs["n"] * 2}\n```',
    ])

    def send(materials, settings):
        calls.append(materials)
        return SimpleNamespace(text=next(replies), truncated=False, finish_reason='stop')

    report = staged.evaluate(send, SETTINGS, 'Double n', 3)
    assert report['status'] == 'PASS'
    assert report['held_back'] == {'total': 2, 'passed': 2}
    assert [case['visible'] for case in report['examples']] == [True, False, False]
    assert calls[1]['user'] == task_text('Double n', interface=INTERFACE,
                                         inputs={'1': {'n': 1}, '2': {'n': 2}, '3': {'n': 3}})
    assert calls[2]['user'] == task_text('Double n', interface=INTERFACE,
                                         example_input={'n': 1}, expected_output={'out': 2})
    assert 'response_schema' not in calls[2]
    assert [attempt['stage'] for attempt in report['attempts']] == ['inputs', 'expectations', 'python']


def test_bad_expectation_stops_without_retry_or_source_call(staged):
    replies = iter(['{"examples":[{"n":1}]}', '{"outputs":{"1":{"out":true}}}'])

    def send(materials, settings):
        return SimpleNamespace(text=next(replies), truncated=False, finish_reason='stop')

    report = staged.evaluate(send, SETTINGS, 'Double n', 1, interface=INTERFACE)
    assert report['failed_stage'] == 'expectations'
    assert report['attempts'][-1]['validation']['field'] == 'outputs.1.out'
    assert len(report['attempts']) == 2


def test_staged_preview_has_correct_budget(staged, capsys):
    assert staged.main(['--dry-run', '--task', '01']) == 0
    assert 'up to 3 logical calls and 3 HTTP attempts' in capsys.readouterr().out


def test_examples_only_records_retry_without_calling_python(staged, monkeypatch, tmp_path):
    calls = []
    good = """interface:
  inputs:
    - labels: list[str]
  outputs:
    - result: list[str]
examples:
  - inputs:
      - labels: [' A ']
    outputs:
      - result: [a]
"""
    rejected = good.replace('list[str]', 'list[int]', 1).replace("[' A ']", '[false]')
    replies = iter([rejected, good])

    def send(materials, settings):
        calls.append(materials)
        return SimpleNamespace(text=next(replies), truncated=False, finish_reason='stop')

    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr(staged, 'dispatch', lambda *args, **kwargs: send)
    path = tmp_path / 'report.json'
    assert staged.main(['--mode', 'two-call', '--examples-only', '--task', '01',
                        '--report', str(path)]) == 0
    report = json.loads(path.read_text())
    assert report['request_count'] == len(calls) == 2
    result = report['results'][0]
    assert [attempt['stage'] for attempt in result['attempts']] == ['examples', 'examples']
    assert not result['executed'] and not result['valid_draft']
    assert 'Copy the interface below unchanged' in calls[0]['user']
    assert '    labels: list[str]' in calls[0]['user']
    assert '- labels: list[str]' not in calls[0]['user']
    assert result['attempts'][1]['repair_echo'] is False
    assert 'expected str, got bool' in calls[1]['user']
    assert calls[1]['user'].endswith(rejected)
    assert report['examples_validation'] == dict(attempted=1, first_pass=0, final_pass=1,
                                                  first_pass_rate=0.0, final_pass_rate=1.0,
                                                  first_pass_evaluated=1, final_pass_evaluated=1,
                                                  first_pass_unevaluated=0, final_pass_unevaluated=0)


def test_yaml_presets_render_fixed_shapes(staged, capsys):
    assert staged.main(['--mode', 'two-call', '--examples-only', '--difficulty', 'all',
                        '--dry-run']) == 0
    output = capsys.readouterr().out
    assert 'up to 120 logical calls and 120 HTTP attempts' in output
    assert output.count('Required YAML shape') == 60
    assert 'inputs.departments[].teams[].staff[] requires id' in output


LABELS = """interface:
  inputs: {labels: 'list[str]'}
  outputs: {result: 'list[str]'}
examples:
  - inputs: {labels: [' A ']}
    outputs: {result: [a]}
"""

PYTHON = """def transform(inputs):
    return {'result': ['a']}
"""


def reply(text):
    return SimpleNamespace(text=text, truncated=False, finish_reason='stop')


def shared_limit(staged):
    body = json.dumps({'user_id': 'private-account', 'error': {
        'code': 429, 'message': 'secret-test-key', 'metadata': {
            'provider_name': 'Parasail', 'limit_source': 'upstream_provider_shared_pool',
            'raw': 'private-metadata'}}})
    return staged.modelspell.BackendError('provider error', status=429, body=body)


@pytest.mark.parametrize('after_rejected', [False, True])
def test_provider_block_leaves_unobserved_yaml_validation_unknown(staged, after_rejected):
    replies = iter(([reply('interface: [')] if after_rejected else []) + [shared_limit(staged)])

    def send(*_):
        value = next(replies)
        if isinstance(value, Exception):
            raise value
        return value

    result = staged.evaluate(send, SETTINGS, 'Normalize labels', 1, mode='two-call')
    assert result['status'] == 'BLOCKED'
    assert result['examples_first_pass'] is (False if after_rejected else None)
    assert result['examples_valid'] is None
    assert 'validation' not in result['attempts'][-1]
    assert staged.yaml_counts([result])['final_pass_evaluated'] == 0
    error = result['attempts'][-1]['provider_error']
    assert error['provider_name'] == 'Parasail'
    assert not any(value in json.dumps(result) for value in ('private-account', 'private-metadata', 'secret-test-key'))


def test_atomic_checkpoint_resume_skips_accepted_examples_and_completed_task(staged, monkeypatch, tmp_path):
    original = tmp_path / 'first.json'
    resumed = tmp_path / 'resumed.json'
    flags = ['--mode', 'two-call', '--task', '01', '--task', '02']
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr(staged, 'sleep', lambda _: None)
    dedup = """interface:
  inputs: {records: 'list[dict]'}
  outputs: {result: 'list[dict]'}
examples:
  - inputs: {records: [{id: 1}, {id: 1}]}
    outputs: {result: [{id: 1}]}
"""
    dedup_python = "def transform(inputs):\n    return {'result': [inputs['records'][0]]}\n"
    replies = iter([reply(LABELS), reply(PYTHON), reply(dedup), shared_limit(staged)])
    calls = []

    def send(materials, settings):
        calls.append(materials)
        value = next(replies)
        if isinstance(value, Exception):
            partial = json.loads(original.read_text())
            assert partial['results'][-1]['reason'] == 'python_pending'
            assert partial['results'][-1]['examples_valid']
            raise value
        return value

    monkeypatch.setattr(staged, 'dispatch', lambda *args, **kwargs: send)
    assert staged.main(flags + ['--report', str(original)]) == 2
    old = original.read_bytes()
    assert len(calls) == 4
    old_report = json.loads(old)
    assert [case['status'] for case in old_report['results']] == ['PASS', 'BLOCKED']

    with pytest.raises(SystemExit) as error:
        staged.main(flags + ['--examples', '2', '--resume', str(original), '--report', str(resumed)])
    assert error.value.code == 2 and len(calls) == 4 and not resumed.exists()

    replies = iter([reply(dedup_python)])
    assert staged.main(flags + ['--resume', str(original), '--report', str(resumed)]) == 0
    assert original.read_bytes() == old
    assert len(calls) == 5
    assert calls[-1] == calls[-2]  # Identical Python prompt, including the original visible case.
    report = json.loads(resumed.read_text())
    assert report['previous_request_count'] == 4
    assert report['invocation_request_count'] == 1
    assert report['request_count'] == 5
    assert report['results'][0] == old_report['results'][0]
    assert [attempt['stage'] for attempt in report['results'][1]['attempts']] == ['examples', 'python', 'python']
    assert report['resumed_from']['sha256'] == staged.digest(old)


@pytest.mark.parametrize('error_type, expected_calls', [('shared', 2), ('credits', 1), ('auth', 1),
                                                         ('timeout', 2), ('unknown_429', 1)])
def test_batch_stop_is_bounded(staged, monkeypatch, tmp_path, error_type, expected_calls):
    errors = {'shared': shared_limit(staged), 'credits': staged.modelspell.BackendError(status=402),
              'auth': staged.modelspell.AuthError(status=403), 'timeout': staged.modelspell.RequestTimeout(),
              'unknown_429': staged.modelspell.BackendError(status=429)}
    attempts, waits = [], []

    def send(materials, settings):
        attempts.append(materials)
        raise errors[error_type]

    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr(staged, 'dispatch', lambda *args, **kwargs: send)
    monkeypatch.setattr(staged, 'sleep', waits.append)
    report_path = tmp_path / 'report.json'
    assert staged.main(['--mode', 'two-call', '--task', '01', '--task', '02', '--task', '03',
                        '--report', str(report_path)]) == 2
    report = json.loads(report_path.read_text())
    assert len(attempts) == report['request_count'] == expected_calls
    assert len(waits) == expected_calls - 1
    assert report['examples_validation']['first_pass_unevaluated'] == expected_calls
    if expected_calls == 2:
        assert attempts[0] != attempts[1]  # Independent task, no automatic call replay.


@pytest.mark.parametrize('kind', ['interrupt', 'cancel'])
def test_interrupt_persists_partial_attempt(staged, monkeypatch, tmp_path, kind):
    def send(*_):
        if kind == 'interrupt':
            raise KeyboardInterrupt
        error = staged.modelspell.Cancelled()
        error.sent = True
        raise error

    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr(staged, 'dispatch', lambda *args, **kwargs: send)
    path = tmp_path / 'report.json'
    assert staged.main(['--mode', 'two-call', '--task', '01', '--task', '02', '--report', str(path)]) == 130
    report = json.loads(path.read_text())
    assert report['interrupted'] and report['request_count'] == 1
    assert staged._uncertain(report['results'][0])


def test_agreement_can_pass_while_independent_join_checks_fail(staged, capsys):
    contract = staged.load_preset_contracts()['09']
    cases = """interface:
  inputs: {orders: 'list[dict]', customers: 'list[dict]'}
  outputs: {result: 'list[dict]'}
examples:
  - inputs:
      orders: [{customer_id: 1, order_id: O1}]
      customers: [{id: 1, name: A}]
    outputs:
      result: [{customer_id: 1, customer_name: A}]
"""
    python = """def transform(inputs):
    names = {row['id']: row['name'] for row in inputs['customers']}
    return {'result': [{'customer_id': row['customer_id'], 'customer_name': names.get(row['customer_id'])}
                       for row in inputs['orders']]}
"""
    calls = []
    replies = iter([reply(cases), reply(python)])

    def send(materials, _):
        calls.append(materials)
        return next(replies)

    result = staged.evaluate(send, SETTINGS, 'Join records', 1, mode='two-call', task='09', **contract)
    assert result['status'] == 'PASS' and result['verified']['status'] == 'FAIL'
    assert result['reference']['generated_expectation']['status'] == 'FAIL'
    assert result['reference']['python_actual']['status'] == 'FAIL'
    assert all('total_cents' not in materials['system'] + materials['user'] for materials in calls)
    staged.print_task(dict(result, task='09', title='Join records', difficulty='easy'))
    output = capsys.readouterr().out
    assert 'agreement PASS · fixed verification FAIL' in output
    assert '$.result[0].order_id' in output


def test_reference_checks_eligibility_and_order_independent_errors(staged):
    from decimal import Decimal

    from scripts.staged_verification import reference_verification

    sample = dict(example_input={'readings': [{'value': Decimal('2.0')}, {}],
                                 'lower': Decimal('2'), 'upper': Decimal('2.00')},
                  expected_output={'below': [], 'above': [{'value': Decimal('2.0')}],
                                   'within': [], 'missing': [{}]}, visible=True)
    actual = {'below': [], 'above': [], 'within': [{'value': Decimal('2.0')}], 'missing': [{}]}
    mixed = dict(sample, example_input=dict(sample['example_input'], lower=2), visible=False)
    ref = reference_verification('05', [sample, mixed], [{'actual': actual}])
    assert ref['generated_expectation']['status'] == 'FAIL'
    assert ref['python_actual']['status'] == 'PASS'
    assert ref['python_actual']['eligible'] == 1
    assert ref['cases'][1]['outcome'] == 'input_out_of_spec'

    errors = [{'index': 0, 'field': 'id'}, {'index': 0, 'field': 'quantity'}]
    sample = dict(example_input={'orders': [{'quantity': False, 'unit_price_cents': 0}]},
                  expected_output={'errors': errors[::-1]}, visible=True)
    ref = reference_verification('07', [sample], [{'actual': {'errors': errors + errors[:1]}}])
    assert ref['generated_expectation']['status'] == 'PASS'
    assert ref['python_actual']['status'] == 'FAIL'
