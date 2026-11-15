"""Trusted guest support. This is concatenated into Monty, never host exec'd."""
SUPPORT = r'''
from decimal import Decimal as _ss_Decimal
from decimal import getcontext as _ss_getcontext
from decimal import Inexact as _ss_Inexact
from decimal import Rounded as _ss_Rounded
_ss_context = _ss_getcontext()
_ss_context.prec = 128
_ss_context.traps[_ss_Inexact] = True
_ss_context.traps[_ss_Rounded] = True

def _ss_encode(v, depth, ancestors, budget):
    budget[0] += 1
    if depth > _ss_depth or budget[0] > _ss_nodes:
        raise ValueError('result_limit')
    t = type(v)
    if t is str:
        budget[1] += len(v) * 12 + 16
        out = ['s', v]
    elif v is None:
        out = ['n']
    elif t is bool:
        out = ['b', v]
    elif t is int:
        text = str(v)
        if len(text) > 4301:
            raise ValueError('number_limit')
        budget[1] += len(text) + 16
        out = ['i', text]
    elif t is float:
        if v - v != 0.0:
            raise ValueError('number_limit')
        text = str(v)
        budget[1] += len(text)
        out = ['f', text]
    elif t is _ss_Decimal:
        text = str(v)
        if not v.is_finite() or len(v.as_tuple().digits) > 4300 or abs(v.as_tuple().exponent) > 999999:
            raise ValueError('number_limit')
        budget[1] += len(text) + 16
        out = ['d', text]
    elif t is list or t is dict:
        for ancestor in ancestors:
            if v is ancestor:
                raise ValueError('cycle')
        ancestors.append(v)
        if t is list:
            out = ['l', [_ss_encode(x, depth + 1, ancestors, budget) for x in v]]
        else:
            pairs = []
            for k, x in v.items():
                if type(k) is not str:
                    raise ValueError('key_type')
                pairs.append([_ss_encode(k, depth + 1, ancestors, budget), _ss_encode(x, depth + 1, ancestors, budget)])
            out = ['o', pairs]
        ancestors.pop()
    else:
        raise ValueError('unsupported_result')
    budget[1] += 16
    if budget[1] > _ss_bytes:
        raise ValueError('result_limit')
    return out

def _ss_finish():
    result = _ss_invoke_user()
    try:
        if type(result) is not dict or sorted(result.keys()) != sorted(_ss_outputs):
            return ['error', 'invalid_result']
        return ['ok', _ss_encode(result, 0, [], [0, 0])]
    except (ValueError, TypeError):
        return ['error', 'invalid_result']
'''
