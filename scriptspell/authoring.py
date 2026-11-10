"""Pure authoring materials; caller owns dispatch, privacy, retries and Test."""
import json
from copy import deepcopy
from .prompt_files import render
from .profile import profile
from .source import validate_source

SCHEMA = {'type': 'object', 'additionalProperties': False,
          'properties': {'source': {'type': 'string', 'maxLength': 65536},
                         'example_input': {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/value'}},
                         'expected_output': {'type': 'object', 'minProperties': 1, 'maxProperties': 100,
                                             'propertyNames': {'minLength': 1, 'maxLength': 128},
                                             'additionalProperties': {'$ref': '#/$defs/value'}},
                         'summary': {'type': 'string', 'maxLength': 4096},
                         'assumptions': {'type': 'array', 'maxItems': 20, 'items': {'type': 'string', 'maxLength': 4096}},
                         'unmet_requirements': {'type': 'array', 'maxItems': 20, 'items': {'type': 'string', 'maxLength': 4096}}},
          'required': ['source', 'summary', 'assumptions', 'unmet_requirements', 'example_input', 'expected_output'],
          '$defs': {'value': {'anyOf': [
              {'type': 'string'}, {'type': 'integer'}, {'type': 'boolean'}, {'type': 'null'},
              {'type': 'array', 'items': {'$ref': '#/$defs/value'}},
              {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/value'}}]}}}


def _check_example(value):
    # A bounded JSON subset: exact integers; decimals must be explicit strings.
    nodes = 0
    def walk(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 20000:
            raise ValueError('example_limit')
        kind = type(item)
        if kind is int:
            if item.bit_length() > 14280:
                raise ValueError('number_limit')
        elif kind in (dict, list):
            if kind is dict:
                if any(type(k) is not str for k in item):
                    raise ValueError('example_key')
                children = item.values()
            else:
                children = item
            for child in children:
                walk(child, depth + 1)
        elif kind not in (str, bool, type(None)):
            raise ValueError('example_type')
    if type(value) is not dict:
        raise ValueError('example_object')
    walk(value, 0)
    if len(json.dumps(value, ensure_ascii=True, allow_nan=False)) > 131072:
        raise ValueError('example_limit')



LANGUAGE_RULES = render('shared/monty')


def prepare_authoring(task, interface=None, examples=(), diagnostics=None):
    context = {'task': task, 'interface': interface, 'examples': examples, 'diagnostics': diagnostics}
    text = json.dumps(context, ensure_ascii=True, allow_nan=False)
    if len(text) > 131072: raise ValueError('authoring_limit')
    capabilities=profile()
    language={k:capabilities[k] for k in ('profile','builtins','imports','data_attributes','syntax','output_types','caveats')}
    return {'prompt_version': 4, 'profile': capabilities, 'response_schema': deepcopy(SCHEMA),
            'system': render('one-shot/single', monty=render('shared/monty'), language=json.dumps(language),
                             examples=render('shared/proposal_examples')), 'user': text}




def validate_proposal(proposal):
    if type(proposal) is not dict or set(proposal) != set(SCHEMA['required']):
        return {'outcome': 'invalid_proposal', 'field': '$', 'reason': 'expected_proposal_fields'}
    for key, limit in [('source', 65536), ('summary', 4096)]:
        if type(proposal[key]) is not str or len(proposal[key]) > limit:
            return {'outcome': 'invalid_proposal', 'field': key, 'reason': 'expected_bounded_string'}
    for key in ('assumptions', 'unmet_requirements'):
        if type(proposal[key]) is not list or len(proposal[key]) > 20 or any(type(x) is not str or len(x) > 4096 for x in proposal[key]):
            return {'outcome': 'invalid_proposal', 'field': key, 'reason': 'expected_bounded_string_array'}
    for key in ('example_input', 'expected_output'):
        try:
            _check_example(proposal[key])
        except (ValueError, TypeError, RecursionError, OverflowError) as exc:
            reason = str(exc) if type(exc) is ValueError and str(exc) in {
                'example_limit', 'example_key', 'example_type', 'example_object', 'number_limit'
            } else 'invalid_example_value'
            return {'outcome': 'invalid_proposal', 'field': key, 'reason': reason}
    names = proposal['expected_output']
    if not names or len(names) > 100 or any(not k or len(k) > 128 for k in names):
        return {'outcome': 'invalid_proposal', 'field': 'expected_output', 'reason': 'output_names'}
    return validate_source(proposal['source'])
