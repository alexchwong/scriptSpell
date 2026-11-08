"""Type-checking support is general; retain reflection and capability refusals."""
from decimal import Decimal
import pytest
from scriptspell import run,validate_source

NESTED='''def transform(inputs):
    patient = inputs["record"].get("patient")
    if patient is not None and isinstance(patient, dict):
        name = patient.get("name")
        if name is not None:
            return {"out": name}
        else:
            return {"out": None}
    return {"out": None}
'''

@pytest.mark.parametrize('record,expected',[
    ({'patient':{'name':'Sample'}},'Sample'), ({},None),
    ({'patient':{}},None), ({'patient':{'name':''}},''),
    ({'patient':{'name':None}},None), ({'patient':None},None),
    ({'patient':[]},None), ({'patient':'unexpected'},None),
])
def test_nested_type_guard(record,expected):
    r=run(NESTED,{'record':record},['out'])
    assert r['outcome']=='ok',r
    assert r['values']=={'out':expected}

@pytest.mark.parametrize('value,target,expected',[
    ({},'dict',True),([], 'list',True),('text','str',True),
    (42,'int',True),(False,'bool',True),(Decimal('1.20'),'Decimal',True),
    (None,'dict',False),([], 'dict',False),
])
def test_general_data_type_checks(value,target,expected):
    source='from decimal import Decimal\ndef transform(inputs):\n    return {"out": isinstance(inputs["x"], '+target+')}'
    r=run(source,{'x':value},['out'])
    assert r.get('values')=={'out':expected},r

@pytest.mark.parametrize('expression,symbol',[
    ('locals()', 'locals'), ('getattr(inputs, "x")','getattr'),
    ('type(inputs)','type'),('eval("1")','eval'),
    ('inputs.__class__','__class__'),('inputs.getcontext()','getcontext'),
])
def test_unapproved_reflection_and_calls_remain_denied(expression,symbol):
    r=validate_source('def transform(inputs):\n    return {"out": '+expression+'}')
    assert r['outcome']=='source_rejected'
    issue=next(i for i in r['issues'] if i.get('symbol')==symbol)
    assert issue['line']==2 and issue['message']
