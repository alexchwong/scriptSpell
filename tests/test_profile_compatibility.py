"""Every advertised name has a positive pinned-runtime fixture."""
import pytest
from scriptspell import profile,run
from scriptspell.profile import BUILTINS,DATA_METHODS,IMPORTS
from profile_cases import BUILTIN_CASES,METHOD_CASES,MODULE_CASES


def execute(expr,before=''):
    statements=(before+'\n' if before else '')+'return {"out": '+expr+'}'
    source='def transform(inputs):\n'+'\n'.join('    '+s for s in statements.split('\n'))
    return run(source,{},['out'])


def test_every_advertised_name_has_a_probe():
    assert set(BUILTIN_CASES)==set(BUILTINS)
    assert set(METHOD_CASES)==set(DATA_METHODS)
    assert set(MODULE_CASES)=={(m,n) for m,names in IMPORTS.items() for n in names}
    assert profile()['profile']=='scriptspell-pure-v3'

@pytest.mark.parametrize('name',sorted(BUILTIN_CASES))
def test_builtin(name):
    expr,expected=BUILTIN_CASES[name]
    r=execute(expr)
    assert r['outcome']=='ok',r
    assert type(r['values']['out']) is type(expected) and r['values']['out']==expected

@pytest.mark.parametrize('name',sorted(METHOD_CASES))
def test_method(name):
    expr,expected,before=METHOD_CASES[name]
    r=execute(expr,before)
    assert r['outcome']=='ok',r
    assert type(r['values']['out']) is type(expected) and r['values']['out']==expected

@pytest.mark.parametrize('name',sorted(MODULE_CASES),ids=lambda x:'.'.join(x))
def test_module_member(name):
    expr,expected,before=MODULE_CASES[name]
    r=execute(expr,before)
    assert r['outcome']=='ok',r
    assert type(r['values']['out']) is type(expected) and r['values']['out']==expected

@pytest.mark.parametrize('name',sorted(MODULE_CASES),ids=lambda x:'.'.join(x))
def test_from_import_member(name):
    module,member=name
    expr,expected,before=MODULE_CASES[name]
    expr=expr.replace(module+'.'+member,'imported_member')
    r=execute(expr,before+'\nfrom '+module+' import '+member+' as imported_member')
    assert r['outcome']=='ok',r
    assert type(r['values']['out']) is type(expected) and r['values']['out']==expected
