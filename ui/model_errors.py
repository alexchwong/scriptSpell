"""Sanitized model setup and provider diagnostics for development entry points."""
import re

import modelspell

from scriptspell import AuthoringError
from scriptspell.workflow import parse_json


def redact(value, key):
    if not key:
        return value
    if isinstance(value, str):
        return value.replace(key, '[REDACTED]')
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if isinstance(value, dict):
        return {redact(name, key): redact(item, key) for name, item in value.items()}
    return value


def provider_error(exc):
    error = {'type': type(exc).__name__, 'http_status': getattr(exc, 'status', None)}
    if isinstance(exc, modelspell.Cancelled):
        error['sent'] = exc.sent
    body = getattr(exc, 'body', None)
    if not isinstance(body, str):
        return error
    try:
        data = parse_json(body)
    except AuthoringError:
        return error
    if not isinstance(data, dict) or not isinstance(data.get('error'), dict):
        return error
    detail = data['error']
    metadata = detail.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}
    for name, value in (('code', detail.get('code')), ('provider_name', metadata.get('provider_name')),
                        ('limit_source', metadata.get('limit_source'))):
        if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9 _.()/+-]{0,99}', value):
            error[name] = value
        elif name == 'code' and type(value) is int:
            error[name] = value
    if type(metadata.get('is_byok')) is bool:
        error['is_byok'] = metadata['is_byok']
    return error


def setup_error(exc, key):
    """Return a stable error code and a displayable offline preflight reason."""
    if isinstance(exc, AuthoringError):
        return exc.code, None
    return type(exc).__name__, redact(str(exc), key)
