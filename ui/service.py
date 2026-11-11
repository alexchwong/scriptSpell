"""modelSpell adapter and exact-value display for the browser."""
import json
import re
import time

import modelspell
from scriptspell import AuthoringError
from scriptspell.workflow import display_json, parse_json

UIError = AuthoringError

# Bounded HTTP 429 recovery for one logical model request. Provider retries are separate from
# the single YAML-content correction request: each logical request has its own budget.
MAX_429_RETRIES = 3
BACKOFF_SECONDS = (1, 2, 4)
_POLL_SECONDS = 0.1
_BODY_LIMIT = 16384
_SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._()+/:-]{0,63}')
_SAFE_CODE = re.compile(r'[A-Za-z0-9_.-]{1,32}')
_sleep = time.sleep


class RateLimitExhausted(modelspell.BackendError):
    """Every permitted attempt for one logical request ended in HTTP 429.

    Only allowlisted facts are kept; the raw upstream body is deliberately discarded.
    """

    def __init__(self, rate_limit, secondary=()):
        super().__init__('rate limited: retry budget exhausted', status=429, body='')
        self.rate_limit = dict(rate_limit)
        self.secondary = [dict(item) for item in secondary]


def rate_limit_facts(exc):
    """Allowlisted facts from an untrusted 429 body: provider name and error code only."""
    facts = {}
    body = getattr(exc, 'body', '')
    if type(body) is str and len(body) <= _BODY_LIMIT:
        try:
            document = json.loads(body)
        except (ValueError, RecursionError):
            document = None
        error = document.get('error') if type(document) is dict else None
        if type(error) is dict:
            metadata = error.get('metadata')
            name = metadata.get('provider_name') if type(metadata) is dict else None
            if type(name) is str and _SAFE_NAME.fullmatch(name):
                facts['provider_name'] = name
            code = error.get('code')
            if (type(code) is int and 0 <= code < 1000) or (type(code) is str and _SAFE_CODE.fullmatch(code)):
                facts['error_code'] = code
    provider = 'provider_name' in facts
    facts['scope'] = 'provider' if provider else 'account_or_unknown'
    facts['classification'] = 'rate_limited_provider' if provider else 'rate_limited_account_or_unknown'
    return facts


def is_rate_limit(exc):
    return isinstance(exc, modelspell.BackendError) and getattr(exc, 'status', None) == 429


def exclusion_tags(rows, provider_name):
    """Every endpoint tag of the named provider, or None when exclusion would be partial or total."""
    if not rows:
        return None
    matched = [row for row in rows if row.name == provider_name]
    if not matched or any(not row.slug for row in matched):
        return None
    if all(row.name == provider_name for row in rows):
        return None  # No publicly listed endpoint would remain.
    return list(dict.fromkeys(row.slug for row in matched))


def _safe_text(value):
    return value if type(value) is str and _SAFE_NAME.fullmatch(value) else None


def _check_cancel(cancel):
    if cancel is not None and cancel.cancelled:
        error = modelspell.Cancelled('cancelled before a rate-limit retry')
        error.sent = False
        raise error


def _wait(seconds, cancel, sleep):
    remaining = seconds
    while remaining > 0:
        _check_cancel(cancel)
        step = min(_POLL_SECONDS, remaining)
        sleep(step)
        remaining -= step


def prompt_preview(materials):
    system = materials['system']
    schema = materials.get('response_schema')
    schema_text = None if schema is None else 'JSON response schema: ' + json.dumps(schema)
    return dict(system=system, user=materials['user'], schema=schema_text,
                full_system=system if schema_text is None else system + '\n' + schema_text)


