import pytest
from scriptspell import run,validate_source
from scriptspell.codec import unpack
from scriptspell.profile import IMPORTS

PROGRAMS=[
 ('def helper(x=2):\n    return x+1\ndef transform(inputs):\n    return {"out": helper()}',3),
 ('def transform(inputs):\n    fn=lambda x:x+1\n    return {"out": fn(2)}',3),
 ('def transform(inputs):\n    return {"out": sorted(["bbb","a"],key=lambda x:len(x))}',['a','bbb']),
 ('def transform(inputs):\n    def helper(x):\n        return x+2\n    return {"out": helper(3)}',5),
 ('def transform(inputs):\n    value: int = 3\n    return {"out": value}',3),
 ('def helper(x: int) -> int:\n    return x+1\ndef transform(inputs):\n    return {"out": helper(2)}',3),
 ('def transform(inputs):\n    try:\n        raise ValueError("bad")\n    except ValueError as error:\n        return {"out": str(error)}','bad'),
 ('def transform(inputs):\n    result=[]\n    try:\n        result.append(1)\n    except Exception:\n        result.append(0)\n    else:\n        result.append(2)\n    finally:\n        result.append(3)\n    return {"out": result}',[1,2,3]),
 ('def transform(inputs):\n    assert True\n    return {"out": f"value={3:04d}"}','value=0003'),
 ('def transform(inputs):\n    return {"out": list((x+1 for x in [1,2]))}',[2,3]),
 ('def transform(inputs):\n    return {"out": sorted({x for x in [2,1,2]})}',[1,2]),
 ('def transform(inputs):\n    a,*rest=[1,2,3]\n    return {"out": [a,*rest]}',[1,2,3]),
 ('def transform(inputs):\n    return {"out": {**{"a":1},"b":2}}',{'a':1,'b':2}),
 ('def transform(inputs):\n    value=0\n    for _ in range(3):\n        value+=1\n    return {"out": value}',3),
 ('def transform(inputs):\n    return {"out": (3<<2) | (5&1) ^ 0}',13),
 ('from re import compile\ndef transform(inputs):\n    return {"out": compile("a").fullmatch("a").group()}','a'),
 ('import re as regex\ndef transform(inputs):\n    return {"out": regex.findall("a","aba")}',['a','a']),
 ('from decimal import Decimal as D\ndef transform(inputs):\n    return {"out": str(D("1.20"))}','1.20'),
]

@pytest.mark.parametrize('source,expected',PROGRAMS)
def test_language_construct(source,expected):
    r=run(source,{},['out'])
    assert r.get('values')=={'out':expected},r

@pytest.mark.parametrize('module',sorted(IMPORTS))
def test_import_aliases(module):
    source=f'import {module} as library\ndef transform(inputs):\n    return {{"out": 1}}'
    assert run(source,{},['out']).get('values')=={'out':1}

SHADOW='''def type(value):
    if isinstance(value, dict):
        return dict
    if isinstance(value, str):
        return str
    return bool
def transform(inputs):
    return {"out": transform}
'''

def test_trusted_builtin_shadowing_rejected():
    assert validate_source(SHADOW)['outcome']=='source_rejected'

@pytest.mark.parametrize('source',[
 'def transform(inputs):\n    f=eval\n    return {"out": f("1")}',
 'import os\ndef transform(inputs):\n    return {"out": os.getenv("HOME")}',
 'import decimal\ndef transform(inputs):\n    return {"out": decimal.getcontext()}',
 'def transform(inputs):\n    return {"out": _ss_inputs}',
 'def transform(inputs):\n    try:\n        pass\n    except Exception as _ss_context:\n        pass\n    return {"out": 1}',
 'def transform(inputs):\n    return {"out": globals()}',
 'def transform(inputs):\n    return {"out": getattr(inputs,"x")}',
 'def transform(inputs):\n    return {"out": type(inputs)}',
 'def transform(inputs):\n    return {"out": 1**2}',
 'def transform(inputs):\n    return {"out": 2**-1}',
 'def transform(inputs):\n    return {"out": inputs.__class__}',
])
def test_boundaries_still_refuse(source):
    assert validate_source(source)['outcome']=='source_rejected'

@pytest.mark.parametrize('value',[
 ['b','forged bool'],['s',1],['n',0],['i','1.2'],['d','NaN'],['d','invalid'],['unknown',1],
 ['o',[[['s','x'],['n']],[['s','x'],['n']]]],
])
def test_transport_tags_are_strict(value):
    with pytest.raises(ValueError):unpack(value)

@pytest.mark.parametrize('action',[
 'try:\n    value="x"*1000000000\nexcept MemoryError:\n    return {"out":"caught"}',
 'try:\n    while True:\n        pass\nexcept Exception:\n    return {"out":"caught"}',
])
def test_limits_cannot_be_caught_to_publish_outputs(action):
    source='def transform(inputs):\n'+'\n'.join('    '+x for x in action.splitlines())+'\n    return {"out":1}'
    assert run(source,{},['out'])['outcome']=='limit_exceeded'


