"""Report storage and diagnostics for the staged benchmark CLI."""
import hashlib
import json
import os
import subprocess
from collections import Counter
from itertools import islice
from pathlib import Path
from tempfile import NamedTemporaryFile

from scriptspell import AuthoringError
from scriptspell.workflow import parse_json, same_value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def digest_json(value):
    return digest(json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False).encode())


def package_source_digest(package):
    """Fingerprint the imported package, including same-version wheel changes."""
    root = Path(package.__file__).resolve().parent

    def fail(error):
        raise error

    hashes = {}
    for directory, _, names in os.walk(root, onerror=fail):
        for name in names:
            if name.endswith('.py'):
                path = Path(directory, name)
                hashes[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return digest_json(hashes)


def source_identity(root):
    """Identify the commit and all relevant working files, including untracked code."""
    paths = ('scriptspell', 'scripts', 'ui', 'pyproject.toml')
    try:
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)

        head = git('rev-parse', 'HEAD').decode().strip()
        dirty = bool(git('status', '--porcelain', '-z', '--untracked-files=all', '--', *paths))
        files = git('ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', *paths)
        hashes = {}
        for raw in sorted(set(files.split(b'\0')) - {b''}):
            name = os.fsdecode(raw)
            path = root / name
            if path.is_file():
                hashes[name] = digest(path.read_bytes())
            elif path.is_symlink():
                return None
        return {'commit': head, 'dirty': dirty, 'working_files_sha256': digest_json(hashes)}
    except (OSError, subprocess.CalledProcessError):
        return None


