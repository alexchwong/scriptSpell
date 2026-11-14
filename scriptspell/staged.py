"""Shared staged prompts and reply validation for the UI and CLI."""
import json
import re
from uuid import uuid4

from .authoring import SCHEMA, _check_example
from .profile import profile
from .prompt_files import render, task_text
from .source import validate_source
from .workflow import AuthoringError, _dispatch_settings, _dispatch_text, parse_json

_TYPES = {'array': list, 'boolean': bool, 'integer': int, 'null': type(None),
          'object': dict, 'string': str}
_MAX_REPLY = 6291456


class StageError(AuthoringError):
    def __init__(self, code, **details):
        super().__init__(code)
        self.details = details


def _unwrap(text, language):
    if type(text) is not str or len(text) > _MAX_REPLY:
        raise StageError('response_limit')
    match = re.fullmatch(rf'```(?:{language})?[ \t]*\r?\n(.*)\r?\n```', text.strip(), re.DOTALL | re.IGNORECASE)
    return match[1] if match else text


def _fields(value, names, path):
    if type(value) is not dict or value.keys() != set(names):
        actual = set(value) if type(value) is dict else set()
        raise StageError('invalid_fields', field=path, actual_type=type(value).__name__,
                             missing=sorted(set(names) - actual), unexpected=sorted(actual - set(names)))


def _interface(value):
    _fields(value, ('inputs', 'outputs'), 'interface')
    for side, fields in value.items():
        if type(fields) is not dict or len(fields) > 100 or (side == 'outputs' and not fields):
            raise StageError('invalid_interface', field=f'interface.{side}')
        for name, kind in fields.items():
            if not name or len(name) > 128 or type(kind) is not str or kind not in _TYPES:
                raise StageError('invalid_interface', field=f'interface.{side}.{name}')
    return value


def _example(value, fields, path):
    _fields(value, fields, path)
    try:
        _check_example(value)
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise StageError('invalid_example', field=path) from exc
    for key, kind in fields.items():
        if type(value[key]) is not _TYPES[kind]:
            raise StageError('invalid_example_type', field=f'{path}.{key}',
                                 expected=kind, actual=type(value[key]).__name__)


def _object(properties):
    return dict(type='object', required=list(properties), properties=properties, additionalProperties=False)


def _schema(properties):
    return dict(_object(properties), **{'$defs': SCHEMA['$defs']})


class StagedAuthoring:
    def __init__(self, instruction, count, interface=None):
        if type(instruction) is not str or not instruction.strip():
            raise StageError('instruction_required')
        if len(instruction) > 131072 or type(count) is not int or not 1 <= count <= 20:
            raise StageError('invalid_authoring_context')
        self.instruction = instruction
        self.count = count
        self.interface = _interface(interface) if interface is not None else None
        self.contract = self.inputs = self.outputs = self.source = None

    def _input_properties(self):
        properties = {'examples': dict(type='array', minItems=self.count, maxItems=self.count,
                                       items=SCHEMA['properties']['example_input'])}
        if self.interface is None:
            fields = dict(type='object', additionalProperties={'enum': list(_TYPES)})
            properties['interface'] = _object({'inputs': fields, 'outputs': fields})
        return properties

    def materials(self, stage):
        if stage == 'inputs':
            return dict(system=render('stages/inputs', json_rules=render('shared/json')),
                        user=task_text(self.instruction, example_count=self.count, interface=self.interface),
                        response_schema=_schema(self._input_properties()))
        if stage == 'expectations' and self.inputs is not None:
            outputs = _object(dict.fromkeys(self.inputs, SCHEMA['properties']['expected_output']))
            return dict(system=render('stages/expectations', json_rules=render('shared/json')),
                        user=task_text(self.instruction, interface=self.contract, inputs=self.inputs),
                        response_schema=_schema({'outputs': outputs}))
        if stage == 'python' and self.outputs is not None:
            capabilities = profile()
            language = {key: capabilities[key] for key in
                        ('profile', 'builtins', 'imports', 'data_attributes', 'syntax', 'output_types', 'caveats')}
            return dict(system=render('stages/python', monty=render('shared/monty'), language=json.dumps(language)),
                        user=task_text(self.instruction, interface=self.contract,
                                       example_input=self.inputs['1'], expected_output=self.outputs['1']))
        raise StageError('stage_not_ready')

    def generate(self, stage, dispatch, settings):
        """Dispatch and accept one legacy JSON authoring stage."""
        materials = self.materials(stage)
        settings = _dispatch_settings(settings)
        text = _dispatch_text(dispatch, settings, materials, f'json_{stage}')
        self.accept(stage, text)

    def accept(self, stage, text):
        if stage == 'inputs':
            value = parse_json(_unwrap(text, 'json'), max_chars=_MAX_REPLY)
            _fields(value, self._input_properties(), '$')
            contract = self.interface if self.interface is not None else _interface(value['interface'])
            examples = value['examples']
            if type(examples) is not list or len(examples) != self.count:
                raise StageError('wrong_example_count', field='examples', expected_count=self.count,
                                 actual_count=len(examples) if type(examples) is list else None)
            for index, example in enumerate(examples):
                _example(example, contract['inputs'], f'examples[{index}]')
            self.contract = contract
            self.inputs = {str(index): example for index, example in enumerate(examples, 1)}
            self.outputs = self.source = None
        elif stage == 'expectations' and self.inputs is not None:
            value = parse_json(_unwrap(text, 'json'), max_chars=_MAX_REPLY)
            _fields(value, ('outputs',), '$')
            outputs = value['outputs']
            _fields(outputs, self.inputs, 'outputs')
            for case_id, output in outputs.items():
                _example(output, self.contract['outputs'], f'outputs.{case_id}')
            self.outputs = outputs
            self.source = None
        elif stage == 'python' and self.outputs is not None:
            source = _unwrap(text, 'python')
            checked = validate_source(source)
            if checked['outcome'] != 'ok':
                raise StageError(checked['outcome'], issues=checked.get('issues', []))
            self.source = source
        else:
            raise StageError('stage_not_ready')

    def draft(self):
        if self.source is None:
            raise StageError('stage_not_ready')
        return dict(source=self.source, instruction=self.instruction, summary='', assumptions=[],
                    unmet_requirements=[], examples=[
                        dict(id=uuid4().hex, example_input=value, expected_output=self.outputs[case_id],
                             visible=case_id == '1') for case_id, value in self.inputs.items()])
