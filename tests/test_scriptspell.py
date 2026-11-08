from decimal import Decimal, localcontext
import os
import signal
import subprocess
import sys
import threading
import time
import pytest
from scriptspell import Limits, profile, run, validate_source


def src(expr): return 'def transform(inputs):\n    return {"out": ' + expr + '}'

@pytest.mark.parametrize('value', [None, False, 0, '', 'é🙂', '<deeply nested>', '[...]', 2**80,
    Decimal('1.20'), Decimal('-0.00'), Decimal('1E-900'), {'a': [1, None, False]}])
def test_roundtrip(value):
    r = run(src('inputs["x"]'), {'x': value}, ['out'])
    assert r['outcome'] == 'ok', r
    assert r['values']['out'] == value
    if isinstance(value, Decimal): assert r['values']['out'].as_tuple() == value.as_tuple()

@pytest.mark.parametrize('expr', ['transform', '(1, 2)', 'range(3)', '{1: "x"}', 'Decimal("NaN")'])
def test_unsupported_results(expr):
    r = run('from decimal import Decimal\n' + src(expr), {}, ['out'])
    assert r['outcome'] != 'ok'
    assert 'values' not in r

@pytest.mark.parametrize('body', [
    'import os\ndef transform(inputs):\n    return {"out": os.getenv("SECRET")}',
    'def transform(inputs):\n    return {"out": open("/etc/passwd").read()}',
    'def transform(inputs):\n    return {"out": eval("1")}',
    'def transform(inputs):\n    return {"out": inputs.__class__}',
    'def transform(inputs):\n    return {"out": 0.1}',
    'def transform(inputs):\n    return {"out": 1 / 3}',
    'def transform(inputs):\n    print(inputs)\n    return {"out": 1}',
    'def transform(inputs):\n    _ss_inputs = 1\n    return {"out": 1}',
    'def transform(inputs):\n    len = 1\n    return {"out": 1}',
    'def transform(inputs=print("leak")):\n    return {"out": 1}',
    'raise ValueError("leak")\ndef transform(inputs):\n    return {"out": 1}',
    '@str\ndef transform(inputs):\n    return {"out": 1}',
])
def test_source_denial(body):
    assert validate_source(body)['outcome'] == 'source_rejected'
    assert run(body, {}, ['out'])['outcome'] == 'source_rejected'

def test_validation_does_not_execute():
    code = 'def transform(inputs):\n    while True:\n        pass'
    assert validate_source(code)['outcome'] == 'ok'

def test_cycles_and_depth():
    code = 'def transform(inputs):\n    a = []\n    a.append(a)\n    return {"out": a}'
    assert run(code, {}, ['out'])['outcome'] != 'ok'
    a = []; a.append(a)
    assert run(src('inputs'), {'x': a}, ['out'])['outcome'] == 'invalid_inputs'
    code = 'def transform(inputs):\n    a = []\n    for i in range(40):\n        a = [a]\n    return {"out": a}'
    assert run(code, {}, ['out'])['outcome'] != 'ok'

def test_decimal_threshold_and_rounding():
    code = 'from decimal import Decimal\n' + src('inputs["vaf"] >= Decimal("0.05")')
    assert run(code, {'vaf': Decimal('0.049999999999999999999')}, ['out'])['values'] == {'out': False}
    code = 'from decimal import Decimal\n' + src('inputs["vaf"] + Decimal("0.1")')
    assert run(code, {'vaf': Decimal('1' * 129)}, ['out'])['outcome'] != 'ok'
    with localcontext() as ctx:
        ctx.prec = 7
        run(src('1'), {}, ['out'])
        assert ctx.prec == 7

def test_no_partial_outputs():
    assert run(src('1'), {}, ['other'])['outcome'] != 'ok'
    assert run('def transform(inputs):\n    return {"out": 1, "extra": 2}', {}, ['out'])['outcome'] != 'ok'

def test_input_immutability_and_freshness():
    data = {'x': [1]}
    code = 'def transform(inputs):\n    inputs["x"].append(2)\n    return {"out": inputs["x"]}'
    assert run(code, data, ['out'])['values'] == {'out': [1, 2]}
    assert data == {'x': [1]}
    assert run(src('inputs["x"]'), data, ['out'])['values'] == {'out': [1]}

