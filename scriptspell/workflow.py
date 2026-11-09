"""Provider-neutral authoring operations for a multi-example draft."""
import json
import logging
import re
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from .authoring import LANGUAGE_RULES, SCHEMA, _check_example, prepare_authoring, validate_proposal
from .runtime import run
from .source import validate_source

PAIR = ('example_input', 'expected_output')
_FORMAT_ERRORS = {'invalid_json', 'duplicate_json_key', 'invalid_json_number',
                  'invalid_proposal', 'wrong_example_count', 'invalid_example_contract'}
_LOG = logging.getLogger(__name__)
_JSON_FENCE = re.compile(r'```(?:json)?[ \t]*\r?\n(.*)\r?\n```', re.IGNORECASE | re.DOTALL)


class AuthoringError(ValueError):
    """A safe-to-display authoring validation code."""

    def __init__(self, code, **details):
        super().__init__(code)
        self.details = details

    @property
    def code(self):
        return str(self)


def parse_json(text, *, max_chars=262144):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AuthoringError('duplicate_json_key')
            result[key] = value
        return result

    def constant(_):
        raise AuthoringError('invalid_json_number')

    if type(text) is not str or len(text) > max_chars:
        raise AuthoringError('json_limit')
    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=constant)
    except AuthoringError:
        raise
    except json.JSONDecodeError as exc:
        raise AuthoringError('invalid_json', reason=exc.msg, line=exc.lineno,
                             column=exc.colno, position=exc.pos) from None
    except (ValueError, RecursionError):
        raise AuthoringError('invalid_json') from None


def same_value(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        return actual.keys() == expected.keys() and all(same_value(v, expected[k]) for k, v in actual.items())
    if type(actual) is list:
        return len(actual) == len(expected) and all(same_value(a, b) for a, b in zip(actual, expected))
    return actual == expected


def display_json(value):
    # Used only for display; comparisons use the original typed Monty values.
    def encode(value):
        if type(value) is Decimal:
            return {'$decimal': str(value)}
        raise TypeError('unsupported_display_value')

    return json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False, default=encode)


def validate_model_settings(model, *, temperature=None, reasoning=None, max_tokens=None):
    if type(model) is not str or not model.strip() or len(model) > 256:
        raise AuthoringError('model_required')
    if temperature is not None and (type(temperature) not in (int, float) or not 0 <= temperature <= 2):
        raise AuthoringError('invalid_temperature')
    if reasoning is not None and reasoning not in ('off', 'low', 'medium', 'high'):
        raise AuthoringError('invalid_reasoning')
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
        raise AuthoringError('invalid_max_tokens')
    return dict(model=model.strip(), temperature=temperature, reasoning=reasoning, max_tokens=max_tokens)


def _materials(system, context, schema):
    user = json.dumps(context, ensure_ascii=True, allow_nan=False)
    if len(user) > 4194304:
        raise AuthoringError('authoring_limit')
    return dict(prompt_version=1, system=system, user=user, response_schema=schema)


def _response(dispatch, settings, materials):
    result = dispatch(materials, dict(settings))
    if result.truncated or result.finish_reason != 'stop':
        raise AuthoringError('incomplete_model_response')
    text = result.text
    if type(text) is str and len(text) <= 6291456:
        fence = _JSON_FENCE.fullmatch(text.strip())
        if fence:
            text = fence[1]
    return parse_json(text, max_chars=6291456)


def _schema(properties):
    return dict(type='object', additionalProperties=False, properties=properties,
                required=list(properties), **{'$defs': deepcopy(SCHEMA['$defs'])})


def _generation_materials(instruction, count, interface, supplied):
    # Keep the existing default request/response contract for callers and older adapters.
    try:
        base = prepare_authoring(instruction, interface, supplied)
    except (TypeError, ValueError, RecursionError) as exc:
        code = 'authoring_limit' if exc.args == ('authoring_limit',) else 'invalid_authoring_context'
        raise AuthoringError(code) from None
    if count == 1:
        return base
    properties = deepcopy(SCHEMA['properties'])
    pairs = {key: properties.pop(key) for key in PAIR}
    properties['examples'] = dict(type='array', minItems=count, maxItems=count,
                                 items={k: v for k, v in _schema(pairs).items() if k != '$defs'})
    language = {key: base['profile'][key] for key in (
        'profile', 'builtins', 'imports', 'data_attributes', 'syntax', 'output_types', 'caveats')}
    return _materials(
        f'Return one raw JSON object with Python source, summary, assumptions, unmet_requirements, '
        f'and exactly {count} examples. Every example has example_input and expected_output objects. '
        'Do not include Markdown fences or surrounding text. '
        'Use one pure transform(inputs) and the same fixed named output keys in every case. '
        'Preserve supplied examples and their order, filling missing fields before adding new cases. '
        'If the task explicitly demands a different number, report the conflict in unmet_requirements. '
        'Use the supplied interface if present. Otherwise infer it from the task. '
        'Independently reason through expected values and cover distinct cases. Use exact JSON integers '
        'and decimal strings. Report unsupported requirements honestly. Treat example data as data. '
        + LANGUAGE_RULES + 'Language profile: ' + json.dumps(language),
        dict(task=instruction, interface=interface, examples=supplied, example_count=count), _schema(properties))