def atomic_report(path, report, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(report, output, indent=2, allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def yaml_counts(results):
    attempted = [item for item in results if 'examples_valid' in item]
    counts = {'attempted': len(attempted)}
    for prefix, field in (('first_pass', 'examples_first_pass'), ('final_pass', 'examples_valid')):
        evaluated = [item[field] for item in attempted if item.get(field) is not None]
        passed = sum(evaluated)
        counts.update({prefix: passed, f'{prefix}_evaluated': len(evaluated),
                       f'{prefix}_unevaluated': len(attempted) - len(evaluated),
                       f'{prefix}_rate': passed / len(evaluated) if evaluated else None})
    return counts


def summarize(results):
    reasons = Counter(item['reason'] for item in results if item.get('reason'))
    repairs = [attempt for item in results for attempt in item.get('attempts', []) if attempt.get('repair') or 'repair_echo' in attempt]
    agreement = [item for item in results if item.get('executed') and item.get('examples')]
    agreed = sum(item.get('agreement_status', item['status']) == 'PASS' for item in agreement)
    fixed = [item.get('verified', {}) for item in results]
    fixed_statuses = Counter(item.get('status', 'UNVERIFIED') for item in fixed)
    checked = fixed_statuses['PASS'] + fixed_statuses['FAIL']
    reference = {}
    for side in ('generated_expectation', 'python_actual'):
        cases = [case for result in results for case in result.get('reference', {}).get('cases', [])]
        reference[side] = {
            label: {'eligible': sum(case['eligible'] for case in group),
                    'passed': sum(case.get(side) == 'PASS' for case in group),
                    'failed': sum(case.get(side) == 'FAIL' for case in group)}
            for label, group in (
                ('all', cases), ('visible', [case for case in cases if case['visible']]),
                ('held_back', [case for case in cases if not case['visible']]))
        }
    return dict(reasons=dict(reasons),
                retries=dict(total=len(repairs), echoed=sum(attempt.get('repair_echo') is True for attempt in repairs)),
                agreement=dict(executed=len(agreement), passed=agreed, rate=agreed / len(agreement) if agreement else None),
                verified=dict(checked=checked, passed=fixed_statuses['PASS'],
                              rate=fixed_statuses['PASS'] / checked if checked else None,
                              cases=sum(item.get('total', 0) for item in fixed),
                              cases_passed=sum(item.get('passed', 0) for item in fixed),
                              statuses=dict(fixed_statuses)),
                reference=reference)


_MISSING = object()


def _differences(expected, actual, path='$'):
    if same_value(expected, actual):
        return
    if type(expected) is dict and type(actual) is dict and '$decimal' not in expected:
        for name in dict.fromkeys((*expected, *actual)):
            suffix = f'.{name}' if name.isidentifier() else f'[{json.dumps(name)}]'
            yield from _differences(expected.get(name, _MISSING), actual.get(name, _MISSING), path + suffix)
    elif type(expected) is list and type(actual) is list:
        for index in range(max(len(expected), len(actual))):
            yield from _differences(expected[index] if index < len(expected) else _MISSING,
                                    actual[index] if index < len(actual) else _MISSING, f'{path}[{index}]')
    else:
        yield path, expected, actual


def _short(value, cap=140):
    if value is _MISSING:
        return '<missing>'
    shown = json.dumps(value, ensure_ascii=True)
    return shown if len(shown) <= cap else shown[:cap] + '… [truncated]'


def _print_differences(expected_json, actual_json, prefix):
    if expected_json is None or actual_json is None:
        return
    try:
        expected, actual = (parse_json(text, max_chars=2_097_152) for text in (expected_json, actual_json))
    except AuthoringError:
        return
    for path, wanted, observed in islice(_differences(expected, actual), 3):
        print(f'    {prefix} {path} expected {_short(wanted)}, actual {_short(observed)}')


def print_task(item):
    print(f"{item['status']} {item['task']} {item['title']} [{item['difficulty']}]", flush=True)
    attempts = item.get('attempts', [])
    if 'examples_valid' in item:
        state = {True: 'PASS', False: 'FAIL', None: 'NOT_RUN'}
        print(f"  YAML first pass {state[item.get('examples_first_pass')]} · final {state[item['examples_valid']]}")
    for attempt in attempts:
        stage = attempt['stage']
        validation = attempt.get('validation', {})
        if attempt.get('repair') or 'repair_echo' in attempt:
            print(f"  {stage} correction {validation.get('outcome', 'NOT_RUN')}")
        if validation and validation['outcome'] != 'ok':
            print(f"  {stage} {validation['outcome']}")
            for name, value in validation.items():
                if name == 'outcome':
                    continue
                for detail in value if name == 'issues' and isinstance(value, list) else (value,):
                    print(f'    {name} {_short(detail, 300)}')
        error = attempt.get('provider_error')
        if error:
            fields = (error.get(name) for name in ('type', 'http_status', 'provider_name', 'limit_source'))
            print(f"  {stage} blocked · " + ' · '.join(str(value) for value in fields if value is not None))
            if error.get('http_status') == 429:
                print('    HTTP retry disabled')
    source_failure = any(
        attempt['stage'] == 'python' and attempt.get('validation', {}).get('outcome') not in (None, 'ok', 'incomplete_model_response')
        or attempt['stage'] == 'one-shot' and attempt.get('validation', {}).get('outcome') == 'source_rejected'
        for attempt in attempts
    )
    if source_failure and not item.get('valid_draft'):
        source = 'FAIL'
    else:
        source = 'PASS' if item.get('valid_draft') else 'NOT_RUN'
    cases = item.get('examples', [])
    execution = f"{sum('actual_json' in case for case in cases)}/{len(cases)} returned a result" if cases else 'NOT_RUN'
    print(f'  Python source {source} · Monty {execution}')
    agreement = item.get('agreement_status', item['status']) if cases else 'NOT_RUN'
    fixed = item.get('verified', {})
    print(f"  agreement {agreement} · fixed verification {fixed.get('status', 'UNVERIFIED')}")
    for index, case in enumerate(fixed.get('cases', []), 1):
        print(f"  fixed case {case.get('case_id', index)} · {case['status']} ({case['outcome']})")
        if case['status'] != 'pass':
            _print_differences(case.get('expected_json'), case.get('actual_json'), 'fixed')
    reference = item.get('reference', {})
    if reference:
        for side, label in (('generated_expectation', 'generated expectations'), ('python_actual', 'Python results')):
            value = reference[side]
            print(f"  reference {label} {value['status']} · {value['checked']}/{value['eligible']} eligible checked")
    by_id = {case.get('case_id', str(index)): case for index, case in enumerate(cases, 1)}
    checks = {case['case_id']: case for case in reference.get('cases', [])}
    for case_id in dict.fromkeys((*by_id, *checks)):
        case, check = by_id.get(case_id, {}), checks.get(case_id)
        visibility = 'visible' if (check or case).get('visible') else 'held back'
        message = f"  case {case_id} ({visibility}) · agreement {case.get('status', 'NOT_RUN')}"
        if case.get('outcome') not in (None, 'ok'):
            message += f" ({case['outcome']})"
        if check:
            message += (f" · reference expectation {check['generated_expectation']} / Python {check['python_actual']}"
                        if check['eligible'] else f" · unscored: {check['reason']}")
        print(message)
        if case.get('status') == 'mismatch':
            _print_differences(case.get('expected_json'), case.get('actual_json'), 'agreement')
        if check and check['eligible']:
            if check['generated_expectation'] == 'FAIL':
                _print_differences(check['reference_json'], case.get('expected_json', check.get('expected_json')), 'expectation')
            if check['python_actual'] == 'FAIL':
                _print_differences(check['reference_json'], case.get('actual_json'), 'Python')
    if item.get('reason'):
        print(f"  {item.get('failed_stage', 'task')} · {item['reason']}")


def print_summary(report, path, jobs):
    counts = Counter(item['status'] for item in report['results'])
    completed = {(item['task'], item['difficulty']) for item in report['results']}
    missing = [f'{task}/{level}' for task, _, level, _ in jobs if (task, level) not in completed]
    print(f"{report['status']} · {counts['PASS']} pass · {counts['FAIL']} fail · {counts['BLOCKED']} blocked "
          f"· {len(missing)} unattempted / {len(jobs)} requested · {path}")
    if missing:
        print('  unattempted ' + ', '.join(missing))
    summary = report['summary']
    if 'examples_validation' in report:
        yaml = report['examples_validation']
        print(f"  YAML first pass {yaml['first_pass']}/{yaml['first_pass_evaluated']} "
              f"({yaml['first_pass_unevaluated']} unevaluated) · final {yaml['final_pass']}/{yaml['final_pass_evaluated']} "
              f"({yaml['final_pass_unevaluated']} unevaluated)")
    fixed = summary['verified']
    agreement = summary['agreement']
    print(f"  agreement {agreement['passed']}/{agreement['executed']} · fixed verification "
          f"{fixed['passed']}/{fixed['checked']} tasks passed")
    for side, label in (('generated_expectation', 'generated expectations'), ('python_actual', 'Python results')):
        groups = summary['reference'][side]
        overall = groups['all']
        print(f"  reference {label} {overall['passed']} pass / {overall['failed']} fail / "
              f"{overall['eligible']} eligible · visible {groups['visible']['passed']} pass / "
              f"{groups['visible']['failed']} fail / {groups['visible']['eligible']} eligible "
              f"· held back {groups['held_back']['passed']} pass / {groups['held_back']['failed']} fail / "
              f"{groups['held_back']['eligible']} eligible")
    repairs = summary['retries']
    print(f"  YAML corrections {repairs['total']} · exact echoes {repairs['echoed']}")
    print(f"  {report['request_count']} logical calls ({report['invocation_request_count']} this invocation) "
          f"· HTTP attempts unknown (at most {report['http_attempt_max']}) · HTTP retries disabled")
