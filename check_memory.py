"""Usage: python check_memory.py [--report reports/memory.json]."""
import argparse
from feasibility_support import run_case, report, blocked_case


def main(argv=None):
    p=argparse.ArgumentParser(description='Measure synthetic caller/worker RSS and check allocation refusal and cleanup.')
    p.add_argument('--report',default='reports/memory.json')
    p.add_argument('--tree-mib',type=int,default=512)
    p.add_argument('--process-mib',type=int,default=256)
    args=p.parse_args(argv)
    if args.tree_mib<=0 or args.process_mib<=0: p.error('thresholds must be positive')
    try: import psutil
    except ImportError:
        return report('memory', [blocked_case('dependencies', 'install_dev_dependencies')], args.report)
    cases=[
        dict(name='fresh_workers_roundtrip',source='def transform(inputs):\n    return {"out": inputs["x"]}',inputs={'x':'sample'},expected=['ok'],expected_value='sample',repeat=8),
        dict(name='bounded_large_conversion',source='def transform(inputs):\n    return {"out": inputs["x"]}',inputs={'x':'x'*60000},expected=['ok'],expected_value='x'*60000),
        dict(name='allocation_bomb',source='def transform(inputs):\n    return {"out": "x" * 1000000000}',expected=['limit_exceeded']),
        dict(name='incremental_growth',source='def transform(inputs):\n    a = []\n    for i in range(2000000):\n        a.append("x" * 100 + str(i))\n    return {"out": a}',expected=['limit_exceeded']),
        dict(name='oversized_result',source='def transform(inputs):\n    return {"out": "x" * 200000}',expected=['invalid_result']),
        dict(name='parser_nesting',source='def transform(inputs):\n    return '+ '['*300+'0'+']'*300,expected=['source_rejected'],validate=True),
    ]
    results=[run_case(c,tree_mib=args.tree_mib,process_mib=args.process_mib) for c in cases]
    if not any(c['observed_monty_worker'] for c in results) and all(c['status']=='PASS' for c in results):
        results[0].update(status='BLOCKED',reason='no_runtime_worker_observed')
    return report('memory',results,args.report,{'tree_mib':args.tree_mib,'single_process_mib':args.process_mib,'sampling_seconds':0.005})

if __name__=='__main__': raise SystemExit(main())
