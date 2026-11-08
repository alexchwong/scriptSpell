"""Trusted subprocess driver. Submitted source runs exclusively in Monty."""
import json
import ast
import sys
import sysconfig
import signal
from datetime import datetime, timezone
from pathlib import Path
from .codec import pack, unpack
from .profile import Limits
from .source import check
from ._guest import SUPPORT


def main():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit()))
    try:
        # Bound native stack/core/address space before parsing submitted source.
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    except (ImportError, ValueError, OSError):
        pass
    request = json.loads(sys.stdin.buffer.read(3 * 1048576))
    limits = Limits(**request['limits']).checked()
    issues = check(request['source'], limits)
    if issues:
        return dict(outcome='source_rejected', issues=issues, validation='static_only')
    if request['action'] == 'validate':
        return dict(outcome='ok', issues=[], validation='static_only')
    try:
        from pydantic_monty import Monty
    except ImportError:
        return dict(outcome='dependency_unavailable')
    binary = Path(sysconfig.get_path('scripts')) / 'monty'
    if not binary.is_file():
        # User-scheme installations are a standard installed location, never PATH.
        binary = Path(sysconfig.get_path('scripts', scheme='posix_user')) / 'monty'
    if not binary.is_file():
        return dict(outcome='dependency_unavailable')
    values = unpack(request['inputs'])
    with Monty(binary_path=binary, min_processes=1, max_processes=1,
               request_timeout=limits.wall_seconds, max_checkouts_per_worker=1) as pool:
        with pool.checkout(limits={'max_memory': limits.memory_bytes,
                                  'max_feed_duration_secs': limits.execution_seconds,
                                  'max_recursion_depth': 512, 'max_suspensions': 10,
                                  'max_total_sleep_secs': 0},
                           os_policy={'datetime': datetime(2000, 1, 1, tzinfo=timezone.utc),
                                      'timezone': 'utc', 'sleep': 'zero', 'process_time': 'zero',
                                      'random_start': {'seed': 0}}) as session:
            # AST wrapping isolates globals without adding whitespace inside multiline literals.
            wrapper=ast.parse('def _ss_invoke_user():\n    pass').body[0]
            wrapper.body=ast.parse(request['source']).body+[ast.parse('return transform(_ss_inputs)').body[0]]
            program=SUPPORT+'\n'+ast.unparse(ast.fix_missing_locations(wrapper))+'\n_ss_finish()'
            result = session.feed_run(program,
                inputs={'_ss_inputs': values, '_ss_outputs': request['outputs'],
                        '_ss_depth': limits.depth, '_ss_nodes': limits.nodes, '_ss_bytes': limits.value_bytes},
                print_callback=lambda stream, text: None)
    # Recheck the result after the strict guest export; never accept repr fallbacks.
    if result[0] != 'ok':
        return dict(outcome='invalid_result')
    values = unpack(result[1])
    return dict(outcome='ok', values=pack(values, limits))

if __name__ == '__main__':
    try:
        response = main()
    except BaseException as exc:
        # Classify only trusted runtime exception types; never expose guest messages.
        outcome = 'runtime_error'
        try:
            from pydantic_monty import MontyRuntimeError, MontyCrashedError
            if isinstance(exc, MontyCrashedError):
                outcome = 'deadline' if exc.timed_out else 'worker_crash'
            elif isinstance(exc, MontyRuntimeError):
                if isinstance(exc.exception(), (TimeoutError, MemoryError, RecursionError)):
                    outcome = 'limit_exceeded'
        except (ImportError, AttributeError):
            pass
        response = dict(outcome=outcome)
    sys.stdout.write(json.dumps(response, ensure_ascii=True))