def dispatch(endpoint, cancel, models, *, timeout=120, max_429_retries=MAX_429_RETRIES,
             observer=None, sleep=None):
    """Return send(materials, settings) for one logical model request with bounded 429 recovery.

    Only HTTP 429 is retried, on the same model, messages and settings. On the first
    provider-attributed 429 the request may be retried once with every public endpoint tag of
    that provider ignored; that exclusion lives only for this logical request. Provider
    discovery is cached for the lifetime of this adapter. observer, when given, receives one
    'completion' event per modelspell.complete() call and one 'discovery' event per
    list_providers() call, holding only allowlisted metadata.
    """
    if type(max_429_retries) is not int or not 0 <= max_429_retries <= len(BACKOFF_SECONDS):
        raise ValueError('max_429_retries must be an integer from 0 to 3')
    sleep = sleep or _sleep
    discovered = {}

    def emit(event):
        if observer is not None:
            observer(event)

    def discover(model):
        if model not in discovered:
            try:
                rows = list(modelspell.list_providers(endpoint, model, timeout=min(timeout, 15)))
                outcome = 'ok'
            except modelspell.Cancelled:
                raise
            except modelspell.ModelSpellError as exc:
                rows, outcome = None, type(exc).__name__
            discovered[model] = rows
            emit(dict(kind='discovery', outcome=outcome, endpoints=len(rows or ())))
        return discovered[model]

    def complete(materials, settings):
        settings = dict(settings)
        model = settings.pop('model')
        modelspell.check_settings(endpoint.kind, **settings)
        info = models.get(model)
        if settings['reasoning'] not in (None, 'off') and getattr(info, 'supports_reasoning', None) is False:
            raise modelspell.UnsupportedSetting('This model reports no reasoning support')
        prompt = prompt_preview(materials)
        messages = [modelspell.Message('system', prompt['full_system']),
                    modelspell.Message('user', prompt['user'])]
        # A caller that supplies its own routing keeps it unchanged: backoff only.
        caller_routing = settings.get('provider') is not None
        route, ignore, wait, reason = 'default', None, 0, None
        exclusion_tried = False
        first_limit = None
        secondary = []
        for index in range(1, max_429_retries + 2):
            if index > 1:
                _check_cancel(cancel)
                _wait(wait, cancel, sleep)
                _check_cancel(cancel)
            kwargs = dict(settings)  # independent copy for every physical attempt
            if route == 'ignore':
                kwargs['provider'] = {'ignore': list(ignore), 'allow_fallbacks': True}
            event = dict(kind='completion', attempt=index, route=route, wait_seconds=wait)
            if reason is not None:
                event['retry_reason'] = reason
            if route == 'ignore':
                event['ignored_endpoints'] = list(ignore)
            try:
                result = modelspell.complete(endpoint, model, messages, timeout=timeout, cancel=cancel, **kwargs)
            except BaseException as exc:
                event.update(error_type=type(exc).__name__, http_status=getattr(exc, 'status', None))
                if is_rate_limit(exc):
                    facts = rate_limit_facts(exc)
                    first_limit = first_limit or facts
                    event.update(status='rate_limited', classification=facts['classification'])
                    if 'provider_name' in facts:
                        event['upstream_provider'] = facts['provider_name']
                    emit(event)
                    if index > max_429_retries:
                        break
                    reason = facts['classification']
                    if (route == 'default' and not exclusion_tried and not caller_routing
                            and 'provider_name' in facts):
                        exclusion_tried = True
                        tags = exclusion_tags(discover(model), facts['provider_name'])
                        if tags:
                            route, ignore, wait = 'ignore', tags, 0
                            continue
                    wait = BACKOFF_SECONDS[index - 1]
                    continue
                if (route == 'ignore' and isinstance(exc, modelspell.ModelSpellError)
                        and not isinstance(exc, modelspell.Cancelled)):
                    # The narrowed route itself failed: restore default routing, keep the 429.
                    event['status'] = 'exclusion_failed'
                    emit(event)
                    secondary.append(dict(outcome='exclusion_failed', error_type=event['error_type'],
                                          http_status=event['http_status']))
                    if index > max_429_retries:
                        break
                    route, ignore, reason = 'restored_default', None, 'exclusion_failed'
                    wait = BACKOFF_SECONDS[index - 1]
                    continue
                event['status'] = 'cancelled' if isinstance(exc, modelspell.Cancelled) else 'error'
                emit(event)
                raise
            event.update(status='ok', provider=_safe_text(getattr(result, 'provider', None)))
            emit(event)
            return result
        rate_limit = dict(reason='rate_limited', scope=first_limit['scope'],
                          classification=first_limit['classification'], retry_exhausted=True,
                          completion_attempts=index)
        for name in ('provider_name', 'error_code'):
            if name in first_limit:
                rate_limit[name] = first_limit[name]
        if secondary:
            rate_limit['exclusion_failed'] = True
        raise RateLimitExhausted(rate_limit, secondary)
    return complete


def rate_limit_detail(exc):
    """Sanitized UI detail for an exhausted rate limit, or None for any other error."""
    rate_limit = getattr(exc, 'rate_limit', None)
    if type(rate_limit) is not dict:
        return None
    detail = dict(reason='rate_limited', scope=rate_limit.get('scope'), retry_exhausted=True)
    if rate_limit.get('exclusion_failed'):
        detail['exclusion_failed'] = True
    return detail


def settings(body):
    return {name: body.get(name) for name in ('model', 'temperature', 'reasoning', 'max_tokens')}


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