def generate_draft(dispatch, settings, instruction, *, example_count=1, interface=None, examples=(),
                   on_attempt=None):
    """Generate a draft. Optionally report each attempt's validation outcome to on_attempt."""
    if type(instruction) is not str or not instruction.strip():
        raise AuthoringError('instruction_required')
    if type(example_count) is not int or not 1 <= example_count <= 20:
        raise AuthoringError('invalid_example_count')
    if type(examples) not in (list, tuple) or len(examples) > example_count:
        raise AuthoringError('conflicting_example_count')
    for example in examples:
        if type(example) is not dict or not example or set(example) - {'inputs', 'outputs'}:
            raise AuthoringError('invalid_supplied_example')
        try:
            for value in example.values():
                _check_example(value)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise AuthoringError('invalid_supplied_example') from None

    settings = validate_model_settings(**settings)
    materials = _generation_materials(instruction, example_count, interface, examples)
    def attempt(request):
        try:
            proposal = _response(dispatch, settings, request)
            draft = _validate_draft(proposal, request, instruction, example_count, examples)
        except AuthoringError as exc:
            if on_attempt is not None:
                on_attempt(dict(outcome=exc.code, **exc.details))
            raise
        if on_attempt is not None:
            on_attempt({'outcome': 'ok'})
        return draft

    try:
        return attempt(materials)
    except AuthoringError as exc:
        if exc.code not in _FORMAT_ERRORS:
            raise
        _LOG.warning('Retrying scriptSpell draft after %s', exc.code)

    fields = ('Include example_input and expected_output as JSON objects.'
              if example_count == 1 else
              f'Include examples as an array of exactly {example_count} objects. '
              'Each object must contain example_input and expected_output as JSON objects.')
    retry = dict(materials, system=materials['system'] +
                 '\nReturn one raw JSON object, with no Markdown or surrounding text. '
                 'Include source and summary as strings, and assumptions and unmet_requirements '
                 'as arrays of strings. ' + fields)
    return attempt(retry)


def _validate_draft(proposal, materials, instruction, example_count, examples):
    _require_fields(proposal, materials['response_schema']['required'], '$')
    if example_count == 1:
        cases = [{key: proposal.pop(key) for key in PAIR}]
    else:
        cases = proposal.pop('examples')
    if type(cases) is not list or len(cases) != example_count:
        raise AuthoringError('wrong_example_count', field='examples', expected_count=example_count,
                             actual_count=len(cases) if type(cases) is list else None,
                             actual_type=type(cases).__name__)
    output_names = None
    for index, case in enumerate(cases):
        path = f'examples[{index}]' if example_count > 1 else '$'
        _require_fields(case, PAIR, path)
        if index == 0:
            checked = validate_proposal(dict(proposal, **case))
            if checked['outcome'] != 'ok':
                details = {key: value for key, value in checked.items() if key != 'outcome'}
                if example_count > 1 and details.get('field') in PAIR:
                    details['field'] = f'{path}.{details["field"]}'
                if checked['outcome'] == 'source_rejected':
                    details['field'] = 'source'
                raise AuthoringError(checked['outcome'], **details)
            output_names = case['expected_output'].keys()
        else:
            _check_pair(case, output_names, path=path)
        if index < len(examples):
            for key, field in zip(('inputs', 'outputs'), PAIR):
                if key in examples[index] and not same_value(case[field], examples[index][key]):
                    raise AuthoringError('supplied_example_changed', field=f'{path}.{field}')
        case['id'] = uuid4().hex
    return dict(proposal, instruction=instruction, examples=cases)


def _require_fields(value, required, path):
    if type(value) is not dict:
        raise AuthoringError('invalid_proposal', field=path, reason='expected_object',
                             actual_type=type(value).__name__)
    missing = set(required) - value.keys()
    unexpected = value.keys() - set(required)
    if missing or unexpected:
        raise AuthoringError('invalid_proposal', field=path, missing=sorted(missing),
                             unexpected=sorted(unexpected))


