"""Bounded authoring YAML and its typed example contract."""
import ast
import re
from decimal import Decimal, InvalidOperation
from math import isfinite

import yaml

from .codec import pack
from .profile import Limits
from .workflow import AuthoringError

MAX_YAML_CHARS = 131072
MAX_DEPTH = 32
MAX_NODES = 20000
_INVALID = object()
_INT = re.compile(r'-?(?:0|[1-9][0-9]*)')
_NUMBER = re.compile(r'-?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_DECIMAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_TYPES = {'str': str, 'int': int, 'bool': bool, 'float': float, 'Decimal': Decimal,
          'None': type(None), 'list': list, 'dict': dict}


class YamlContractError(AuthoringError):
    def __init__(self, issues, *, retryable=True):
        super().__init__('invalid_yaml')
        self.details = {'issues': list(issues)}
        self.retryable = retryable


def _yaml_location(mark):
    return f'Line {mark.line + 1}, column {mark.column + 1}'


def _plain_scalar(node, path, issues):
    value = node.value
    try:
        value.encode('utf-8')
    except UnicodeError:
        issues.append(f'{path}: use valid Unicode text.')
        return _INVALID
    if node.style is not None:
        return value
    if value in ('', 'null'):
        return None
    if value in ('true', 'false'):
        return value == 'true'
    if _INT.fullmatch(value):
        if len(value.lstrip('-')) <= 4300:
            return int(value)
    elif _NUMBER.fullmatch(value):
        number = float(value)
        if isfinite(number):
            return number
    elif value.lower() not in ('.nan', '.inf', '+.inf', '-.inf'):
        return value
    issues.append(f'{path}: use a finite number within the supported limits.')
    return _INVALID


def _decode(node, path, issues):
    if isinstance(node, yaml.ScalarNode):
        return _plain_scalar(node, path, issues)
    if isinstance(node, yaml.SequenceNode):
        return [_decode(item, f'{path}[{index}]', issues) for index, item in enumerate(node.value, 1)]
    values = {}
    for raw_key, raw_value in node.value:
        key = _decode(raw_key, f'{path} key', issues)
        if type(key) is not str:
            issues.append(f'{path}: mapping keys must be strings. Quote non-string keys.')
            continue
        if raw_key.style is None and key == '<<':
            issues.append(f'{path}: YAML merge keys are unavailable. Write the fields explicitly.')
            continue
        if key in values:
            issues.append(f'{path}: key {key!r} is repeated. Keep exactly one entry.')
            continue
        values[key] = _decode(raw_value, f'{path}.{key}', issues)
    return values


def read_yaml(text):
    """Parse only inert YAML nodes, with bounded scanning before composition."""
    if type(text) is not str or len(text) > MAX_YAML_CHARS:
        raise YamlContractError(['Return a YAML document of at most 131072 characters.'], retryable=False)
    issues = []
    depth = nodes = documents = 0
    try:
        for event in yaml.parse(text, Loader=yaml.BaseLoader):
            if isinstance(event, yaml.DocumentStartEvent):
                documents += 1
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            if isinstance(event, yaml.NodeEvent):
                nodes += 1
                if event.anchor or getattr(event, 'tag', None):
                    issues.append(f'{_yaml_location(event.start_mark)}: use plain YAML values without tags, anchors or aliases.')
            if depth > MAX_DEPTH or nodes > MAX_NODES:
                raise YamlContractError(['Simplify the YAML. It exceeds the nesting or node limit.'])
        if documents != 1:
            issues.append(f'Return exactly one YAML document. Found {documents}.')
        if issues:
            raise YamlContractError(issues)
        node = yaml.compose(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, 'problem_mark', None)
        where = _yaml_location(mark) if mark is not None else 'YAML'
        reason = getattr(exc, 'problem', None) or 'invalid YAML syntax'
        raise YamlContractError([*issues, f'{where}: {reason}. The remaining content could not be validated.']) from None
    return _decode(node, '$', issues), issues


def _type(expression):
    """Compile a bounded set of type declarations without evaluating Python."""
    if type(expression) is not str or len(expression) > 128:
        raise ValueError('invalid type declaration')

    def visit(node):
        if isinstance(node, ast.Name) and node.id in _TYPES:
            return (node.id,)
        if isinstance(node, ast.Constant) and node.value is None:
            return ('None',)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return ('union', visit(node.left), visit(node.right))
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id == 'list':
                return ('list', visit(node.slice))
            if node.value.id == 'dict' and isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2:
                key, value = node.slice.elts
                if isinstance(key, ast.Name) and key.id == 'str':
                    return ('dict', visit(value))
        raise ValueError('invalid type declaration')

    try:
        return visit(ast.parse(expression.strip(), mode='eval').body)
    except (SyntaxError, RecursionError):
        raise ValueError('invalid type declaration') from None


def validate_interface(interface):
    if type(interface) is not dict or set(interface) != {'inputs', 'outputs'}:
        raise ValueError('invalid_interface')
    for side, fields in interface.items():
        if type(fields) is not dict or len(fields) > 100 or (side == 'outputs' and not fields):
            raise ValueError('invalid_interface')
        for name, declaration in fields.items():
            if type(name) is not str or not name or len(name) > 128:
                raise ValueError('invalid_interface')
            _type(declaration)


