"""Consumer adapter: modelSpell dispatch and scriptSpell's public authoring/runtime APIs."""
import json
from decimal import Decimal

import modelspell
from scriptspell import prepare_authoring, validate_proposal, run


class UIError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UIError('duplicate_json_key')
        result[key] = value
    return result


def _constant(value):
    raise UIError('invalid_json_number')


def parse_json(text):
    if type(text) is not str or len(text.encode('utf-8')) > 262144:
        raise UIError('json_limit')
    try:
        return json.loads(text, object_pairs_hook=_unique, parse_constant=_constant)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, UIError):
            raise
        raise UIError('invalid_json') from None


def parse_example(text):
    value = parse_json(text)
    # Preserve exact integers and refuse unsupported decimal literals before execution.
    count = 0
    def check(item, depth=0):
        nonlocal count
        count += 1
        if depth > 32 or count > 20000:
            raise UIError('json_limit')
        if type(item) is int:
            if item.bit_length() > 14280:
                raise UIError('json_number_limit')
        elif type(item) in (dict, list):
            for child in (item.values() if type(item) is dict else item):
                check(child, depth + 1)
        elif type(item) not in (str, bool, type(None)):
            raise UIError('use_decimal_strings')
    if type(value) is not dict:
        raise UIError('example_must_be_object')
    check(value)
    return value


def pretty(value):
    # Decimal results remain explicitly typed, never silently coerced into strings or floats.
    return json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False,
                      default=lambda x: {'$decimal': str(x)} if type(x) is Decimal else _constant(x))


def same_value(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        return actual.keys() == expected.keys() and all(same_value(v, expected[k]) for k, v in actual.items())
    if type(actual) is list:
        return len(actual) == len(expected) and all(same_value(a, b) for a, b in zip(actual, expected))
    return actual == expected


def generate(endpoint, model, instruction, cancel):
    if type(instruction) is not str or not instruction.strip():
        raise UIError('instruction_required')
    if type(model) is not str or not model.strip():
        raise UIError('model_required')
    materials = prepare_authoring(instruction)
    response = modelspell.complete(
        endpoint, model,
        [modelspell.Message('system', materials['system'] + '\nJSON response schema: ' +
                            json.dumps(materials['response_schema'])),
         modelspell.Message('user', materials['user'])],
        max_tokens=4096, temperature=0, timeout=120, cancel=cancel)
    if response.truncated or response.finish_reason != 'stop':
        raise UIError('incomplete_model_response')
    proposal = parse_json(response.text)
    checked = validate_proposal(proposal)
    if checked['outcome'] != 'ok':
        raise UIError(checked['outcome'])
    return proposal


def execute(proposal, input_text, expected_text, cancel):
    if not proposal:
        raise UIError('generate_first')
    if proposal['unmet_requirements']:
        raise UIError('requirements_unmet')
    inputs, expected = parse_example(input_text), parse_example(expected_text)
    result = run(proposal['source'], inputs, list(proposal['expected_output']), cancel=cancel)
    if result['outcome'] != 'ok':
        return {'status': 'error', 'outcome': result['outcome'], 'actual_json': ''}
    match = same_value(result['values'], expected)
    return {'status': 'match' if match else 'mismatch', 'outcome': 'ok',
            'actual_json': pretty(result['values'])}
