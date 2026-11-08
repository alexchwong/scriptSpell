"""Regression checks for the test scripts; not added to the product wheel."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Installed-wheel suites outside the checkout do not include repository tools.
pytestmark = pytest.mark.skipif(not (ROOT/'feasibility_support.py').exists(), reason='repository-only feasibility tools')


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mismatched_process_identity_never_signals_visible_pid(monkeypatch):
    import psutil
    support=load('feasibility_support')
    monkeypatch.setattr(support,'_pid_namespace_visible',lambda:True)
    class UnrelatedProcess:
        def cmdline(self): return ['unrelated-service']
        def kill(self): raise AssertionError('must not signal unrelated process')
        def children(self,**kw): raise AssertionError('must not inspect unrelated descendants')
    monkeypatch.setattr(psutil,'Process',lambda pid:UnrelatedProcess())
    r=support.run_case(dict(name='identity',source='SHOULD NOT EXECUTE',expected=['ok']))
    assert r['status']=='BLOCKED'
    assert r['reason']=='process_identity_not_observable'
    assert r['sampled_peak_tree_mib'] is None


@pytest.mark.parametrize('status,code',[('PASS',0),('FAIL',1),('BLOCKED',2)])
def test_report_exit_codes(tmp_path,status,code):
    support=load('feasibility_support')
    case=support.blocked_case('fixture','reason')
    case['status']=status
    path=tmp_path/'report.json'
    assert support.report('test',[case],path)==code
    assert json.loads(path.read_text())['status']==status


@pytest.mark.parametrize('spec',[
    dict(name='growth',source='def transform(inputs):\n    a = []\n    for i in range(2000000):\n        a.append("x" * 100 + str(i))\n    return {"out": a}',expected=['limit_exceeded']),
    dict(name='crash',source='def transform(inputs):\n    while True:\n        pass',expected=['worker_crash'],crash=True),
    dict(name='deadline',source='def transform(inputs):\n    while True:\n        pass',expected=['deadline'],wall_seconds=0.15),
    dict(name='raw_print',source='while True:\n    print("x" * 1000)',raw=True),
])
def test_case_driver_runs_real_fixture(spec):
    result=subprocess.run([sys.executable,str(ROOT/'_feasibility_case.py')],input=json.dumps(spec),
                          capture_output=True,text=True,timeout=12)
    assert result.returncode==0
    assert json.loads(result.stdout)['status']=='PASS',result.stdout

@pytest.mark.parametrize('script,count',[('check_memory',6),('check_adversarial',19)])
def test_all_script_fixtures_without_process_sampling(monkeypatch,script,count):
    # Execute every real fixture independently of process observation. This does
    # not claim memory measurements; the real CLI reports BLOCKED if unobservable.
    monkeypatch.syspath_prepend(str(ROOT))
    module=load(script)
    seen=[]
    def execute(spec,**kwargs):
        result=subprocess.run([sys.executable,str(ROOT/'_feasibility_case.py')],input=json.dumps(spec),
                              text=True,capture_output=True,timeout=12)
        case=json.loads(result.stdout)
        assert case['status']=='PASS',(spec['name'],case)
        case.update(name=spec['name'],observed_monty_worker=False)
        seen.append(case)
        return case
    monkeypatch.setattr(module,'run_case',execute)
    monkeypatch.setattr(module,'report',lambda *args,**kwargs:0)
    monkeypatch.setattr(sys,'argv',[script+'.py'])
    assert module.main()==0
    assert len(seen)==count


def test_unobservable_namespace_never_launches_or_signals(monkeypatch):
    support=load('feasibility_support')
    monkeypatch.setattr(support,'_pid_namespace_visible',lambda:False)
    def forbidden(*args,**kwargs):raise AssertionError('must not launch in unobservable namespace')
    monkeypatch.setattr(support.subprocess,'Popen',forbidden)
    r=support.run_case(dict(name='namespace',source='unused'))
    assert r['status']=='BLOCKED' and r['reason']=='process_namespace_not_observable'
