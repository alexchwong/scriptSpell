"""Optional standalone adapter for modelSpell's ordinary completion API."""
import json
from collections.abc import Mapping

from .workflow import AuthoringError, model_messages

_OPTIONS = frozenset({
    'reasoning', 'max_tokens', 'temperature', 'top_p', 'top_k', 'min_p',
    'repetition_penalty', 'presence_penalty', 'frequency_penalty', 'seed',
    'stop', 'provider', 'timeout',
})


def _snapshot(value, active):
    if not isinstance(value, (Mapping, list, tuple)):
        return value
    identity = id(value)
    if identity in active:
        raise AuthoringError('cyclic_dispatch_options')
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            return {key: _snapshot(item, active) for key, item in value.items()}
        return [_snapshot(item, active) for item in value]
    finally:
        active.remove(identity)


def make_dispatch(endpoint, model, *, options=None, cancel=None):
    """Bind a modelSpell target and options for use with empty per-call settings."""
    try:
        import modelspell
    except ModuleNotFoundError as exc:
        if exc.name != 'modelspell':
            raise
        raise AuthoringError('modelspell_unavailable') from None

    if not isinstance(endpoint, modelspell.Endpoint):
        raise AuthoringError('invalid_dispatch_endpoint')
    if cancel is not None and not isinstance(cancel, modelspell.CancelHandle):
        raise AuthoringError('invalid_dispatch_cancel')
    if options is not None and set(options) - _OPTIONS:
        raise AuthoringError('unsupported_dispatch_option')
    bound = {} if options is None else _snapshot(options, set())
    if hasattr(modelspell, 'check_completion'):
        modelspell.check_completion(endpoint, model, **bound)
    else:
        generation = {name: value for name, value in bound.items() if name != 'timeout'}
        modelspell.check_settings(endpoint.kind, **generation)
        if bound.get('provider') is not None:
            try:
                json.dumps(bound['provider'], allow_nan=False)
            except (TypeError, ValueError, OverflowError, RecursionError):
                raise AuthoringError('unencodable_dispatch_options') from None

    def dispatch(materials, settings):
        if settings:
            raise AuthoringError('bound_dispatch_requires_empty_settings')
        return modelspell.complete(endpoint, model, model_messages(materials), cancel=cancel, **bound)

    return dispatch
