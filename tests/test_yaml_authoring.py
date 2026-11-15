from decimal import Decimal
from types import SimpleNamespace

import pytest

from scriptspell import AuthoringError, AuthoringSession, YamlAuthoring, run_examples
from scriptspell.workflow import same_value
from scriptspell.yaml_contract import YamlContractError, dump_examples, read_yaml, validate_examples


EXAMPLES = """interface:
  inputs:
    - x: float
    - exact: Decimal
  outputs:
    - values: list[float]
    - exact: Decimal
examples:
  - inputs:
      - x: 0.1
      - exact: '1.2300'
    outputs:
      - values: [0.3, 0.5]
      - exact: '1.2300'
  - inputs:
      - x: 1.0
      - exact: '0.10'
    outputs:
      - values: [1.2, 0.5]
      - exact: '0.10'
"""
CODE = '''def transform(inputs):
    return {"values": [inputs["x"] + float("0.2"), 1 / 2], "exact": inputs["exact"]}
'''
INVALID = """interface:
  inputs:
    - x: float
  outputs:
    - out: int
examples:
  - inputs:
      - x: true
      - x: 2.0
    outputs:
      - out: "1"
  - inputs:
      - wrong: 3.0
    outputs:
      - out: 2.5
extra: unused
"""


def response(text):
    return SimpleNamespace(text=text, finish_reason='stop', truncated=False)


def test_contract_reports_independent_errors_across_cases():
    with pytest.raises(YamlContractError) as error:
        validate_examples(INVALID, 3)
    issues = '\n'.join(error.value.details['issues'])
    for fragment in ("unexpected 'extra'", 'exactly 3 examples', "'x' appears more than once",
                     'examples[1].inputs.x: expected float, got bool',
                     'examples[1].outputs.out: expected int, got str',
                     "examples[2].inputs: add the missing 'x'",
                     "examples[2].inputs: remove the unexpected 'wrong'",
                     'examples[2].outputs.out: expected int, got float'):
        assert fragment in issues


@pytest.mark.parametrize('text, issue', [
    ('a: [1,\n', 'remaining content could not be validated'),
    ('a: 1\na: 2\n', 'key \'a\' is repeated'),
    ('a: &anchor [1]\nb: *anchor', 'without tags, anchors or aliases'),
    ('a: !!python/object:bad {}', 'without tags, anchors or aliases'),
    ('a: {<<: {x: 1}}', 'merge keys'),
    ('a: 1\n---\na: 2', 'exactly one YAML document'),
    ('a: .nan', 'finite number'),
    ('a: 1e999', 'finite number'),
])
def test_yaml_boundary(text, issue):
    with pytest.raises(YamlContractError) as error:
        validate_examples(text, 1)
    assert any(issue in item for item in error.value.details['issues'])


def test_yaml_scalar_round_trip_keeps_strings_and_float_types():
    original = {'values': ['1e3', 'yes', 'on', '2026-11-10', '.5', 'null', None, True, 0.5]}
    loaded, issues = read_yaml(dump_examples(original))
    assert not issues and loaded == original
    assert type(loaded['values'][-1]) is float
    data, issues = read_yaml('a: [.5, 1., yes, on, 2026-11-10]')
    assert not issues and data['a'] == [0.5, 1.0, 'yes', 'on', '2026-11-10']


def test_two_call_retry_is_verbatim_and_uses_only_first_case_for_coding(tmp_path):
    rejected = '\n' + INVALID + '\n'
    replies = iter([rejected, EXAMPLES, CODE])
    calls = []

    def send(materials, settings):
        calls.append(materials)
        return response(next(replies))

    flow = YamlAuthoring('Compute', 2)
    assert flow.generate('examples', send, {'model': 'test'})
    assert calls[1]['user'].endswith(rejected)
    assert 'expected int, got str' in calls[1]['user']
    assert "missing 'x'" in calls[1]['user']
    assert flow.generate('python', send, {'model': 'test'}) == []
    assert len(calls) == 3
    assert '1.2300' in calls[2]['system'] and "'0.10'" not in calls[2]['system']
    draft = flow.draft()
    assert [case['visible'] for case in draft['examples']] == [True, False]
    assert draft['examples'][0]['expected_output']['exact'] == Decimal('1.2300')
    session = AuthoringSession(tmp_path)
    revision = session.record_authored(None, draft)
    results = session.run(revision)
    assert [case['status'] for case in results] == ['pass', 'pass']
    assert results[0]['actual']['values'][0] == 0.30000000000000004
    assert '"$decimal": "1.2300"' in (session.directory / 'journal.json').read_text()
    flow.accept('examples', EXAMPLES)
    with pytest.raises(AuthoringError, match='stage_not_ready'):
        flow.draft()