@pytest.mark.parametrize('value', [1.2, float('nan'), Decimal('Infinity'), object(), {1: 2}])
def test_invalid_inputs(value):
    assert run(src('1'), {'x': value}, ['out'])['outcome'] == 'invalid_inputs'

@pytest.mark.parametrize('code', [
    'def transform(inputs):\n    while True:\n        pass',
    'def transform(inputs):\n    a = "x" * 1000000000\n    return {"out": a}',
    'def transform(inputs):\n    return transform(inputs)',
])
def test_runtime_limits(code):
    start = time.monotonic()
    assert run(code, {}, ['out'], limits=Limits(execution_seconds=0.1))['outcome'] != 'ok'
    assert time.monotonic() - start < 7
    assert run(src('1'), {}, ['out'])['outcome'] == 'ok'

def test_stop_and_deadline():
    code = 'def transform(inputs):\n    while True:\n        pass'
    event = threading.Event()
    timer = threading.Timer(0.2, event.set)
    timer.start()
    try:
        assert run(code, {}, ['out'], cancel=event)['outcome'] == 'cancelled'
    finally: timer.cancel()
    assert run(code, {}, ['out'], limits=Limits(wall_seconds=0.2))['outcome'] == 'deadline'
    event.set()
    assert run(src('1'), {}, ['out'], cancel=event)['outcome'] == 'cancelled'

@pytest.mark.parametrize('limits', [Limits(depth=0), Limits(wall_seconds=float('nan')), Limits(nodes=True)])
def test_bad_limits(limits):
    with pytest.raises(ValueError): run(src('1'), {}, ['out'], limits=limits)

@pytest.mark.parametrize('expr,inputs,expected', [
    ('[x.strip() for x in inputs["x"] if x.strip()]', {'x': [' a ', '', ' b']}, ['a', 'b']),
    ('sorted(inputs["x"])', {'x': [3, 1, 2]}, [1, 2, 3]),
    ('sum(inputs["x"])', {'x': [2, 3]}, 5),
    ('inputs["x"].get("missing")', {'x': {}}, None),
])
def test_independent_expected_cases(expr, inputs, expected):
    assert run(src(expr), inputs, ['out'])['values'] == {'out': expected}

def test_raw_runtime_denies_host_access(tmp_path):
    # Independently probe the runtime configuration, bypassing only the AST filter
    # inside this test; no production bypass exists.
    from pydantic_monty import Monty
    from importlib.metadata import distribution
    binary = next(distribution('pydantic-monty-runtime').locate_file(p) for p in distribution('pydantic-monty-runtime').files if str(p).endswith('/monty'))
    secret = tmp_path / 'secret.txt'
    secret.write_text('SYNTHETIC_PRIVATE_VALUE')
    with Monty(binary_path=binary, max_processes=1, request_timeout=2) as pool:
        for code in [f'open({str(secret)!r}).read()', 'import os\nos.getenv("HOME")',
                     'import socket\nsocket.socket()', 'import subprocess\nsubprocess.run(["true"])']:
            with pool.checkout(limits={'max_memory': 67108864, 'max_feed_duration_secs': 0.1}) as session:
                with pytest.raises(Exception):
                    session.feed_run(code, print_callback=lambda *_: None)
    assert secret.read_text() == 'SYNTHETIC_PRIVATE_VALUE'


def test_real_helper_crash(monkeypatch):
    import scriptspell.runtime as runtime
    launch = runtime.subprocess.Popen
    timers = []
    def launch_and_kill(*args, **kwargs):
        process = launch(*args, **kwargs)
        def kill():
            try: os.kill(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        timer = threading.Timer(0.2, kill)
        timers.append(timer)
        timer.start()
        return process
    monkeypatch.setattr(runtime.subprocess, 'Popen', launch_and_kill)
    try:
        result = run('def transform(inputs):\n    while True:\n        pass', {}, ['out'])
        assert result['outcome'] == 'worker_crash'
    finally:
        for timer in timers: timer.cancel()
