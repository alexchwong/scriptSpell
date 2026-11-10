"""Two-call and one-shot YAML authoring without a model-client dependency."""
import json
from uuid import uuid4

from .profile import profile
from .prompt_files import render, task_text
from .source import validate_source
from .staged import _unwrap
from .workflow import AuthoringError, validate_model_settings
from .yaml_contract import YamlContractError, dump_examples, validate_examples, validate_interface


class YamlAuthoring:
    """Accept validated examples and Python, or accept them together in one reply."""

    def __init__(self, instruction, count=1, *, interface=None, one_shot=False, records=None, guidance=None):
        if type(instruction) is not str or not instruction.strip():
            raise AuthoringError('instruction_required')
        if len(instruction) > 131072 or type(count) is not int or not 1 <= count <= 20:
            raise AuthoringError('invalid_authoring_context')
        if interface is not None:
            try:
                validate_interface(interface)
            except ValueError:
                raise AuthoringError('invalid_interface') from None
        self.instruction, self.count, self.interface = instruction, count, interface
        self.one_shot = one_shot
        self.records, self.guidance = records, guidance
        self.document = self.pairs = self.source = None

    def materials(self, stage):
        if stage == 'python':
            contract = None
        else:
            contract = render('shared/yaml-contract')
            if self.interface is None:
                contract += '\n\n' + render('shared/yaml-example')
        if stage == 'examples' and not self.one_shot:
            system = render('stages/yaml-examples', contract=contract)
        elif stage == 'one-shot' and self.one_shot:
            system = render('stages/yaml-one-shot', contract=contract, **_language())
        elif stage == 'python' and not self.one_shot and self.document is not None:
            visible = dict(interface=self.document['interface'], examples=self.document['examples'][:1])
            system = render('stages/yaml-python', examples_yaml=dump_examples(visible), **_language())
        else:
            raise AuthoringError('stage_not_ready')
        user = task_text(self.instruction, example_count=self.count)
        if self.interface is not None and stage != 'python':
            interface = {side: [{name: kind} for name, kind in fields.items()]
                         for side, fields in self.interface.items()}
            example = {side: [{name: f'<{kind} value>'} for name, kind in fields.items()]
                       for side, fields in self.interface.items()}
            shape = dump_examples(dict(interface=interface, examples=[example])).rstrip()
            user += '\n\n' + render('stages/yaml-fixed-interface', shape=shape, count=self.count)
        if self.records:
            user += '\n\n' + _record_guidance(self.records)
        if self.guidance:
            user += '\n\n' + self.guidance
        return dict(system=system, user=user)

    def accept(self, stage, text):
        self.materials(stage)
        if stage == 'python':
            self.source = _source(_unwrap(text, 'python'))
            return
        document, pairs = validate_examples(text, self.count, one_shot=self.one_shot,
                                            interface=self.interface, records=self.records)
        source = _source(document.pop('source')) if self.one_shot else None
        self.document, self.pairs, self.source = document, pairs, source

    def generate(self, stage, dispatch, settings, *, on_reject=None):
        """Perform one stage and return any rejected attempt's diagnostics."""
        materials = self.materials(stage)
        settings = validate_model_settings(**settings)
        text = _reply(dispatch, materials, settings)
        try:
            self.accept(stage, text)
        except YamlContractError as first:
            if not first.retryable:
                raise
            initial = first.details['issues']
            if on_reject is not None:
                on_reject(list(initial))
            retry = dict(materials, system=materials['system'] + '\n\n' + render('stages/yaml-retry'),
                         user=materials['user'] + '\n\nIssues to fix\n\n' +
                         '\n'.join(f'- {issue}' for issue in initial) +
                         '\n\nExact rejected reply follows\n\n' + text)
            try:
                self.accept(stage, _reply(dispatch, retry, settings))
            except AuthoringError as second:
                second.details = dict(getattr(second, 'details', {}), first_attempt=initial)
                raise
            return initial
        return []

    def examples_yaml(self):
        if self.document is None:
            raise AuthoringError('stage_not_ready')
        return dump_examples(self.document)

    def draft(self):
        if self.source is None:
            raise AuthoringError('stage_not_ready')
        return dict(source=self.source, instruction=self.instruction, summary='', assumptions=[],
                    unmet_requirements=[], yaml_examples=self.examples_yaml(), examples=[
                        dict(id=uuid4().hex, example_input=pair['inputs'], expected_output=pair['outputs'],
                             visible=self.one_shot or index == 0) for index, pair in enumerate(self.pairs)])


def _record_guidance(records):
    lines = ['Nested fields (each [] refers to every item in that list)']
    for path, rule in records.items():
        if 'length' in rule:
            lines.append(f"- {path} must contain exactly {rule['length']} items.")
            continue
        details = [f'{name} ({kind})' for name, kind in rule['required'].items()]
        sentence = 'requires ' + ', '.join(details) if details else 'has no required fields'
        if rule.get('optional'):
            fields = ', '.join(f'{name} ({kind})' for name, kind in rule['optional'].items())
            sentence += f'. Optional fields are {fields}'
        if not rule.get('allow_extra'):
            sentence += '. Use only these fields'
        if rule.get('nullable'):
            sentence += '. A null item is also allowed'
        lines.append(f'- {path} {sentence}.')
    return '\n'.join(lines)


def _language():
    capabilities = profile()
    keys = ('profile', 'builtins', 'imports', 'data_attributes', 'syntax', 'output_types', 'caveats')
    return dict(monty=render('shared/monty'), language=json.dumps({key: capabilities[key] for key in keys}))


def _source(text):
    checked = validate_source(text)
    if checked['outcome'] != 'ok':
        error = AuthoringError(checked['outcome'])
        error.details = {'issues': checked.get('issues', [])}
        raise error
    return text


def _reply(dispatch, materials, settings):
    reply = dispatch(materials, dict(settings))
    if reply.truncated or reply.finish_reason != 'stop':
        raise AuthoringError('incomplete_model_response')
    return reply.text
