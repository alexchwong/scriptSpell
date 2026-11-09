"""Explicitly invoked, paid OpenRouter experiment; never used by ordinary pytest/CI."""
import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from authoring_jobs import JOBS
from scriptspell import prepare_authoring, validate_proposal, run, profile

ENDPOINT='https://openrouter.ai/api/v1/chat/completions'

class TransportError(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise TransportError('redirect_refused')


def complete(materials,model,key,max_tokens,timeout):
    payload={'model':model,'max_tokens':max_tokens,'temperature':0,
             'messages':[{'role':'system','content':materials['system']+'\nReturn exactly this JSON schema: '+json.dumps(materials['response_schema'])},
                         {'role':'user','content':materials['user']} ]}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    # No proxy credential propagation or redirection to another destination.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(req,timeout=timeout) as response:
            body=response.read(2*1024*1024+1)
            if len(body)>2*1024*1024: raise TransportError('response_limit')
            result=json.loads(body)
    except urllib.error.HTTPError as exc:
        raise TransportError('http_'+str(exc.code)) from None
    except (urllib.error.URLError,TimeoutError,OSError,ValueError):
        raise TransportError('request_failed') from None
    if 'error' in result: raise TransportError('provider_error')
    try:
        choice=result['choices'][0]
        if choice.get('finish_reason')!='stop': raise TransportError('incomplete_response')
        content=choice['message']['content']
        if type(content) is not str: raise TransportError('invalid_response')
        usage={k:result.get('usage',{}).get(k) for k in ('prompt_tokens','completion_tokens','total_tokens')}
        return content,usage,result.get('model',model)
    except (KeyError,IndexError,TypeError):
        raise TransportError('invalid_response') from None


def same_value(actual,expected):
    if type(actual) is not type(expected):return False
    if type(expected) is dict:
        return actual.keys()==expected.keys() and all(same_value(actual[k],v) for k,v in expected.items())
    if type(expected) is list:
        return len(actual)==len(expected) and all(same_value(a,b) for a,b in zip(actual,expected))
    return actual==expected


def check_case(source,case):
    inputs,expected=case
    try:
        result=run(source,deepcopy(inputs),['out'])
    except RuntimeError:
        return False,'cleanup_failed'
    return result['outcome']=='ok' and same_value(result['values'],{'out':expected}),result['outcome']


def evaluate(job,model,key,max_tokens,timeout,repairs,transport=complete):
    attempts=[]
    diagnostics=None
    final=None
    for index in range(repairs+1):
        materials=prepare_authoring(job['task'],job['interface'],
            [{'inputs':job['visible'][0],'outputs':{'out':job['visible'][1]}}],diagnostics)
        started=time.monotonic()
        try:
            text,usage,actual_model=transport(materials,model,key,max_tokens,timeout)
        except TransportError as exc:
            attempts.append({'attempt':index+1,'outcome':'transport_error','code':str(exc),'elapsed_seconds':time.monotonic()-started})
            return {'id':job['id'],'status':'BLOCKED','attempts':attempts}
        attempt={'attempt':index+1,'elapsed_seconds':time.monotonic()-started,
                 'usage':usage,'actual_model':actual_model}
        try:
            proposal=json.loads(text)
            # Retain a bounded proposal source before validation, including rejects.
            if type(proposal) is dict and type(proposal.get('source')) is str:
                source=proposal['source']
                attempt['source']=source[:65536]
                attempt['source_truncated']=len(source)>65536
            validation=validate_proposal(proposal)
        except (ValueError,TypeError,RecursionError):
            validation={'outcome':'invalid_proposal'}
        attempt['validation']=validation['outcome']
        attempt['validation_issues']=validation.get('issues',[])
        if validation['outcome']=='invalid_proposal' and 'source' not in attempt:
            attempt['response_excerpt']=text[:16384]
            attempt['response_truncated']=len(text)>16384
        if validation['outcome'] in ('dependency_unavailable','platform_unavailable','worker_crash','cleanup_failed'):
            attempts.append(attempt)
            return {'id':job['id'],'status':'BLOCKED','attempts':attempts}
        if validation['outcome']=='ok':
            attempt['example_input']=proposal['example_input']
            attempt['expected_output']=proposal['expected_output']
            correct,outcome=check_case(proposal['source'],job['visible'])
            attempt.update(development_outcome=outcome,development_correct=correct)
            if outcome=='cleanup_failed':
                attempts.append(attempt)
                return {'id':job['id'],'status':'FAIL','attempts':attempts}
            if correct:
                final=proposal['source'];attempts.append(attempt);break
        attempts.append(attempt)
        previous_source=attempt.get('source')
        diagnostics={'previous_source':previous_source[:16384] if previous_source is not None else None,
                     'previous_source_truncated':attempt.get('source_truncated',False) or (previous_source is not None and len(previous_source)>16384),
                     'validation':validation['outcome'],
                     'issues':attempt['validation_issues'],
                     'development_correct':attempt.get('development_correct',False)}
        if 'response_excerpt' in attempt:
            diagnostics['previous_response_excerpt']=attempt['response_excerpt'][:8192]
    hidden=[]
    if final is not None:
        for case in job['hidden']:
            correct,outcome=check_case(final,case)
            hidden.append({'correct':correct,'outcome':outcome})
    correct=bool(hidden) and all(c['correct'] for c in hidden)
    return dict(id=job['id'],status='PASS' if correct else 'FAIL',attempts=attempts,
                first_pass_correct=correct and len(attempts)==1,held_out=hidden)


def main(argv=None):
    p=argparse.ArgumentParser(description='Generate proposals through OpenRouter, validate, then explicitly test in Monty. Uses synthetic data; incurs API charges.')
    p.add_argument('--model')
    p.add_argument('--task',choices=[j['id'] for j in JOBS])
    p.add_argument('--list',action='store_true')
    p.add_argument('--max-tokens',type=int,default=4096)
    p.add_argument('--repairs',type=int,choices=(0,1,2),default=0)
    p.add_argument('--timeout',type=float,default=90)
    p.add_argument('--report',default='reports/authoring_openrouter.json')
    args=p.parse_args(argv)
    if args.list:
        for job in JOBS: print(job['id']+': '+job['task'])
        return 0
    if not args.model: p.error('--model is required')
    if not 1<=args.max_tokens<=16384 or not 0<args.timeout<=300: p.error('invalid token/timeout limit')
    key=os.environ.get('OPENROUTER_API_KEY') or getpass.getpass('OpenRouter API key (not saved): ')
    if not key: p.error('API key required')
    jobs=[j for j in JOBS if not args.task or j['id']==args.task]
    print(f'Authoring role model: {args.model}; at most {len(jobs)*(args.repairs+1)} paid requests, {args.max_tokens} output tokens per request.')
    results=[]
    for job in jobs:
        result=evaluate(job,args.model,key,args.max_tokens,args.timeout,args.repairs)
        results.append(result);print(result['status']+' '+job['id'])
        if result['status']=='BLOCKED': break  # No blind network retries.
    status='FAIL' if any(r['status']=='FAIL' for r in results) else ('BLOCKED' if any(r['status']=='BLOCKED' for r in results) else 'PASS')
    report={'status':status,'requested_model':args.model,'runtime_profile':profile(),
            'settings':{'max_tokens':args.max_tokens,'repairs':args.repairs,'temperature':0,'timeout':args.timeout},
            'tasks_requested':len(jobs),'tasks_completed':len(results),
            'correct_tasks':sum(r['status']=='PASS' for r in results),
            'first_pass_correct_tasks':sum(r.get('first_pass_correct',False) for r in results),
            'calls':sum(len(r['attempts']) for r in results),'results':results}
    path=Path(args.report);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(status+': '+str(path))
    return 0 if status=='PASS' else (2 if status=='BLOCKED' else 1)

if __name__=='__main__':raise SystemExit(main())