def _typed(value, spec, path, issues):
    if value is _INVALID:
        return value
    kind, *children = spec
    if kind == 'union':
        for option in children:
            trial = []
            result = _typed(value, option, path, trial)
            if not trial:
                return result
        issues.append(f'{path}: value does not match any declared type.')
        return _INVALID
    if kind == 'Decimal' and type(value) is str and len(value) <= 4400 and _DECIMAL.fullmatch(value):
        try:
            decimal = Decimal(value)
            pack(decimal, Limits())
            return decimal
        except (InvalidOperation, ValueError, OverflowError):
            pass
    if type(value) is not _TYPES[kind]:
        required = 'a quoted exact decimal string' if kind == 'Decimal' else kind
        issues.append(f'{path}: expected {required}, got {type(value).__name__}.')
        return _INVALID
    if children and kind == 'list':
        return [_typed(item, children[0], f'{path}[{index}]', issues) for index, item in enumerate(value, 1)]
    if children and kind == 'dict':
        return {key: _typed(item, children[0], f'{path}.{key}', issues) for key, item in value.items()}
    return value


def _keys(value, required, path, issues):
    if value is _INVALID:
        return {}
    if type(value) is not dict:
        issues.append(f'{path}: use a mapping, got {type(value).__name__}.')
        return {}
    for name in sorted(set(required) - value.keys()):
        issues.append(f'{path}: add the missing {name!r} key.')
    for name in sorted(value.keys() - set(required)):
        issues.append(f'{path}: remove the unexpected {name!r} key.')
    return value


def _variables(value, path, issues):
    if value is _INVALID:
        return None
    if type(value) is not list:
        issues.append(f'{path}: use a list of single-entry mappings.')
        return None
    fields = {}
    if len(value) > 100:
        issues.append(f'{path}: declare at most 100 variables.')
    for index, item in enumerate(value, 1):
        if type(item) is not dict or len(item) != 1:
            issues.append(f'{path}[{index}]: provide exactly one variable name and value.')
            continue
        name, field = next(iter(item.items()))
        if not name or len(name) > 128:
            issues.append(f'{path}[{index}]: use a name between 1 and 128 characters.')
        elif name in fields:
            issues.append(f'{path}: variable {name!r} appears more than once. Keep one entry.')
        else:
            fields[name] = field
    return fields


def validate_examples(text, count, *, one_shot=False, interface=None):
    """Return the original data document and normalised pairs, or all verifiable errors."""
    data, issues = read_yaml(text)
    document = _keys(data, ('interface', 'examples', 'source') if one_shot else
                     ('interface', 'examples'), '$', issues)
    declared = _keys(document['interface'], ('inputs', 'outputs'), 'interface', issues) if 'interface' in document else {}
    contracts = {}
    for side in ('inputs', 'outputs'):
        fields = _variables(declared[side], f'interface.{side}', issues) if side in declared else None
        if fields is None:
            continue
        if side == 'outputs' and not fields:
            issues.append('interface.outputs: declare at least one output.')
        if interface is not None and fields != interface.get(side):
            issues.append(f'interface.{side}: preserve the supplied names and types exactly.')
        specs = contracts[side] = {}
        for name, expression in fields.items():
            try:
                specs[name] = _type(expression)
            except ValueError:
                specs[name] = None
                issues.append(f'interface.{side}.{name}: use a supported type declaration.')
    if one_shot and 'source' in document and type(document['source']) is not str:
        issues.append('source: use a YAML literal string containing the Python script.')
    examples = document.get('examples', _INVALID)
    pairs = []
    if examples is not _INVALID:
        if type(examples) is not list:
            issues.append('examples: use a list of example objects.')
        else:
            if len(examples) != count:
                issues.append(f'examples: provide exactly {count} examples, found {len(examples)}.')
            for index, example in enumerate(examples, 1):
                path = f'examples[{index}]'
                entry = _keys(example, ('inputs', 'outputs'), path, issues)
                pair = {}
                for side in ('inputs', 'outputs'):
                    location = f'{path}.{side}'
                    fields = _variables(entry[side], location, issues) if side in entry else None
                    if fields is None:
                        continue
                    specs = contracts.get(side)
                    if specs is not None:
                        _keys(fields, specs, location, issues)
                        fields = {key: _typed(value, specs[key], f'{location}.{key}', issues)
                                  if specs.get(key) is not None else value for key, value in fields.items()}
                    pair[side] = fields
                pairs.append(pair)
    if issues:
        raise YamlContractError(issues)
    return document, pairs


class _Dumper(yaml.SafeDumper):
    pass


def _represent_string(dumper, value):
    # PyYAML's resolver does not recognise every plain scalar accepted by our loader.
    quote = _NUMBER.fullmatch(value) or value.lower() in ('.nan', '.inf', '+.inf', '-.inf')
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style="'" if quote else None)


_Dumper.add_representer(str, _represent_string)


def dump_examples(document):
    return yaml.dump(document, Dumper=_Dumper, sort_keys=False, allow_unicode=True)