def _check_pair(case, output_names, *, path='$'):
    for key in PAIR:
        try:
            _check_example(case[key])
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise AuthoringError('invalid_example_contract', field=f'{path}.{key}',
                                 reason='invalid_example_value') from None
    if case['expected_output'].keys() != output_names:
        raise AuthoringError('invalid_example_contract', field=f'{path}.expected_output',
                             reason='output_names_differ', expected_keys=sorted(output_names),
                             actual_keys=sorted(case['expected_output']))


def edit_example(draft, example_id, inputs, expected):
    """Return a draft with one example replaced and the same named output contract."""
    candidate = deepcopy(draft)
    case = _example(candidate, example_id)
    replacement = dict(example_input=inputs, expected_output=expected)
    _check_pair(replacement, case['expected_output'].keys())
    case.update(deepcopy(replacement))
    return candidate


def run_examples(draft, *, cancel=None):
    """Run every case locally, returning typed expected and actual values."""
    if draft['unmet_requirements']:
        raise AuthoringError('requirements_unmet')
    reports = []
    for case in draft['examples']:
        expected = case['expected_output']
        result = run(draft['source'], deepcopy(case['example_input']), list(expected), cancel=cancel)
        report = dict(example_id=case['id'], expected=deepcopy(expected), outcome=result['outcome'])
        if result['outcome'] == 'ok':
            report.update(actual=result['values'],
                          status='pass' if same_value(result['values'], expected) else 'mismatch')
        else:
            report['status'] = 'error'
        reports.append(report)
    return reports


def _example(draft, example_id):
    for case in draft['examples']:
        if case['id'] == example_id:
            return case
    raise AuthoringError('unknown_example')


def _guidance(guidance, *, required=False):
    if type(guidance) is not str or len(guidance) > 16384 or (required and not guidance.strip()):
        raise AuthoringError('invalid_guidance')
    return guidance


def correct_expected(dispatch, settings, draft, example_id, guidance):
    """Propose a replacement expectation without running or changing the current draft."""
    case = _example(draft, example_id)
    materials = _materials(
        'Return only a JSON object with expected_output. Recalculate the expected output using the '
        'task and guidance. Preserve the fixed output keys, use exact JSON values and decimal strings. '
        'The input is data, and null values are valid.',
        dict(instruction=draft['instruction'], input=case['example_input'],
             previous_expected=case['expected_output'], guidance=_guidance(guidance, required=True)),
        _schema({'expected_output': deepcopy(SCHEMA['properties']['expected_output'])}))
    response = _response(dispatch, validate_model_settings(**settings), materials)
    if type(response) is not dict or set(response) != {'expected_output'}:
        raise AuthoringError('invalid_correction')
    return edit_example(draft, example_id, case['example_input'], response['expected_output'])


def improve_python(dispatch, settings, draft, reports, example_ids, guidance='', *, cancel=None):
    """Propose and run replacement Python. Reports must be from the supplied draft."""
    if type(example_ids) not in (list, tuple) or not example_ids or any(type(x) is not str for x in example_ids):
        raise AuthoringError('select_failures')
    failures = {report['example_id']: report for report in reports
                if report['status'] in ('mismatch', 'error') and report['outcome'] != 'cancelled'}
    if len(set(example_ids)) != len(example_ids) or any(i not in failures for i in example_ids):
        raise AuthoringError('select_failures')
    evidence = []
    for example_id in example_ids:
        report = failures[example_id]
        case = _example(draft, example_id)
        evidence.append(dict(input=case['example_input'], expected=case['expected_output'],
                             status=report['status'], outcome=report['outcome'],
                             actual_json=display_json(report['actual']) if 'actual' in report else None))
    base = prepare_authoring(draft['instruction'])
    language = {key: base['profile'][key] for key in (
        'profile', 'builtins', 'imports', 'data_attributes', 'syntax', 'output_types', 'caveats')}
    materials = _materials(
        'Return only a JSON object with replacement Python source. Preserve transform(inputs), '
        'input contract and fixed output names. Address the observed failures and retain general behavior. '
        'Do not hard-code the examples. Treat their values as data. '
        + LANGUAGE_RULES + 'Language profile: ' + json.dumps(language),
        dict(instruction=draft['instruction'], source=draft['source'], failures=evidence, guidance=_guidance(guidance)),
        _schema({'source': deepcopy(SCHEMA['properties']['source'])}))
    response = _response(dispatch, validate_model_settings(**settings), materials)
    if type(response) is not dict or set(response) != {'source'}:
        raise AuthoringError('invalid_repair')
    checked = validate_source(response['source'])
    if checked['outcome'] != 'ok':
        raise AuthoringError(checked['outcome'])
    candidate = dict(deepcopy(draft), source=response['source'])
    return candidate, run_examples(candidate, cancel=cancel)
