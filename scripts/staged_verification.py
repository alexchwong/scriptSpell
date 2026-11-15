"""Independent answers for selected staged benchmark presets."""
from collections import Counter
from decimal import Decimal

from scriptspell import run_examples
from scriptspell.workflow import display_json, same_value


FIXED_CASES = {
    '05': (
        ("Inclusive bounds, exact decimals and stable record order",
         {'readings': [{'value': Decimal('1.10'), 'label': 'edge'}, {},
                       {'value': Decimal('1.09')}, {'value': None}, {'value': Decimal('1.11')}],
          'lower': Decimal('1.1'), 'upper': Decimal('1.10')},
         {'below': [{'value': Decimal('1.09')}],
          'within': [{'value': Decimal('1.10'), 'label': 'edge'}],
          'above': [{'value': Decimal('1.11')}], 'missing': [{}, {'value': None}]}),
    ),
    '06': (
        ("Only a leading hash starts a comment; the last value wins",
         {'lines': ['  # ignored=1', 'x=a', 'x=b=c#d', '  ', 'text # malformed', 'y=']},
         {'values': {'x': 'b=c#d', 'y': ''}, 'malformed_lines': [5]}),
        ("Trim split parts independently and retain the last value for trimmed keys",
         {'lines': ['name = Alex', ' name= Pat ', 'code = a=b#c', 'empty = ']},
         {'values': {'name': 'Pat', 'code': 'a=b#c', 'empty': ''}, 'malformed_lines': []}),
    ),
    '07': (
        ("Zero price is valid, and zero or boolean quantity is invalid",
         {'orders': [{'id': 'ok', 'quantity': 1, 'unit_price_cents': 0},
                     {'id': '', 'quantity': 0, 'unit_price_cents': 0},
                     {'quantity': True, 'unit_price_cents': -1}]},
         {'errors': [{'index': 1, 'field': 'id'}, {'index': 1, 'field': 'quantity'},
                     {'index': 2, 'field': 'id'}, {'index': 2, 'field': 'quantity'},
                     {'index': 2, 'field': 'unit_price_cents'}]}),
    ),
    '09': (
        ("Order fields must survive the join, including on unmatched orders",
         {'orders': [{'customer_id': 1, 'order_id': 'O1', 'total_cents': 1250},
                     {'customer_id': 3, 'order_id': 'O2', 'total_cents': 400},
                     {'customer_id': 2, 'order_id': 'O3', 'total_cents': 75}],
          'customers': [{'id': 1, 'name': 'A'}, {'id': 2, 'name': 'B'}]},
         {'result': [{'customer_id': 1, 'order_id': 'O1', 'total_cents': 1250, 'customer_name': 'A'},
                     {'customer_id': 3, 'order_id': 'O2', 'total_cents': 400, 'customer_name': None},
                     {'customer_id': 2, 'order_id': 'O3', 'total_cents': 75, 'customer_name': 'B'}]}),
    ),
    '12': (
        ("Empty intervals are omitted, reversed intervals are invalid, and touching intervals merge",
         {'intervals': [[5, 8], [1, 3], [7, 7], [3, 4], [9, 6], [6, 7], [2, 2]]},
         {'merged': [[1, 4], [5, 8]], 'invalid': [[9, 6]]}),
    ),
}


class Ineligible(ValueError):
    """An input is outside the task's defined scoring rules."""


def _records(inputs, key):
    items = inputs.get(key)
    if type(items) is not list or any(type(item) is not dict for item in items):
        raise Ineligible(f'{key} must be a list of records')
    return items


def _classify(inputs):
    readings = _records(inputs, 'readings')
    lower, upper = inputs.get('lower'), inputs.get('upper')
    values = [lower, upper, *(r['value'] for r in readings if r.get('value') is not None)]
    if type(lower) not in (int, Decimal) or any(type(value) is not type(lower) for value in values):
        raise Ineligible('bounds and present values must use a consistent exact numeric representation')
    if lower > upper:
        raise Ineligible('lower bound exceeds upper bound')
    result = {key: [] for key in ('below', 'within', 'above', 'missing')}
    for reading in readings:
        value = reading.get('value')
        if value is None:
            category = 'missing'
        elif value < lower:
            category = 'below'
        elif value > upper:
            category = 'above'
        else:
            category = 'within'
        result[category].append(reading)
    return result


def _parse_lines(inputs):
    lines = inputs.get('lines')
    if type(lines) is not list or any(type(line) is not str for line in lines):
        raise Ineligible('lines must be a list of strings')
    values, malformed = {}, []
    for index, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator:
            malformed.append(index)
            continue
        key, value = key.strip(), value.strip()
        if not key:
            raise Ineligible('empty keys have unspecified semantics')
        values[key] = value
    return {'values': values, 'malformed_lines': malformed}


