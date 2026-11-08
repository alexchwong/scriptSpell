"""Test-only subprocess monitor shared by the two feasibility commands."""
import json
import os
import uuid
import platform
import subprocess
import sys
import time
from pathlib import Path


def blocked_case(name, reason):
    return dict(name=name, status='BLOCKED', reason=reason, samples=0,
                observed_monty_worker=False, survivors=[], elapsed_seconds=0,
                sampled_peak_tree_mib=None, sampled_peak_caller_mib=None,
                sampled_peak_workers_mib=None, sampled_peak_single_process_mib=None)


def _pid_namespace_visible():
    if sys.platform!='linux':return True
    try:
        return int(Path('/proc/self/stat').read_text().split(' ',1)[0])==os.getpid()
    except (OSError,ValueError):
        return False


IDENTITY_SECONDS = 2.0


def _wait_for_identity(proc, script, token, seconds=IDENTITY_SECONDS):
    """Require the launched child's own argv before trusting its PID.

    Popen returns once the child is forked, but /proc/<pid>/cmdline keeps showing
    the parent image until the child execs. A single sample can lose that window
    and report a live child as unobservable. Sample until the exact script path and
    the per-launch token appear in argv, the child exits, or the deadline passes.

    The requirement is unchanged: argv that never matches is still refused, so a
    similarly named process is never trusted, inspected or signalled.
    """
    import psutil
    deadline = time.monotonic() + seconds
    while True:
        try:
            command = psutil.Process(proc.pid).cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        if str(script) in command and token in command:
            return True
        if proc.poll() is not None or time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def run_case(spec, *, tree_mib=512, process_mib=256, timeout=12):
    import psutil
    if not _pid_namespace_visible():
        return blocked_case(spec['name'],'process_namespace_not_observable')
    token=uuid.uuid4().hex
    script = Path(__file__).with_name('_feasibility_case.py')
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, str(script), token], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    # Verify PID visibility before sending any fixture or inspecting descendants.
    # Some containers expose host /proc with namespace-local subprocess IDs.
    if not _wait_for_identity(proc, script, token):
        proc.terminate()
        try: proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate(timeout=2)
        return dict(name=spec['name'], status='BLOCKED', reason='process_identity_not_observable',
                    elapsed_seconds=round(time.monotonic()-started, 3), samples=0,
                    observed_monty_worker=False, survivors=[], sampled_peak_tree_mib=None,
                    sampled_peak_caller_mib=None, sampled_peak_workers_mib=None,
                    sampled_peak_single_process_mib=None)
    proc.stdin.write(json.dumps(spec).encode()); proc.stdin.close(); proc.stdin = None
    known = {}
    peak_tree = peak_process = peak_caller = peak_workers = 0
    samples = 0
    observed_worker = False
    reason = None
    monitoring_blocked = False
    while proc.poll() is None:
        try:
            root = psutil.Process(proc.pid)
            for p in [root, *root.children(recursive=True)]:
                known[(p.pid, p.create_time())] = p
            total = workers = 0
            for p in list(known.values()):
                try:
                    if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE: continue
                    rss = p.memory_info().rss
                    total += rss
                    peak_process = max(peak_process, rss)
                    if p.pid == proc.pid: peak_caller = max(peak_caller, rss)
                    else: workers += rss
                    if p.name().startswith('monty'): observed_worker = True
                except psutil.NoSuchProcess: pass
                except psutil.AccessDenied: monitoring_blocked = True
            peak_tree = max(peak_tree, total)
            peak_workers = max(peak_workers, workers)
            samples += 1
            if total > tree_mib * 1024**2 or peak_process > process_mib * 1024**2:
                reason = 'sampled_memory_threshold_exceeded'; break
        except psutil.NoSuchProcess: pass
        except psutil.AccessDenied: monitoring_blocked = True
        if time.monotonic() - started > timeout:
            reason = 'outer_timeout'; break
        time.sleep(0.005)
    # Always clean up known descendants, including after a crashed case driver.
    # Process objects retain creation identity, preventing PID-reuse kills.
    cleanup = []
    for p in reversed(list(known.values())):
        try:
            if p.is_running():
                if p.status() != psutil.STATUS_ZOMBIE:
                    cleanup.append(p.pid)
                p.kill()
        except psutil.NoSuchProcess: pass
        except psutil.AccessDenied: monitoring_blocked = True
    try: output, errors = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill(); output, errors = proc.communicate(timeout=2)
        reason = reason or 'cleanup_timeout'
    _, alive = psutil.wait_procs(list(known.values()), timeout=2)
    survivors = [p.pid for p in alive if p.is_running()]
    if survivors or cleanup:
        reason = reason or 'surviving_processes'
    try:
        result = json.loads(output)
    except (ValueError, UnicodeError):
        result = {'status': 'FAIL', 'reason': 'case_crashed'}
    if reason: result = {'status': 'FAIL', 'reason': reason}
    elif monitoring_blocked or not samples: result = {'status': 'BLOCKED', 'reason': 'process_monitor_unavailable'}
    result.update(name=spec['name'], elapsed_seconds=round(time.monotonic()-started, 3),
                  sampled_peak_tree_mib=round(peak_tree/1024**2, 2),
                  sampled_peak_caller_mib=round(peak_caller/1024**2, 2),
                  sampled_peak_workers_mib=round(peak_workers/1024**2, 2),
                  sampled_peak_single_process_mib=round(peak_process/1024**2, 2),
                  samples=samples, observed_monty_worker=observed_worker,
                  survivors=survivors)
    return result


def report(kind, cases, path, thresholds=None):
    status = 'FAIL' if any(c['status']=='FAIL' for c in cases) else ('BLOCKED' if any(c['status']=='BLOCKED' for c in cases) else 'PASS')
    from scriptspell import profile
    result = dict(check=kind, status=status, runtime_profile=profile(), platform=platform.platform(),
                  architecture=platform.machine(), python=platform.python_version(),
                  thresholds=thresholds, cases=cases,
                  limitation='Sampled case-process RSS excludes the monitor, may miss brief peaks and double-count shared pages. PASS covers these fixtures only, not formal confinement or hard RSS enforcement.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2)+'\n')
    for c in cases:
        print(f"{c['status']:7} {c['name']}: {c.get('reason', c.get('outcomes', ''))} (tree peak {c['sampled_peak_tree_mib']} MiB)")
    print(f'{status}: {path}')
    return 0 if status=='PASS' else (1 if status=='FAIL' else 2)
