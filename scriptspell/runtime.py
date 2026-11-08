"""Finite local invocation; no submitted source is evaluated by host Python."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from .codec import pack, unpack
from .profile import Limits, profile


_retained = []  # An unconfirmed cleanup blocks further dispatch in this process.


def _cancelled(cancel):
    return cancel is not None and cancel.is_set()


def _invoke(request, limits=None, cancel=None, started=None):
    started = time.monotonic() if started is None else started
    limits = (limits or Limits()).checked()
    metadata = profile()
    def done(outcome, **extra):
        return dict(outcome=outcome, elapsed=time.monotonic() - started, **extra,
                    metadata=metadata)
    if _retained: return done('cleanup_failed')
    if _cancelled(cancel): return done('cancelled')
    if sys.platform not in ('linux', 'darwin'): return done('platform_unavailable')
    source = request.get('source')
    if type(source) is not str:
        return done('source_rejected', issues=[{'code': 'source_limit', 'line': None}])
    try: source_bytes=source.encode('utf-8')
    except UnicodeEncodeError:
        return done('source_rejected', issues=[{'code':'source_encoding','line':None}])
    if len(source_bytes)>limits.source_bytes:
        return done('source_rejected', issues=[{'code': 'source_limit', 'line': None}])
    metadata['source_digest'] = hashlib.sha256(source_bytes).hexdigest()
    metadata['limits'] = asdict(limits)
    request = dict(request, limits=asdict(limits))
    payload = json.dumps(request, ensure_ascii=True).encode()
    root = str(Path(__file__).resolve().parent.parent)
    bootstrap = 'import sys,runpy;sys.path.insert(0,sys.argv[1]);runpy.run_module("scriptspell._worker",run_name="__main__")'
    env = {k: v for k, v in os.environ.items() if k in ('SYSTEMROOT', 'WINDIR', 'LANG')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    process = subprocess.Popen([sys.executable, '-c', bootstrap, root], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd='/', env=env, start_new_session=True)
    reason = None
    completed = threading.Event()
    result = {}
    def communicate():
        try:
            result['output'], _ = process.communicate(payload)
        except BaseException as exc:
            result['error'] = exc
        finally:
            completed.set()
    # One owner for all pipe I/O. Retrying timed communicate() can lose stdin
    # progress on older CPython versions (python/cpython#141473).
    communication = threading.Thread(target=communicate, name='scriptspell-communicate', daemon=True)
    try:
        communication.start()
        while True:
            if _cancelled(cancel): reason = 'cancelled'; break
            remaining = limits.wall_seconds - (time.monotonic() - started)
            if remaining <= 0: reason = 'deadline'; break
            if completed.wait(min(0.02, remaining)): break
        if reason:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            completed.wait(1)
            return done(reason)
        if 'error' in result: return done('worker_crash')
        output = result['output']
        if process.returncode != 0: return done('worker_crash')
        if len(output) > limits.value_bytes + 65536: return done('invalid_result')
        response = json.loads(output)
        if response.get('outcome') == 'ok' and 'values' in response:
            values = unpack(response.pop('values'))
            pack(values, limits)
            response['values'] = values
        return done(**response)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return done('worker_crash')
    finally:
        # The helper closes Monty's pool before responding, including on SIGTERM.
        # Last-resort process-group kill also covers a crashed helper's descendants.
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        # Never close buffered streams underneath their communication owner.
        if communication.ident is not None:
            communication.join(timeout=1)
        if communication.is_alive():
            _retained.append((process, communication))
            raise RuntimeError('cleanup_failed')
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            _retained.append(process)
            raise RuntimeError('cleanup_failed') from None
        cleanup_deadline = time.monotonic() + 1
        while True:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            if time.monotonic() >= cleanup_deadline:
                _retained.append(process)
                raise RuntimeError('cleanup_failed')
            time.sleep(0.01)
        for stream in (process.stdin, process.stdout):
            if stream: stream.close()


def run(source, inputs, output_names, *, limits=None, cancel=None):
    started = time.monotonic()
    limits = (limits or Limits()).checked()
    if _cancelled(cancel): return {'outcome': 'cancelled'}
    if type(inputs) is not dict or type(output_names) not in (list, tuple) or not output_names:
        return {'outcome': 'invalid_inputs'}
    if len(output_names) > 100 or any(type(x) is not str or not x or len(x) > 128 for x in output_names) or len(set(output_names)) != len(output_names):
        return {'outcome': 'invalid_inputs'}
    try: encoded = pack(inputs, limits)
    except (ValueError, TypeError, RecursionError): return {'outcome': 'invalid_inputs'}
    return _invoke(dict(action='run', source=source, inputs=encoded, outputs=list(output_names)), limits, cancel, started)
