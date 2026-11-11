"""Shared adapter HTTP 429 recovery with injected modelSpell failures; no network."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / 'ui/service.py').exists(), reason='repository-only adapter')

MATERIALS = dict(system='System text', user='User text')
SETTINGS = dict(model='author/model', temperature=0, reasoning=None, max_tokens=64)
SECRET_BODY_MARKERS = ('user_id', 'acct-123', 'raw upstream text')


@pytest.fixture
def service(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from ui import service
    return service


def limit(provider=None, extra=True):
    import modelspell
    error = {'message': 'raw upstream text', 'code': 429}
    if provider is not None:
        error['metadata'] = {'provider_name': provider, 'raw': 'raw upstream text'}
    body = {'error': error}
    if extra:
        body['user_id'] = 'acct-123'
    return modelspell.BackendError('provider returned HTTP 429', status=429, body=json.dumps(body))


def ok(provider='Beta'):
    return SimpleNamespace(text='reply', finish_reason='stop', truncated=False, provider=provider)


def row(name, slug):
    return SimpleNamespace(name=name, slug=slug)


class Harness:
    def __init__(self, service, monkeypatch, outcomes, rows=None, retries=3):
        import modelspell
        self.outcomes = list(outcomes)
        self.calls, self.events, self.sleeps, self.discovery_calls = [], [], [], 0
        self.rows = rows
        self.cancel = modelspell.CancelHandle()

        def complete(endpoint, model, messages, **kwargs):
            self.calls.append(dict(model=model, messages=[(m.role, m.content) for m in messages], kwargs=kwargs))
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        def list_providers(endpoint, model, **kwargs):
            self.discovery_calls += 1
            if isinstance(self.rows, BaseException):
                raise self.rows
            return self.rows

        monkeypatch.setattr(modelspell, 'complete', complete)
        monkeypatch.setattr(modelspell, 'list_providers', list_providers)
        self.service = service
        self.retries = retries
        self.send = self.adapter()

    def adapter(self):
        return self.service.dispatch(SimpleNamespace(kind='openrouter'), self.cancel, {},
                                     max_429_retries=self.retries, observer=self.events.append,
                                     sleep=self.sleeps.append)

    def completions(self):
        return [event for event in self.events if event['kind'] == 'completion']


def test_provider_429_ignores_every_endpoint_tag_and_keeps_the_request(service, monkeypatch):
    rows = [row('Alpha', 'alpha/fp8'), row('Alpha', 'alpha/bf16'), row('Beta', 'beta')]
    h = Harness(service, monkeypatch, [limit('Alpha'), ok()], rows)
    settings = dict(SETTINGS)
    assert h.send(MATERIALS, settings).text == 'reply'
    assert settings == SETTINGS  # caller's settings are not mutated
    first, second = h.calls
    assert 'provider' not in first['kwargs']
    assert second['kwargs']['provider'] == {'ignore': ['alpha/fp8', 'alpha/bf16'], 'allow_fallbacks': True}
    assert second['model'] == first['model'] == 'author/model'
    assert second['messages'] == first['messages']
    assert {k: v for k, v in second['kwargs'].items() if k != 'provider'} == first['kwargs']
    assert h.sleeps == []  # the alternative route is tried immediately but consumes a retry
    events = h.completions()
    assert [(e['route'], e['status']) for e in events] == [('default', 'rate_limited'), ('ignore', 'ok')]
    assert events[0]['upstream_provider'] == 'Alpha' and events[1]['provider'] == 'Beta'
    assert events[1]['retry_reason'] == 'rate_limited_provider'
    assert h.discovery_calls == 1 and len(h.events) == 3


@pytest.mark.parametrize('rows', [
    [row('Alpha', 'alpha/fp8'), row('Alpha', None), row('Beta', 'beta')],  # one matched row lacks a tag
    [row('Gamma', 'gamma'), row('Beta', 'beta')],  # provider not listed
    [row('Alpha', 'alpha/fp8'), row('Alpha', 'alpha/bf16')],  # no endpoint would remain
    [],
])
def test_partial_or_total_exclusion_falls_back_to_backoff(service, monkeypatch, rows):
    h = Harness(service, monkeypatch, [limit('Alpha'), ok()], rows)
    h.send(MATERIALS, dict(SETTINGS))
    assert all('provider' not in call['kwargs'] for call in h.calls)
    assert sum(h.sleeps) == pytest.approx(1)
    assert [e['route'] for e in h.completions()] == ['default', 'default']


def test_discovery_failure_and_unattributed_limits_use_backoff(service, monkeypatch):
    import modelspell
    h = Harness(service, monkeypatch, [limit('Alpha'), ok()], modelspell.BackendError('down', status=500, body='x'))
    h.send(MATERIALS, dict(SETTINGS))
    assert 'provider' not in h.calls[1]['kwargs'] and h.discovery_calls == 1
    assert [e for e in h.events if e['kind'] == 'discovery'][0]['outcome'] == 'BackendError'
    h = Harness(service, monkeypatch, [limit(None), limit(None), ok()], [row('Beta', 'beta')])
    h.send(MATERIALS, dict(SETTINGS))
    assert h.discovery_calls == 0
    assert [e['classification'] for e in h.completions()[:2]] == ['rate_limited_account_or_unknown'] * 2
    assert sum(h.sleeps) == pytest.approx(3)


def test_narrowed_route_error_is_exclusion_failed_and_never_masks_the_429(service, monkeypatch):
    import modelspell
    rows = [row('Alpha', 'alpha'), row('Beta', 'beta')]
    no_route = modelspell.BackendError('no endpoints', status=404, body='{"user_id":"acct-123"}')
    h = Harness(service, monkeypatch, [limit('Alpha'), no_route, limit('Alpha'), limit('Alpha')], rows)
    with pytest.raises(service.RateLimitExhausted) as raised:
        h.send(MATERIALS, dict(SETTINGS))
    exc = raised.value
    assert exc.status == 429 and exc.body == ''
    assert exc.rate_limit['scope'] == 'provider' and exc.rate_limit['provider_name'] == 'Alpha'
    assert exc.rate_limit['exclusion_failed'] is True and exc.rate_limit['retry_exhausted'] is True
    assert exc.secondary == [dict(outcome='exclusion_failed', error_type='BackendError', http_status=404)]
    assert [(e['route'], e['status']) for e in h.completions()] == [
        ('default', 'rate_limited'), ('ignore', 'exclusion_failed'),
        ('restored_default', 'rate_limited'), ('restored_default', 'rate_limited')]
    assert [call['kwargs'].get('provider') for call in h.calls][2:] == [None, None]
    assert len(h.calls) == 4 and h.discovery_calls == 1
    assert not any(marker in json.dumps(exc.rate_limit) + json.dumps(h.events) for marker in SECRET_BODY_MARKERS)


def test_restored_route_surfaces_a_genuine_non_429_error(service, monkeypatch):
    import modelspell
    rows = [row('Alpha', 'alpha'), row('Beta', 'beta')]
    genuine = modelspell.BackendError('server error', status=500, body='')
    h = Harness(service, monkeypatch, [limit('Alpha'), modelspell.ConnectError('no route'), genuine], rows)
    with pytest.raises(modelspell.BackendError) as raised:
        h.send(MATERIALS, dict(SETTINGS))
    assert raised.value is genuine and not isinstance(raised.value, service.RateLimitExhausted)
    assert len(h.calls) == 3


@pytest.mark.parametrize('error', ['backend', 'auth', 'timeout'])
def test_non_429_errors_on_the_default_route_are_not_retried(service, monkeypatch, error):
    import modelspell
    exc = dict(backend=modelspell.BackendError('bad', status=500, body=''),
               auth=modelspell.AuthError('denied', status=401),
               timeout=modelspell.RequestTimeout('slow'))[error]
    h = Harness(service, monkeypatch, [exc, ok()], [row('Beta', 'beta')])
    with pytest.raises(type(exc)) as raised:
        h.send(MATERIALS, dict(SETTINGS))
    assert raised.value is exc and len(h.calls) == 1 and h.discovery_calls == 0
    assert h.completions()[0]['status'] == 'error'


@pytest.mark.parametrize('retries', [0, 1, 3])
def test_budget_is_bounded_per_logical_request(service, monkeypatch, retries):
    h = Harness(service, monkeypatch, [limit(None)] * 5, retries=retries)
    with pytest.raises(service.RateLimitExhausted) as raised:
        h.send(MATERIALS, dict(SETTINGS))
    assert len(h.calls) == len(h.completions()) == retries + 1
    assert raised.value.rate_limit['completion_attempts'] == retries + 1
    assert raised.value.rate_limit['scope'] == 'account_or_unknown'
    assert sum(h.sleeps) == pytest.approx(sum((1, 2, 4)[:retries]))
    assert all(step <= 0.1 + 1e-9 for step in h.sleeps)


def test_ignore_set_is_per_request_and_discovery_is_per_adapter(service, monkeypatch):
    rows = [row('Alpha', 'alpha'), row('Beta', 'beta')]
    h = Harness(service, monkeypatch, [limit('Alpha'), ok(), ok(), limit('Alpha'), ok()], rows)
    h.send(MATERIALS, dict(SETTINGS))
    h.send(MATERIALS, dict(SETTINGS))
    h.send(MATERIALS, dict(SETTINGS))
    assert [call['kwargs'].get('provider') is not None for call in h.calls] == [False, True, False, False, True]
    assert h.discovery_calls == 1  # cached within one adapter (one CLI run)
    h.outcomes = [limit('Alpha'), ok()]
    h.adapter()(MATERIALS, dict(SETTINGS))  # a fresh adapter (one UI operation) rediscovers
    assert h.discovery_calls == 2


def test_caller_routing_is_never_overridden(service, monkeypatch):
    h = Harness(service, monkeypatch, [limit('Alpha'), ok()], [row('Alpha', 'alpha'), row('Beta', 'beta')])
    h.send(MATERIALS, dict(SETTINGS, provider={'order': ['alpha']}))
    assert [call['kwargs']['provider'] for call in h.calls] == [{'order': ['alpha']}] * 2
    assert h.discovery_calls == 0


def test_cancellation_interrupts_backoff_before_the_next_attempt(service, monkeypatch):
    import modelspell
    h = Harness(service, monkeypatch, [limit(None), ok()])
    h.send = service.dispatch(SimpleNamespace(kind='openrouter'), h.cancel, {}, observer=h.events.append,
                              sleep=lambda seconds: (h.sleeps.append(seconds), h.cancel.cancel()))
    with pytest.raises(modelspell.Cancelled):
        h.send(MATERIALS, dict(SETTINGS))
    assert len(h.calls) == 1 and h.sleeps == [0.1]


def test_ordinary_success_makes_exactly_one_call(service, monkeypatch):
    h = Harness(service, monkeypatch, [ok()])
    assert h.send(MATERIALS, dict(SETTINGS)).text == 'reply'
    assert len(h.calls) == 1 and h.sleeps == [] and h.discovery_calls == 0
    assert 'provider' not in h.calls[0]['kwargs']


def test_rate_limit_facts_are_allowlisted(service):
    import modelspell
    facts = service.rate_limit_facts(limit('Alpha'))
    assert facts == dict(provider_name='Alpha', error_code=429, scope='provider',
                         classification='rate_limited_provider')
    hostile = modelspell.BackendError('x', status=429, body=json.dumps(
        {'error': {'code': 'x' * 99, 'metadata': {'provider_name': '<script>' + 'a' * 200}}}))
    assert service.rate_limit_facts(hostile) == dict(scope='account_or_unknown',
                                                     classification='rate_limited_account_or_unknown')
    oversized = modelspell.BackendError('x', status=429, body=' ' * 20000 + json.dumps(
        {'error': {'metadata': {'provider_name': 'Alpha'}}}))
    assert 'provider_name' not in service.rate_limit_facts(oversized)
    assert service.rate_limit_facts(modelspell.BackendError('x', status=429, body='not json'))['scope'] == \
        'account_or_unknown'