def _validate_orders(inputs):
    errors = []
    for index, order in enumerate(_records(inputs, 'orders')):
        identifier, quantity, price = (order.get(field) for field in ('id', 'quantity', 'unit_price_cents'))
        if type(identifier) is str and identifier and not identifier.strip():
            raise Ineligible('whitespace-only IDs have unspecified semantics')
        checks = {'id': type(identifier) is str and identifier != '',
                  'quantity': type(quantity) is int and quantity > 0,
                  'unit_price_cents': type(price) is int and price >= 0}
        errors.extend({'index': index, 'field': field} for field, valid in checks.items() if not valid)
    return {'errors': errors}


def _join_orders(inputs):
    names = {}
    for customer in _records(inputs, 'customers'):
        identifier, name = customer.get('id'), customer.get('name')
        if type(identifier) not in (int, str) or type(name) is not str or identifier in names:
            raise Ineligible('customers must have unique string or integer IDs and string names')
        names[identifier] = name
    result = []
    for order in _records(inputs, 'orders'):
        if type(order.get('customer_id')) not in (int, str) or 'customer_name' in order:
            raise Ineligible('orders require customer IDs and must not already have customer_name')
        result.append(dict(order, customer_name=names.get(order['customer_id'])))
    return {'result': result}


REFERENCES = {'05': _classify, '06': _parse_lines, '07': _validate_orders, '09': _join_orders}


def _matches(task, expected, actual):
    return same_value(expected, actual)


def case_report(example_input, execution):
    report = dict(status=execution['status'], outcome=execution['outcome'],
                  input_json=display_json(example_input), expected_json=display_json(execution['expected']))
    if 'actual' in execution:
        report['actual_json'] = display_json(execution['actual'])
    return report


def fixed_verification(task, draft):
    fixtures = FIXED_CASES.get(task)
    if not fixtures:
        return {'status': 'UNVERIFIED'}
    if draft is None:
        return {'status': 'NOT_RUN', 'reason': 'Python draft unavailable'}
    example = draft['examples'][0]
    _, inputs, expected = fixtures[0]
    if example['example_input'].keys() != inputs.keys() or example['expected_output'].keys() != expected.keys():
        return {'status': 'NOT_RUN', 'reason': 'draft uses a different interface'}
    examples = [dict(id=str(index), example_input=inputs, expected_output=expected)
                for index, (_, inputs, expected) in enumerate(fixtures, 1)]
    executions = run_examples(dict(draft, examples=examples))
    cases = []
    for example, (note, _, expected), execution in zip(examples, fixtures, executions):
        case = case_report(example['example_input'], execution)
        if 'actual' in execution:
            case['status'] = 'pass' if _matches(task, expected, execution['actual']) else 'mismatch'
        cases.append(dict(case, case_id=example['id'], note=note))
    passed = sum(case['status'] == 'pass' for case in cases)
    return dict(status='PASS' if passed == len(cases) else 'FAIL', total=len(cases), passed=passed, cases=cases)


def reference_verification(task, examples=(), executions=()):
    rule = REFERENCES.get(task)
    cases = []
    for index, example in enumerate(examples, 1):
        if rule is None:
            break
        case = dict(case_id=str(index), visible=example['visible'], eligible=False)
        cases.append(case)
        try:
            expected = rule(example['example_input'])
        except Ineligible as exc:
            case.update(outcome='input_out_of_spec', reason=str(exc))
            continue
        case.update(eligible=True, reference_json=display_json(expected),
                    expected_json=display_json(example['expected_output']),
                    generated_expectation='PASS' if _matches(task, expected, example['expected_output']) else 'FAIL',
                    python_actual='NOT_RUN')
        if index <= len(executions) and 'actual' in executions[index - 1]:
            case['python_actual'] = 'PASS' if _matches(task, expected, executions[index - 1]['actual']) else 'FAIL'

    result = {'cases': cases}
    eligible = sum(case['eligible'] for case in cases)
    for side in ('generated_expectation', 'python_actual'):
        outcomes = Counter(case[side] for case in cases if case['eligible'])
        checked = outcomes['PASS'] + outcomes['FAIL']
        status = 'FAIL' if outcomes['FAIL'] else 'PASS' if checked else 'NOT_RUN' if rule else 'UNVERIFIED'
        result[side] = dict(status=status, checked=checked, eligible=eligible, passed=outcomes['PASS'])
        if status == 'NOT_RUN':
            result[side]['reason'] = 'no eligible generated inputs' if cases and not eligible else 'no outputs available'
    return result
