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
    assert 'up to 3 paid requests' in capsys.readouterr().out


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
    assert '- labels: list[str]' in calls[0]['user']
    assert 'expected str, got bool' in calls[1]['user']
    assert calls[1]['user'].endswith(rejected)
    assert report['examples_validation'] == dict(attempted=1, first_pass=0, final_pass=1,
                                                  first_pass_rate=0.0, final_pass_rate=1.0)


def test_yaml_presets_render_fixed_shapes(staged, capsys):
    assert staged.main(['--mode', 'two-call', '--examples-only', '--difficulty', 'all',
                        '--dry-run']) == 0
    output = capsys.readouterr().out
    assert 'up to 120 paid requests' in output
    assert output.count('Required YAML shape') == 60
    assert 'inputs.departments[].teams[].staff[] requires id' in output
