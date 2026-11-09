"""modelSpell adapter and exact-value display for the browser."""
import json

import modelspell
from scriptspell import AuthoringError
from scriptspell.workflow import display_json, parse_json

UIError = AuthoringError


def dispatch(endpoint, cancel, models):
    def complete(materials, settings):
        model = settings.pop('model')
        modelspell.check_settings(endpoint.kind, **settings)
        info = models.get(model)
        if settings['reasoning'] not in (None, 'off') and getattr(info, 'supports_reasoning', None) is False:
            raise modelspell.UnsupportedSetting('This model reports no reasoning support')
        return modelspell.complete(
            endpoint, model,
            [modelspell.Message('system', materials['system'] + '\nJSON response schema: ' +
                                json.dumps(materials['response_schema'])),
             modelspell.Message('user', materials['user'])],
            timeout=120, cancel=cancel, **settings)
    return complete


def settings(body):
    return {name: body.get(name) for name in ('model', 'temperature', 'reasoning', 'max_tokens')}


def _reports(reports):
    return {r['example_id']: dict(
        status=r['status'], outcome=r['outcome'],
        actual_json=display_json(r['actual']) if 'actual' in r else None) for r in reports}


def _draft(draft, reports):
    return dict(draft, examples=[
        dict(id=case['id'], input_json=display_json(case['example_input']),
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
