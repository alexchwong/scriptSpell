"""Offline regression checks for the public authoring workflow and revision boundaries."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scriptspell import AuthoringError, AuthoringSession, generate_draft, prepare_authoring

SOURCE = 'def transform(inputs):\n    return {"out": inputs["text"].strip()}'
SETTINGS = {'model': 'test/model'}


def case(text, expected):
    return dict(example_input={'text': text}, expected_output={'out': expected})


def proposal(**parts):
    return dict(source=SOURCE, summary='Trim', assumptions=[], unmet_requirements=[], **parts)


def reply(value, *, truncated=False, calls=None):
    def dispatch(materials, settings):
        if calls is not None:
            calls.append((materials, settings))
        return SimpleNamespace(text=json.dumps(value), truncated=truncated, finish_reason='stop')
    return dispatch


def test_generation_keeps_default_schema_and_applies_strict_multi_contract():
    calls = []
    p = proposal(**case(' x ', 'x'))
    draft = generate_draft(reply(p, calls=calls), SETTINGS, 'Trim')
    assert len(calls) == 1 and calls[0][0]['system'] == prepare_authoring('Trim')['system']
    assert all(calls[0][1][key] is None for key in ('temperature', 'reasoning', 'max_tokens'))
    assert draft['examples'][0]['expected_output'] == {'out': 'x'}

    cases = [case(' a ', 'a'), case(' b ', None)]
    draft = generate_draft(reply(proposal(examples=cases), calls=calls), SETTINGS, 'Trim',
                           example_count=2, examples=[{'inputs': {'text': ' a '}}])
    assert len({item['id'] for item in draft['examples']}) == 2
    assert len(calls) == 2
    schema = calls[-1][0]['response_schema']['properties']['examples']
    assert schema['minItems'] == schema['maxItems'] == 2
    with pytest.raises(AuthoringError, match='wrong_example_count'):
        generate_draft(reply(proposal(examples=cases), calls=calls), SETTINGS, 'Trim', example_count=3)
    with pytest.raises(AuthoringError, match='supplied_example_changed'):
        generate_draft(reply(proposal(examples=cases)), SETTINGS, 'Trim', example_count=2,
                       examples=[{'outputs': {'out': True}}])
    with pytest.raises(AuthoringError, match='invalid_example_contract'):
        generate_draft(reply(proposal(examples=[cases[0], dict(cases[1], expected_output={'wrong': None})])),
                       SETTINGS, 'Trim', example_count=2)
    with pytest.raises(AuthoringError, match='conflicting_example_count'):
        generate_draft(reply(p, calls=calls), SETTINGS, 'Trim', examples=[{'inputs': {}}, {'inputs': {}}])
    assert len(calls) == 3


def test_correction_failure_regression_restore_and_export(tmp_path):
    session = AuthoringSession(tmp_path)
    p = proposal(examples=[case(' a ', 'a'), case(' b ', None)])
    original = session.generate(None, reply(p), SETTINGS, 'Trim', example_count=2)
    snapshot = session.snapshot()
    examples = snapshot['revision']['draft']['examples']
    first, second = (case['id'] for case in examples)
    results = session.run(original)
    assert [report['status'] for report in results] == ['pass', 'mismatch']
    results[0]['expected']['out'] = 'external mutation'
    snapshot = session.snapshot()
    snapshot['reports'][0]['expected']['out'] = 'external mutation'
    assert session.snapshot()['reports'][0]['expected']['out'] == 'a'

    with pytest.raises(AuthoringError, match='incomplete_model_response'):
        session.generate(original, reply(p, truncated=True), SETTINGS, 'Trim', example_count=2)
    assert session.snapshot()['active_id'] == original
    assert session.snapshot()['attempts'][-1]['status'] == 'failed'

    repaired_source = 'def transform(inputs):\n    return {"out": None}'
    calls = []
    repair = session.improve(original, reply({'source': repaired_source}, calls=calls), SETTINGS, [second])
    attempt = session.attempt(repair)
    assert attempt['regressions'] == [first]
    assert [r['status'] for r in attempt['reports']] == ['mismatch', 'pass']
    evidence = json.loads(calls[0][0]['user'])['failures']
    assert len(evidence) == 1 and evidence[0]['expected'] == {'out': None}
    failing = session.decide(original, repair, True)
    assert session.snapshot()['revisions'][-1]['test_status'] == 'failing'

    restored = session.restore(failing, original)
    assert session.snapshot()['revision']['restored_from'] == original
    correction = session.correct(restored, reply({'expected_output': {'out': 'b'}}), SETTINGS, second, 'Trim b')
    assert session.snapshot()['revision']['draft']['examples'] == examples
    corrected = session.decide(restored, correction, True)
    assert session.snapshot()['revision']['draft']['examples'] == [examples[0], dict(examples[1], expected_output={'out': 'b'})]
    assert [r['status'] for r in session.snapshot()['reports']] == ['pass', 'pass']
    assert session.snapshot(original)['revision']['draft']['examples'] == examples

    pending = session.correct(corrected, reply({'expected_output': {'out': None}}), SETTINGS, second, 'Use null')
    newest = session.restore(corrected, original)
    with pytest.raises(AuthoringError, match='stale_attempt'):
        session.decide(newest, pending, True)
    assert session.attempt(pending)['status'] == 'stale'

    exports = [session.export(corrected), session.export(corrected)]
    assert exports[0]['path'] != exports[1]['path']
    for export in exports:
        path = Path(export['path'])
        assert path.read_bytes() == SOURCE.encode()
        assert json.loads(path.with_name('metadata.json').read_text()) == {
            'revision_id': corrected, 'test_status': 'passing'}
    journal = json.loads((session.directory / 'journal.json').read_text())
    assert journal['active_id'] == newest and journal['format_version'] == 1


def test_null_expected_and_execution_error_are_distinct(tmp_path):
    session = AuthoringSession(tmp_path)
    p = proposal(examples=[case('null', None), case('error', None)])
    p['source'] = 'def transform(inputs):\n    if inputs["text"] == "error":\n        raise ValueError("failed")\n    return {"out": None}'
    revision = session.generate(None, reply(p), SETTINGS, 'Check', example_count=2)
    match, error = session.run(revision)
    assert match['status'] == 'pass' and match['actual'] == {'out': None}
    assert error['status'] == 'error' and 'actual' not in error
