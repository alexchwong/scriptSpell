"""Prompt previews and exact-value display for the browser."""
from scriptspell import AuthoringError, model_messages
from scriptspell.workflow import display_json, parse_json

UIError = AuthoringError


def prompt_preview(materials):
    system, user = model_messages(materials)
    full_system = system['content']
    original = materials['system']
    schema = full_system[len(original) + 1:] if materials.get('response_schema') is not None else None
    return dict(system=original, user=user['content'], schema=schema, full_system=full_system)


def _reports(reports):
    return {r['example_id']: dict(
        status=r['status'], outcome=r['outcome'],
        actual_json=display_json(r['actual']) if 'actual' in r else None) for r in reports}


def _draft(draft, reports):
    return dict(draft, examples=[
        dict(id=case['id'], visible=case.get('visible'), input_json=display_json(case['example_input']),
             expected_json=display_json(case['expected_output']), result=reports.get(case['id']))
        for case in draft['examples']])


def view(session, revision_id=None):
    snapshot = session.snapshot(revision_id)
    reports = _reports(snapshot.pop('reports'))
    if snapshot['revision'] is not None:
        revision = snapshot['revision']
        revision['draft'] = _draft(revision['draft'], reports)
    return snapshot


def attempt_view(session, attempt_id):
    attempt = session.attempt(attempt_id)
    reports = _reports(attempt.pop('reports'))
    if attempt['action'] == 'correct_expected' and 'candidate' in attempt:
        original = session.snapshot(attempt['revision_id'])['revision']['draft']
        case = next(case for case in original['examples'] if case['id'] == attempt['example_id'])
        attempt['previous_expected_json'] = display_json(case['expected_output'])
    if 'candidate' in attempt:
        attempt['candidate'] = _draft(attempt['candidate'], reports)
    return attempt
