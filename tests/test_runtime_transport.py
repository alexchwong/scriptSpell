"""Transport regressions independent of Monty and CPython pipe capacity."""
import json
import subprocess
import sys
import threading

import pytest

from scriptspell import Limits, run
import scriptspell.runtime as runtime


@pytest.mark.parametrize('failure', ['transient', 'persistent', 'signal', 'unexpected', 'wait'])
def test_cleanup_permission_errors(monkeypatch, failure):
    retained = []
    monkeypatch.setattr(runtime, '_retained', retained)
    events = []
    class Stream:
        def close(self):
            assert 'join' in events
            events.append('close')
    class Process:
        pid = 12345
        stdin = stdout = Stream()
        def wait(self, timeout):
            events.append('wait')
            if failure == 'wait': raise OSError('unobservable')
    class Communication:
        ident = 1
        def join(self, timeout): events.append('join')
        def is_alive(self): return False
    probes = []
    def killpg(pid, sig):
        if sig:
            if failure == 'signal': raise PermissionError
            return
        probes.append(True)
        if failure == 'unexpected': raise OSError('unobservable')
        if failure == 'persistent' or (failure == 'transient' and len(probes) == 1):
            raise PermissionError
        raise ProcessLookupError
    ticks = iter(range(100))
    monkeypatch.setattr(runtime.os, 'killpg', killpg)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: next(ticks) / 10)
    if failure in ('persistent', 'unexpected', 'wait'):
        with pytest.raises(RuntimeError, match='cleanup_failed'):
            runtime._cleanup(Process(), Communication())
        assert retained and 'close' not in events
        assert runtime._invoke(dict(source=''))['outcome'] == 'cleanup_failed'
    else:
        runtime._cleanup(Process(), Communication())
        assert not retained and events == ['join', 'wait', 'close', 'close']


@pytest.mark.parametrize('failure', ['thread', 'group'])
def test_unconfirmed_cleanup_blocks_dispatch(monkeypatch, failure):
    retained = []
    monkeypatch.setattr(runtime, '_retained', retained)
    class Process:
        pid = 12345
        stdin = stdout = None
        returncode = 0
        def communicate(self, payload): return b'{"outcome":"ok"}', None
        def wait(self, timeout): return 0
    class Communication:
        ident = 1
        def __init__(self, target, **kwargs): self.target = target
        def start(self): self.target()
        def join(self, timeout): pass
        def is_alive(self): return failure == 'thread'
    launches = []
    def launch(*args, **kwargs):
        launches.append(True)
        return Process()
    def killpg(pid, sig):
        if failure != 'group': raise ProcessLookupError
    ticks = iter(range(100))
    monkeypatch.setattr(runtime.subprocess, 'Popen', launch)
    monkeypatch.setattr(runtime.threading, 'Thread', Communication)
    monkeypatch.setattr(runtime.os, 'killpg', killpg)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(RuntimeError, match='cleanup_failed'):
        runtime._invoke(dict(source=''))
    assert retained
    assert runtime._invoke(dict(source=''))['outcome'] == 'cleanup_failed'
    assert len(launches) == 1


@pytest.mark.parametrize('size,expression,expected', [
    (60000, 'inputs["x"]', 'x' * 60000),
    (200000, 'len(inputs["x"])', 200000),
])
def test_large_values(size, expression, expected):
    result = run('def transform(inputs):\n    return {"out": ' + expression + '}',
                 {'x': 'x' * size}, ['out'])
    assert result['outcome'] == 'ok', result
    assert result['values'] == {'out': expected}
    assert not any(t.name == 'scriptspell-communicate' for t in threading.enumerate())


@pytest.mark.parametrize('case', ['slow_read', 'cancel', 'deadline', 'crash'])
def test_transport_in_watchdog_process(case):
    # The outer timeout also catches lifecycle regressions in the test itself.
    program = r'''
import json, signal, subprocess, sys, threading, time
import scriptspell.runtime as runtime
from scriptspell import Limits
case = sys.argv[1]
launch = subprocess.Popen
children = []
calls = []
def child(*args, **kwargs):
    code = "import sys,time,json; time.sleep(.15); data=sys.stdin.buffer.read(); print(json.dumps({'outcome':'ok','length':len(data)}))"
    if case in ('cancel', 'deadline'):
        code = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    if case == 'crash': code = 'raise SystemExit(3)'
    proc = launch([sys.executable, '-c', code], **kwargs)
    original = proc.communicate
    def communicate(*a, **kw):
        calls.append((a, kw))
        return original(*a, **kw)
    proc.communicate = communicate
    children.append(proc)
    return proc
runtime.subprocess.Popen = child
event = threading.Event()
timer = threading.Timer(.2, event.set)
if case == 'cancel': timer.start()
try:
    request = dict(source='', padding='x' * 200000)
    result = runtime._invoke(request, Limits(wall_seconds=.4 if case == 'deadline' else 5), event)
finally:
    timer.cancel()
    if timer.ident is not None: timer.join()
assert result['outcome'] == dict(slow_read='ok',cancel='cancelled',deadline='deadline',crash='worker_crash')[case], result
assert len(calls) == 1 and calls[0][1] == {}, calls
if case == 'slow_read':
    expected = dict(request, limits=result['metadata']['limits'])
    assert result['length'] == len(json.dumps(expected, ensure_ascii=True).encode()), result
assert not any(t.name == 'scriptspell-communicate' for t in threading.enumerate())
assert all(p.poll() is not None for p in children)
assert not runtime._retained
'''
    result = subprocess.run([sys.executable, '-c', program, case],
                            capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stdout + result.stderr