def test_regex_resource_bound():
    from scriptspell import Limits
    r=run('import re\ndef transform(inputs):\n    return {"out": bool(re.fullmatch("(a+)+$",inputs["text"]))}',
          {'text':'a'*20000+'!'},['out'],limits=Limits(execution_seconds=0.1,wall_seconds=2))
    assert r['outcome'] in ('ok','runtime_error','limit_exceeded','deadline')
    if r['outcome']=='ok':assert r['values']=={'out':False}

@pytest.mark.parametrize('source',[
 'import math\ndef transform(inputs):\n    return {"out": math.exp(1)}',
 'import math\ndef transform(inputs):\n    other=math\n    return {"out": other.exp(1)}',
 'import math\ndef transform(inputs):\n    return {"out": [math][0].exp(1)}',
 'import datetime\ndef transform(inputs):\n    return {"out": datetime.datetime.now()}',
 'import json\ndef transform(inputs):\n    return {"out": json.loads("0.1")}',
])
def test_module_permissions_cannot_be_bypassed(source):
    assert validate_source(source)['outcome']=='source_rejected'

@pytest.mark.parametrize('source',[
 'import csv\ndef transform(inputs):\n    return {"out": list(csv.reader(["0.123"],quoting=2))}',
 'import csv\ndef transform(inputs):\n    reader=csv.reader\n    return {"out": list(reader(["0.123"],quoting=2))}',
 'from csv import reader\ndef transform(inputs):\n    return {"out": list(reader(["0.123"],**{"quoting":2}))}',
])
def test_csv_float_conversion_paths_denied(source):
    assert validate_source(source)['outcome']=='source_rejected'


def test_trusted_encoder_namespace_is_isolated_even_without_static_filter():
    # Fixed regression fixture only; no production bypass is introduced.
    import textwrap
    from importlib.metadata import distribution
    from pydantic_monty import Monty
    from scriptspell._guest import SUPPORT
    dist=distribution('pydantic-monty-runtime')
    binary=next(dist.locate_file(p) for p in dist.files if str(p).endswith('/monty'))
    program=SUPPORT+'\ndef _ss_invoke_user():\n'+textwrap.indent(SHADOW,'    ')+'\n    return transform(_ss_inputs)\n_ss_finish()'
    with Monty(binary_path=binary,max_processes=1,request_timeout=2) as pool:
        with pool.checkout(limits={'max_memory':67108864,'max_feed_duration_secs':1}) as session:
            out=session.feed_run(program,inputs={'_ss_inputs':{},'_ss_outputs':['out'],'_ss_depth':32,'_ss_nodes':20000,'_ss_bytes':1048576},print_callback=lambda *_:None)
    assert out==['error','invalid_result']

@pytest.mark.parametrize('source',[
 'def transform(inputs):\n    fn=pow\n    return {"out": fn(2,-1)}',
 'def transform(inputs):\n    fn=type\n    return {"out": fn(inputs)}',
])
def test_unadvertised_builtin_aliases_denied(source):
    assert validate_source(source)['outcome']=='source_rejected'

@pytest.mark.parametrize('source,expected',[
 ('def transform(inputs):\n    if (size := len(inputs["items"])):\n        return {"out": size}\n    return {"out": 0}',2),
 ('def transform(inputs):\n    match inputs["items"]:\n        case [first, *rest]:\n            return {"out": [first,rest]}\n        case _:\n            return {"out": None}',[1,[2]]),
 ('def transform(inputs):\n    match {"a": 2, "b": 3}:\n        case {"a": value, **rest}:\n            return {"out": [value,rest]}\n        case _:\n            return {"out": None}',[2,{'b':3}]),
 ('def transform(inputs):\n    match 2:\n        case (1 | 2) as value if value>0:\n            return {"out": value}\n        case _:\n            return {"out": None}',2),
 ('def transform(inputs):\n    match None:\n        case None:\n            return {"out": True}\n        case _:\n            return {"out": False}',True),
])
def test_assignment_and_data_patterns(source,expected):
    assert run(source,{'items':[1,2]},['out']).get('values')=={'out':expected}

@pytest.mark.parametrize('pattern', ['{"x": _ss_context}','[type,*rest]','{"x": value, **_ss_inputs}'])
def test_pattern_binding_cannot_replace_reserved_names(pattern):
    source='def transform(inputs):\n    match inputs:\n        case '+pattern+':\n            return {"out": 1}\n    return {"out": 0}'
    assert validate_source(source)['outcome']=='source_rejected'

@pytest.mark.parametrize('source,expected',[
 ('def transform(inputs):\n    return {"out": """first\nsecond\n  third"""}', 'first\nsecond\n  third'),
 ('def transform(inputs):\n    return {"out": b"""a\nb""".decode()}', 'a\nb'),
 ('def transform(inputs):\n    return {"out": f"""number={3}\nnext"""}', 'number=3\nnext'),
])
def test_wrapper_preserves_multiline_literals(source,expected):
    assert run(source,{},['out']).get('values')=={'out':expected}


def test_non_utf8_source_is_a_structured_refusal():
    source='def transform(inputs):\n    return {"out": "\ud800"}'
    assert validate_source(source)['outcome']=='source_rejected'
    assert run(source,{},['out'])['outcome']=='source_rejected'
