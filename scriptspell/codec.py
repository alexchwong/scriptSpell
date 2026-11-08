"""Private bounded typed transport. No pickle, arbitrary objects or float coercion."""
import json
from decimal import Decimal, InvalidOperation


def pack(value, limits):
    budget = [0, 0]
    ancestors = set()
    def walk(v, depth):
        budget[0] += 1
        if depth > limits.depth or budget[0] > limits.nodes:
            raise ValueError('value_limit')
        t = type(v)
        if t is str:
            if len(v) > limits.value_bytes:
                raise ValueError('value_limit')
            budget[1] += len(v.encode('utf-8'))
            out = ['s', v]
        elif v is None:
            out = ['n']
        elif t is bool:
            out = ['b', v]
        elif t is int:
            if v.bit_length() > 14280:
                raise ValueError('number_limit')
            out = ['i', str(v)]
            budget[1] += len(out[1])
        elif t is Decimal:
            if not v.is_finite() or len(v.as_tuple().digits) > 4300 or abs(v.as_tuple().exponent) > 999999:
                raise ValueError('number_limit')
            out = ['d', str(v)]
            budget[1] += len(out[1])
        elif t in (list, dict):
            if len(v) > limits.nodes:
                raise ValueError('value_limit')
            if id(v) in ancestors:
                raise ValueError('cycle')
            ancestors.add(id(v))
            try:
                if t is list:
                    out = ['l', [walk(x, depth + 1) for x in v]]
                else:
                    out = ['o', [[walk(k, depth + 1), walk(x, depth + 1)] for k, x in v.items() if type(k) is str]]
                    if len(out[1]) != len(v):
                        raise ValueError('key_type')
            finally:
                ancestors.remove(id(v))
        else:
            raise ValueError('unsupported_value')
        budget[1] += 16
        if budget[1] > limits.value_bytes:
            raise ValueError('value_limit')
        return out
    out = walk(value, 0)
    if len(json.dumps(out, ensure_ascii=True).encode()) > limits.value_bytes:
        raise ValueError('value_limit')
    return out


def unpack(node):
    """Validate the tagged representation before constructing public values."""
    if type(node) is not list or not node or type(node[0]) is not str:
        raise ValueError('invalid_transport')
    tag=node[0]
    if tag=='n':
        if len(node)!=1:raise ValueError('invalid_transport')
        return None
    if len(node)!=2:raise ValueError('invalid_transport')
    value=node[1]
    if tag=='s' and type(value) is str:return value
    if tag=='b' and type(value) is bool:return value
    if tag in ('i','d') and type(value) is str:
        if len(value)>4400:raise ValueError('invalid_transport')
        if tag=='i':
            import re
            if not re.fullmatch(r'-?(?:0|[1-9][0-9]*)',value):raise ValueError('invalid_transport')
            return int(value)
        try:result=Decimal(value)
        except InvalidOperation:raise ValueError('invalid_transport') from None
        if not result.is_finite() or len(result.as_tuple().digits)>4300 or abs(result.as_tuple().exponent)>999999:
            raise ValueError('invalid_transport')
        return result
    if tag=='l' and type(value) is list:return [unpack(x) for x in value]
    if tag=='o' and type(value) is list:
        result={}
        for pair in value:
            if type(pair) is not list or len(pair)!=2:raise ValueError('invalid_transport')
            key=unpack(pair[0])
            if type(key) is not str or key in result:raise ValueError('invalid_transport')
            result[key]=unpack(pair[1])
        return result
    raise ValueError('invalid_transport')