def test_one_shot_valid_has_one_call_and_no_hidden_cases():
    reply = EXAMPLES + 'source: |\n' + ''.join('  ' + line for line in CODE.splitlines(keepends=True))
    calls = []
    flow = YamlAuthoring('Compute', 2, one_shot=True)
    assert flow.generate('one-shot', lambda materials, _: calls.append(materials) or response(reply),
                         {'model': 'test'}) == []
    assert len(calls) == 1
    assert all(case['visible'] for case in flow.draft()['examples'])
    assert all(case['status'] == 'pass' for case in run_examples(flow.draft()))


def test_retry_stops_after_second_error_and_bad_python_is_not_retried():
    calls = []
    flow = YamlAuthoring('Compute', 2, one_shot=True)

    def reject(materials, settings):
        calls.append(materials)
        return response('interface: [')

    with pytest.raises(YamlContractError) as error:
        flow.generate('one-shot', reject, {'model': 'test'})
    assert len(calls) == 2 and error.value.details['first_attempt'] and error.value.details['issues']

    def bad_python(materials, settings):
        calls.append(materials)
        return response(EXAMPLES + 'source: "not valid Python syntax"\n')

    with pytest.raises(AuthoringError, match='source_rejected'):
        flow.generate('one-shot', bad_python, {'model': 'test'})
    assert len(calls) == 3


def test_float_tolerance_is_recursive_and_type_sensitive():
    assert same_value({'values': [0.1 + 0.2, 1e-13]}, {'values': [0.3, 0.0]})
    assert not same_value([1.0], [1])
    assert not same_value(1.0, Decimal('1.0'))
    assert not same_value(Decimal('1.0000000001'), Decimal('1'))
    assert not same_value(0.001, 0.0)


def test_fixed_contract_checks_nested_rows_even_when_echo_is_missing():
    from scriptspell.prompt_files import load_preset_contracts

    contract = load_preset_contracts()['08']
    text = """interface:
  outputs:
    - result: list[str]
examples:
  - inputs:
      - departments:
          - id: 1
            teams:
              - id: 2
                staff:
                  - name: Alice
    outputs:
      - result:
          - department_id: 1
            team_id: false
"""
    with pytest.raises(YamlContractError) as error:
        validate_examples(text, 1, **contract)
    issues = error.value.details['issues']
    assert any("interface: add the missing 'inputs'" in issue for issue in issues)
    assert any("interface.outputs.result: use the exact type 'list[dict]'" in issue for issue in issues)
    assert any("staff[1]: add the missing 'id'" in issue for issue in issues)
    assert any("staff[1]: remove the unexpected 'name'" in issue for issue in issues)
    assert any("result[1]: add the missing 'staff_id'" in issue for issue in issues)
    assert any('result[1].team_id:' in issue for issue in issues)


def test_nested_decimal_is_normalised_without_changing_yaml():
    from scriptspell.prompt_files import load_preset_contracts

    flow = YamlAuthoring('Classify readings', **load_preset_contracts()['05'])
    flow.accept('examples', """interface:
  inputs:
    - readings: list[dict]
    - lower: int | Decimal
    - upper: int | Decimal
  outputs:
    - below: list[dict]
    - within: list[dict]
    - above: list[dict]
    - missing: list[dict]
examples:
  - inputs:
      - readings: [{value: '1.1'}, {}]
      - lower: '1.0'
      - upper: '2.0'
    outputs:
      - below: []
      - within: [{value: '1.1'}]
      - above: []
      - missing: [{}]
""")
    assert flow.pairs[0]['inputs']['readings'] == [{'value': Decimal('1.1')}, {}]
    assert "value: '1.1'" in flow.examples_yaml()


def test_concordance_comparison_stays_order_and_type_sensitive():
    # Generated expectations are not authoritative; agreement must be exact, including list order.
    assert same_value([{'index': 0, 'field': 'id'}, {'index': 0, 'field': 'quantity'}],
                      [{'index': 0, 'field': 'id'}, {'index': 0, 'field': 'quantity'}])
    assert not same_value([{'index': 0, 'field': 'id'}, {'index': 0, 'field': 'quantity'}],
                          [{'index': 0, 'field': 'quantity'}, {'index': 0, 'field': 'id'}])
    assert not same_value({'out': 1}, {'out': True})
