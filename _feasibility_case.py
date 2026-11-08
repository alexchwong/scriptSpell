"""Private test driver: executes fixed fixtures in the actual restricted runtime."""
import json
import sys
import threading
from pathlib import Path


def main(spec):
    from scriptspell import Limits, profile, run, validate_source
    if profile()['packages']['pydantic-monty'] != '1.5.0':
        return {'status': 'BLOCKED', 'reason': 'pinned_runtime_not_installed'}
    if sys.platform not in ('linux', 'darwin'):
        return {'status': 'BLOCKED', 'reason': 'platform_unavailable'}
    source = spec['source']
    if spec.get('raw'):
        # Tests independently exercise Monty's no-capability configuration.
        # This path is not imported or included in the product wheel.
        from datetime import datetime, timezone
        from importlib.metadata import distribution
        from pydantic_monty import Monty, MontyRuntimeError
        dist = distribution('pydantic-monty-runtime')
        binary = next(dist.locate_file(p) for p in dist.files if str(p).endswith('/monty'))
        with Monty(binary_path=binary, max_processes=1, request_timeout=2) as pool:
            with pool.checkout(limits={'max_memory': 67108864, 'max_feed_duration_secs': 0.2,
                                      'max_recursion_depth': 128, 'max_suspensions': 10,
                                      'max_total_sleep_secs': 0},
                               os_policy={'datetime': datetime(2000,1,1,tzinfo=timezone.utc),
                                          'timezone':'utc', 'sleep':'zero', 'process_time':'zero',
                                          'random_start':{'seed':0}}) as session:
                try:
                    session.feed_run(source, print_callback=lambda *_: None)
                except MontyRuntimeError:
                    return {'status': 'PASS', 'reason': 'guest_operation_refused'}
                return {'status': 'FAIL', 'reason': 'forbidden_operation_succeeded'}
    if spec.get('validate'):
        r = validate_source(source)
        return {'status': 'PASS' if r['outcome'] in spec['expected'] else 'FAIL', 'outcomes':[r['outcome']]}
    if spec.get('crash'):
        import os
        import signal
        import scriptspell.runtime as runtime
        launch = runtime.subprocess.Popen
        def launch_and_kill(*args, **kwargs):
            process = launch(*args, **kwargs)
            def kill():
                try: os.kill(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            threading.Timer(0.25, kill).start()
            return process
        runtime.subprocess.Popen = launch_and_kill
    outcomes=[]
    for _ in range(spec.get('repeat', 1)):
        event = threading.Event()
        timer = threading.Timer(0.25,event.set) if spec.get('cancel') else None
        if timer: timer.start()
        try:
            r = run(source, spec.get('inputs',{}), ['out'],
                    limits=Limits(execution_seconds=0.5, wall_seconds=spec.get('wall_seconds',5)), cancel=event)
        finally:
            if timer: timer.cancel()
        outcomes.append(r['outcome'])
        if r['outcome'] not in spec['expected']:
            return {'status':'FAIL','reason':'unexpected_outcome','outcomes':outcomes}
        if r['outcome']=='ok' and 'expected_value' in spec and r['values']['out'] != spec['expected_value']:
            return {'status':'FAIL','reason':'incorrect_value','outcomes':outcomes}
    if spec.get('crash'):
        runtime.subprocess.Popen = launch
    # Check recovery in the same owner after failure, timeout or Stop.
    recovery=run('def transform(inputs):\n    return {"out": 7}',{},['out'])
    if recovery.get('values') != {'out':7}:
        return {'status':'FAIL','reason':'recovery_failed','outcomes':outcomes}
    return {'status':'PASS','outcomes':outcomes}

if __name__=='__main__':
    try:
        result=main(json.loads(sys.stdin.read()))
    except ImportError:
        result={'status':'BLOCKED','reason':'dependency_unavailable'}
    except BaseException:
        result={'status':'FAIL','reason':'driver_exception'}
    print(json.dumps(result))
