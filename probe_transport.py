"""Investigation probe: cost of moving values into and out of the pinned runtime.

Repository tooling, never imported by the product and never part of the wheel.
It measures each stage separately so a slow platform can be attributed to value
conversion rather than to interpreter startup, process monitoring or the codec.

Emits one JSON object per measurement on stdout.

    python probe_transport.py --mode direct --sizes 1000,10000,60000 --rounds 3
    python probe_transport.py --mode codec,adapter,scriptspell --sizes 60000
"""
import argparse
import json
import platform
import statistics
import sys
import sysconfig
import time
from pathlib import Path


def _monty_binary():
    for scheme in (None, 'posix_user'):
        directory = (sysconfig.get_path('scripts') if scheme is None
                     else sysconfig.get_path('scripts', scheme=scheme))
        candidate = Path(directory) / 'monty'
        if candidate.is_file():
            return candidate
    return None


def _versions():
    from importlib.metadata import PackageNotFoundError, version
    out = {}
    for name in ('pydantic-monty', 'pydantic-monty-client', 'pydantic-monty-runtime'):
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def fingerprint():
    import pydantic_monty
    binary = _monty_binary()
    extension = Path(pydantic_monty._monty.__file__)
    return dict(platform=platform.platform(), machine=platform.machine(),
                python=platform.python_version(), versions=_versions(),
                monty_binary=None if binary is None else str(binary),
                monty_binary_bytes=None if binary is None else binary.stat().st_size,
                extension=extension.name, extension_bytes=extension.stat().st_size)


def emit(**record):
    sys.stdout.write(json.dumps(record, sort_keys=True) + '\n')
    sys.stdout.flush()


def timeit(call, rounds):
    times = []
    for _ in range(rounds):
        started = time.perf_counter()
        call()
        times.append(time.perf_counter() - started)
    return dict(seconds_min=min(times), seconds_median=statistics.median(times),
                rounds=len(times))


# Each cell names what crosses the boundary. `fixed` is the baseline every other
# cell is compared against; it moves one character each way and does no work.
def cells(size):
    big = bool(size > 1)
    return [
        ('fixed', 'len("a")', not big),
        ('in_raw', 'len(_x)', big),
        ('out_raw', '"x" * _n', not big),
        ('in_tagged', '["o", [[["s", "out"], ["s", "tiny"]]]]', big),
        ('out_tagged', '["o", [[["s", "out"], ["s", "x" * _n]]]]', not big),
        ('roundtrip_tagged', '["o", [[["s", "out"], ["s", _x]]]]', big),
    ]


def measure_direct(size, rounds, timeout):
    from pydantic_monty import Monty
    binary = _monty_binary()
    if binary is None:
        emit(mode='direct', cell='all', size=size, error='monty_binary_missing')
        return
    guest_limits = {'max_memory': 64 * 1024 ** 2, 'max_feed_duration_secs': timeout,
                    'max_recursion_depth': 512, 'max_suspensions': 10,
                    'max_total_sleep_secs': 0}
    def padding(stream, text): return None
    with Monty(binary_path=binary, min_processes=1, max_processes=1,
               request_timeout=timeout + 30, max_checkouts_per_worker=64) as pool:
        for name, program, big_in in cells(size):
            inputs = {'_x': 'x' * size if big_in else 'x', '_n': size}
            try:
                with pool.checkout(limits=guest_limits) as session:
                    # One untimed call moves worker start-up out of the measurement.
                    session.feed_run(program, inputs=inputs, print_callback=padding)
                    stats = timeit(lambda: session.feed_run(
                        program, inputs=inputs, print_callback=padding), rounds)
                emit(mode='direct', cell=name, size=size,
                     bytes_in=len(inputs['_x']), **stats)
            except BaseException as exc:
                emit(mode='direct', cell=name, size=size, error=type(exc).__name__)


def measure_codec(size, rounds):
    from scriptspell.codec import pack, unpack
    from scriptspell.profile import Limits
    limits = Limits()
    value = {'x': 'x' * size}
    tagged = pack(value, limits)
    payload = json.dumps({'inputs': tagged}, ensure_ascii=True).encode()
    calls = {
        'pack': lambda: pack(value, limits),
        'json_encode': lambda: json.dumps({'inputs': tagged}, ensure_ascii=True).encode(),
        'json_decode': lambda: json.loads(payload)['inputs'],
        'unpack': lambda: unpack(tagged),
    }
    for name, call in calls.items():
        emit(mode='codec', cell=name, size=size, payload_bytes=len(payload),
             **timeit(call, rounds))


def measure_adapter(size, rounds):
    """The product's own stages, with no runtime and no subprocess."""
    from scriptspell.codec import pack, unpack
    from scriptspell.profile import Limits
    limits = Limits()
    value = {'x': 'x' * size}

    def once():
        tagged = pack(value, limits)
        encoded = json.dumps({'inputs': tagged}, ensure_ascii=True).encode()
        decoded = json.loads(encoded)['inputs']
        return json.dumps({'values': pack(unpack(decoded), limits)},
                          ensure_ascii=True).encode()

    emit(mode='adapter', cell='codec_roundtrip', size=size, **timeit(once, rounds))


def measure_scriptspell(size, rounds):
    from scriptspell import run
    source = 'def transform(inputs):\n    return {"out": inputs["x"]}'
    inputs = {'x': 'x' * size}
    outcomes = []
    started = time.perf_counter()
    for _ in range(rounds):
        outcomes.append(run(source, inputs, ['out'])['outcome'])
    emit(mode='scriptspell', cell='product_roundtrip', size=size, outcomes=outcomes,
         seconds_median=(time.perf_counter() - started) / rounds)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Measure host/guest value transport cost.')
    parser.add_argument('--mode', default='direct',
                        help='comma list of codec,adapter,direct,scriptspell')
    parser.add_argument('--sizes', default='1000,10000,60000')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=30.0,
                        help='per-call guest budget in seconds; not the product limit')
    args = parser.parse_args(argv)
    modes = [m.strip() for m in args.mode.split(',') if m.strip()]
    sizes = [int(s) for s in args.sizes.split(',') if s.strip()]
    emit(mode='fingerprint', **fingerprint())
    for size in sizes:
        for mode in modes:
            if mode == 'direct':
                measure_direct(size, args.rounds, args.timeout)
            elif mode == 'codec':
                measure_codec(size, args.rounds)
            elif mode == 'adapter':
                measure_adapter(size, args.rounds)
            elif mode == 'scriptspell':
                measure_scriptspell(size, args.rounds)
            else:
                raise SystemExit(f'unknown mode {mode}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
