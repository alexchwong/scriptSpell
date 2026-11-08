import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(not (ROOT/'check_authoring_openrouter.py').exists(),reason='repository-only manual runner')

@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec=importlib.util.spec_from_file_location('authoring_runner',ROOT/'check_authoring_openrouter.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def proposal(source):
    return json.dumps(dict(source=source,summary='Synthetic',assumptions=[],unmet_requirements=[])),{},'test/model'

def test_held_out_and_budget(runner):
    calls=[]
    def transport(materials,*args):
        calls.append(materials)
        if len(calls)==1:return proposal('def transform(inputs):\n    return {"out": "wrong"}')
        return proposal('def transform(inputs):\n    return {"out": [x.strip() for x in inputs["items"] if x.strip()]}')
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,2,transport)
    assert r['status']=='PASS' and len(calls)==2
    assert not r['first_pass_correct']
    assert 'é' not in ''.join(c['user'] for c in calls)
    assert 'FAKE_KEY' not in json.dumps(r)

def test_valid_but_wrong_hidden_answer_fails(runner):
    def transport(*args):return proposal('def transform(inputs):\n    return {"out": ["a"]}')
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,2,transport)
    assert r['status']=='FAIL' and len(r['attempts'])==1
    assert not all(x['correct'] for x in r['held_out'])

def test_network_failure_has_no_retry(runner):
    calls=[]
    def transport(*args):calls.append(1);raise runner.TransportError('http_401')
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,2,transport)
    assert r['status']=='BLOCKED' and len(calls)==1

def test_malformed_proposal_exhausts_budget(runner):
    calls=[]
    def transport(*args):calls.append(1);return 'not json',{},'test/model'
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,2,transport)
    assert r['status']=='FAIL' and len(calls)==3

def test_list_does_not_prompt_or_call_network(runner,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('unexpected network or key prompt')
    monkeypatch.setattr(runner.getpass,'getpass',forbidden)
    monkeypatch.setattr(runner.urllib.request,'build_opener',forbidden)
    assert runner.main(['--list'])==0

def test_redirects_are_refused(runner):
    with pytest.raises(runner.TransportError):runner.NoRedirect().redirect_request(None,None,None,None,None,None)

def test_http_request_contract(runner,monkeypatch):
    captured=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{}'}}],'usage':{'total_tokens':3},'model':'actual/model'}).encode()
    class Opener:
        def open(self,request,timeout):captured.append((request,timeout));return Response()
    monkeypatch.setattr(runner.urllib.request,'build_opener',lambda *args:Opener())
    materials=runner.prepare_authoring('job',{'inputs':{},'outputs':{'out':'integer'}})
    text,usage,model=runner.complete(materials,'test/model','FAKE_KEY',128,1)
    req,timeout=captured[0]
    assert req.full_url==runner.ENDPOINT
    assert req.headers['Authorization']=='Bearer FAKE_KEY'
    assert json.loads(req.data)['max_tokens']==128 and timeout==1
    assert 'FAKE_KEY' not in req.data.decode()
    assert text=='{}' and usage['total_tokens']==3 and model=='actual/model'


def test_manual_report_never_stores_key(runner,monkeypatch,tmp_path):
    monkeypatch.setenv('OPENROUTER_API_KEY','FAKE_KEY')
    original=runner.evaluate
    def transport(*args):return proposal('def transform(inputs):\n    return {"out": [x.strip() for x in inputs["items"] if x.strip()]}')
    monkeypatch.setattr(runner,'evaluate',lambda *args:original(*args,transport=transport))
    path=tmp_path/'live.json'
    assert runner.main(['--model','test/model','--task','trim','--report',str(path)])==0
    report=path.read_text()
    assert 'FAKE_KEY' not in report
    assert json.loads(report)['first_pass_correct_tasks']==1

def test_correctness_checks_types_not_just_python_equality(runner):
    source='from decimal import Decimal\ndef transform(inputs):\n    return {"out": int(Decimal(inputs["vaf"]) >= Decimal("0.05"))}'
    def transport(*args):return proposal(source)
    r=runner.evaluate(runner.JOBS[-1],'test/model','FAKE_KEY',128,1,0,transport)
    assert r['status']=='FAIL'

def test_rejected_source_saved_and_sent_for_repair(runner,monkeypatch):
    rejected='def transform(inputs):\n    return {"out": getattr(inputs, "items")}'
    fixed='def transform(inputs):\n    return {"out": [x.strip() for x in inputs["items"] if x.strip()]}'
    requests=[]
    executed=[]
    original=runner.check_case
    def check(source,case):
        executed.append(source)
        return original(source,case)
    monkeypatch.setattr(runner,'check_case',check)
    def transport(materials,*args):
        requests.append(materials)
        return proposal(rejected if len(requests)==1 else fixed)
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,2,transport)
    first=r['attempts'][0]
    assert r['status']=='PASS' and len(requests)==2
    assert first['validation']=='source_rejected'
    assert first['source']==rejected
    assert first['validation_issues']
    feedback=json.loads(requests[1]['user'])['diagnostics']
    assert feedback['previous_source']==rejected
    assert feedback['issues']==first['validation_issues']
    assert rejected not in executed  # Rejected proposals are never tested.


def test_all_rejected_attempts_retain_details(runner):
    bad='def transform(inputs):\n    return {"out": getattr(inputs, "items")}'
    def transport(*args):return proposal(bad)
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,2,transport)
    assert r['status']=='FAIL' and len(r['attempts'])==3
    assert all(a['source']==bad and a['validation_issues'] for a in r['attempts'])


def test_malformed_response_excerpt_sent_for_repair(runner):
    requests=[]
    def transport(materials,*args):
        requests.append(materials)
        return 'not json',{},'test/model'
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,1,transport)
    assert r['attempts'][0]['response_excerpt']=='not json'
    assert json.loads(requests[1]['user'])['diagnostics']['previous_response_excerpt']=='not json'


def test_oversized_source_and_feedback_are_bounded(runner):
    source='x'*70000
    requests=[]
    def transport(materials,*args):
        requests.append(materials)
        return proposal(source)
    r=runner.evaluate(runner.JOBS[0],'test/model','FAKE_KEY',128,1,1,transport)
    assert len(r['attempts'][0]['source'])==65536
    assert r['attempts'][0]['source_truncated']
    feedback=json.loads(requests[1]['user'])['diagnostics']
    assert len(feedback['previous_source'])==16384
    assert feedback['previous_source_truncated']
