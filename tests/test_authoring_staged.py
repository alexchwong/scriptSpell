"""Exercise staged authoring without paid requests."""
import json
from types import SimpleNamespace

from scripts.check_authoring_staged import evaluate, main
from scriptspell.prompt_files import task_text


SETTINGS = {'model': 'test/model'}
INTERFACE = {'inputs': {'n': 'integer'}, 'outputs': {'out': 'integer'}}


def test_three_stages_execute_and_hold_back_cases():
    calls = []
    replies = iter([
        json.dumps(dict(interface=INTERFACE, examples=[{'n': 1}, {'n': 2}, {'n': 3}])),
        json.dumps(dict(outputs={'1': {'out': 2}, '2': {'out': 4}, '3': {'out': 6}})),
        '```python\ndef transform(inputs):\n    return {"out": inputs["n"] * 2}\n```',
    ])

    def send(materials, settings):
        calls.append(materials)
        return SimpleNamespace(text=next(replies), truncated=False, finish_reason='stop')

    report = evaluate(send, SETTINGS, 'Double n', 3)
    assert report['status'] == 'PASS'
    assert report['held_back'] == {'total': 2, 'passed': 2}
    assert [case['visible'] for case in report['examples']] == [True, False, False]
    assert calls[1]['user'] == task_text('Double n', interface=INTERFACE,
                                         inputs={'1': {'n': 1}, '2': {'n': 2}, '3': {'n': 3}})
    assert calls[2]['user'] == task_text('Double n', interface=INTERFACE,
                                         example_input={'n': 1}, expected_output={'out': 2})
    assert 'response_schema' not in calls[2]
    assert [attempt['stage'] for attempt in report['attempts']] == ['inputs', 'expectations', 'python']


def test_bad_expectation_stops_without_retry_or_source_call():
    replies = iter(['{"examples":[{"n":1}]}', '{"outputs":{"1":{"out":true}}}'])

    def send(materials, settings):
        return SimpleNamespace(text=next(replies), truncated=False, finish_reason='stop')

    report = evaluate(send, SETTINGS, 'Double n', 1, interface=INTERFACE)
    assert report['failed_stage'] == 'expectations'
    assert report['attempts'][-1]['validation']['field'] == 'outputs.1.out'
    assert len(report['attempts']) == 2


def test_staged_preview_has_correct_budget(capsys):
    assert main(['--dry-run', '--task', '01']) == 0
    assert 'up to 3 paid requests' in capsys.readouterr().out
