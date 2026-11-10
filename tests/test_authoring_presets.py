"""Offline coverage for preset selection and batch evaluation through real Monty."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / 'scripts/check_authoring_presets.py').exists(),
                                reason='repository-only authoring tools')


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts import check_authoring_presets
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    return check_authoring_presets


def test_default_and_all_preview_without_key(runner, capsys, tmp_path):
    report = tmp_path / 'preview.json'
    assert runner.main(['--dry-run', '--report', str(report)]) == 0
    preview = capsys.readouterr().out
    assert 'up to 40 paid requests' in preview and preview.count('[medium]') == 20
    assert runner.main(['--dry-run', '--difficulty', 'all', '--report', str(report)]) == 0
    preview = capsys.readouterr().out
    assert 'up to 120 paid requests' in preview
    assert all(preview.count(f'[{level}]') == 20 for level in runner.DIFFICULTIES)
    assert not report.exists()


def test_batch_continues_after_mismatch_and_reports_exact_values(runner, monkeypatch, tmp_path):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only-secret')
    requests = []

    def complete(endpoint, model, messages, **settings):
        requests.append((model, messages[1].content.split('\n\nExample count')[0].removeprefix('Task\n\n'), settings))
        pair = dict(example_input={'n': 9007199254740993}, expected_output={'out': 9007199254740993})
        other = dict(example_input={'n': 2}, expected_output={'out': 1 if len(requests) == 1 else 2})
        payload = dict(source='def transform(inputs):\n    return {"out": inputs["n"]}',
                       summary='Echo', assumptions=[], unmet_requirements=[], examples=[pair, other])
        return SimpleNamespace(text=json.dumps(payload), finish_reason='stop', truncated=False)

    monkeypatch.setattr(runner.modelspell, 'complete', complete)
    path = tmp_path / 'batch.json'
    assert runner.main(['--task', '01', '--task', '02', '--difficulty', 'hard', '--examples', '2',
                        '--temperature', '0.4', '--reasoning', 'low', '--max-tokens', '600',
                        '--model', 'test/model', '--timeout', '30', '--report', str(path)]) == 1
    report = json.loads(path.read_text())
    assert report['status'] == 'FAIL' and report['tasks_requested'] == 2
    assert [entry['status'] for entry in report['results']] == ['FAIL', 'PASS']
    assert [request[1] for request in requests] == [variants['hard'] for _, variants in runner.PRESETS[:2]]
    for model, _, settings in requests:
        assert model == 'test/model'
        assert settings['temperature'] == 0.4 and settings['reasoning'] == 'low'
        assert settings['max_tokens'] == 600 and settings['timeout'] == 30
    examples = report['results'][0]['examples']
    assert examples[0]['status'] == 'pass' and '9007199254740993' in examples[0]['actual_json']
    assert examples[1]['status'] == 'mismatch' and json.loads(examples[1]['actual_json']) == {'out': 2}
    assert 'test-only-secret' not in path.read_text()


def test_transport_failure_stops_batch(runner, monkeypatch, tmp_path):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only-secret')
    calls = []

    def blocked(*args, **kwargs):
        calls.append(True)
        raise runner.modelspell.AuthError('test-only-secret')

    monkeypatch.setattr(runner.modelspell, 'complete', blocked)
    path = tmp_path / 'blocked.json'
    assert runner.main(['--report', str(path)]) == 2
    assert len(calls) == 1
    report = json.loads(path.read_text())
    assert report['status'] == 'BLOCKED' and report['tasks_requested'] == 20
    assert report['results'][0]['outcome'] == 'AuthError'
    assert 'test-only-secret' not in path.read_text()


def test_report_keeps_both_attempts_and_rejected_source(runner):
    raw = '{"source":'
    invalid = {
        'source': 'def transform(inputs):\n    return open("file")',
        'summary': 'Read a file', 'assumptions': [], 'unmet_requirements': [],
        'example_input': {}, 'expected_output': {'out': ''},
    }
    responses = iter((raw, json.dumps(invalid)))

    def send(materials, settings):
        return SimpleNamespace(text=next(responses), truncated=False, finish_reason='stop',
                               model='test/model', provider='test', response_id='response')

    result = runner.evaluate(send, {'model': 'test/model'}, 'Read a file', 1)
    first, second = result['attempts']
    assert first['response']['text'] == raw
    assert first['validation']['outcome'] == 'invalid_json'
    assert first['validation']['line'] == 1
    assert first['request']['user'] == second['request']['user']
    assert 'Return one raw JSON object' in second['request']['system']
    assert json.loads(second['response']['text'])['source'] == invalid['source']
    assert second['validation']['field'] == 'source'
    assert any(issue['line'] == 2 for issue in second['validation']['issues'])
    assert result['outcome'] == 'source_rejected'
