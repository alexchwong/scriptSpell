"""Benchmark the YAML and legacy JSON authoring modes on the playground presets."""
import argparse
import json
import os
from importlib.metadata import version
from pathlib import Path
from time import monotonic, sleep

import modelspell

from scriptspell import AuthoringError, YamlAuthoring, run_examples
from scriptspell.prompt_files import load_preset_contracts
from scriptspell.staged import StagedAuthoring, _interface, _MAX_REPLY
from scriptspell.yaml_contract import validate_interface
from scriptspell.workflow import parse_json
from scripts.check_authoring_presets import BLOCKED_OUTCOMES, DEFAULT_MODEL, bind_openrouter, cli_settings
from scripts.staged_report import (atomic_report, digest, digest_json, package_source_digest,
                                   print_summary, print_task, source_identity, summarize, yaml_counts)
from scripts.staged_verification import case_report, fixed_verification, reference_verification
from ui.presets import DEFAULT_DIFFICULTY, DIFFICULTIES, PRESETS
from ui.model_errors import provider_error, redact

ROOT = Path(__file__).resolve().parents[1]
TRANSIENT_PAUSE_SECONDS = 2


def load_interface(path):
    return _interface(parse_json(path.read_text(encoding='utf-8')))


def _accepted_examples(attempts):
    for attempt in reversed(attempts):
        if attempt['stage'] == 'examples' and attempt.get('validation', {}).get('outcome') == 'ok':
            return attempt['response']['text']
    raise ValueError('accepted examples reply is absent from attempt history')


def evaluate(send, settings, instruction, example_count, *, interface=None, mode="legacy-json",
             examples_only=False, records=None, guidance=None, task=None, checkpoint=None, on_checkpoint=None):
    attempts = []
    result = {'attempts': attempts, 'valid_draft': False, 'executed': False}
    examples = []
    executions = []
    stage = 'interface'
    rejected_reply = None

    def record_request(materials, model_settings):
        nonlocal rejected_reply
        attempt = dict(stage=stage, request=materials)
        if rejected_reply is not None:
            attempt['repair'] = True
        attempts.append(attempt)
        started = monotonic()
        try:
            reply = send(materials, model_settings)
            if rejected_reply is not None:
                attempt['repair_echo'] = reply.text == rejected_reply
                rejected_reply = None
            attempt['response'] = dict(text=reply.text[:_MAX_REPLY],
                                       truncated_for_report=len(reply.text) > _MAX_REPLY,
                                       finish_reason=reply.finish_reason, truncated=reply.truncated,
                                       provider=getattr(reply, 'provider', None),
                                       model=getattr(reply, 'model', None),
                                       response_id=getattr(reply, 'response_id', None))
            return reply
        except modelspell.ModelSpellError as exc:
            attempt['provider_error'] = provider_error(exc)
            raise
        except KeyboardInterrupt:
            attempt['interrupted'] = True
            attempt['send_outcome_uncertain'] = True
            raise
        finally:
            attempt['elapsed_seconds'] = monotonic() - started

    def request(name):
        nonlocal stage, rejected_reply
        stage = name
        if mode != 'legacy-json':
            before = len(attempts)

            def capture(materials, config):
                nonlocal rejected_reply
                reply = record_request(materials, config)
                # Keep the full raw first reply only in memory for exact echo comparison.
                if len(attempts) == before + 1:
                    rejected_reply = reply.text
                return reply

            def rejected(issues):
                attempts[-1]['validation'] = dict(outcome='invalid_yaml', issues=issues)

            try:
                flow.generate(stage, capture, settings, on_reject=rejected)
            except AuthoringError as exc:
                if len(attempts) > before and 'response' in attempts[-1]:
                    details = dict(getattr(exc, 'details', {}))
                    details.pop('first_attempt', None)
                    attempts[-1]['validation'] = dict(outcome=exc.code, **details)
                raise
            finally:
                rejected_reply = None
            attempts[-1]['validation'] = {'outcome': 'ok'}
            return
        before = len(attempts)
        try:
            flow.generate(stage, record_request, settings)
            attempts[-1]['validation'] = {'outcome': 'ok'}
        except AuthoringError as exc:
            details = getattr(exc, 'details', {})
            cause = exc.__context__
            if isinstance(cause, json.JSONDecodeError):
                details = dict(reason=cause.msg, line=cause.lineno, column=cause.colno)
            if len(attempts) > before:
                attempts[-1]['validation'] = dict(outcome=exc.code, **details)
            raise

    outcome = None
    try:
        if mode == 'legacy-json':
            flow = StagedAuthoring(instruction, example_count, interface)
            request('inputs')
            result.update(interface=flow.contract, inputs=flow.inputs)
            request('expectations')
            result['expectations'] = flow.outputs
            request('python')
        else:
            flow = YamlAuthoring(instruction, example_count, interface=interface, one_shot=mode == 'one-shot-yaml',
                                 records=records, guidance=guidance)
            if flow.one_shot:
                request('one-shot')
                result['examples_yaml'] = flow.examples_yaml()
            else:
                result.update(examples_valid=None, examples_first_pass=None)
                if checkpoint is None:
                    try:
                        request('examples')
                    finally:
                        if attempts:
                            first = attempts[0].get('validation')
                            final = attempts[-1].get('validation')
                            result['examples_first_pass'] = first['outcome'] == 'ok' if first else None
                            result['examples_valid'] = final['outcome'] == 'ok' if final else None
                    accepted = _accepted_examples(attempts)
                else:
                    accepted = _accepted_examples(checkpoint['attempts'])
                    flow.accept('examples', accepted)
                    result.update(examples_valid=True, examples_first_pass=checkpoint['examples_first_pass'])
                # Revalidate the original reply on resume. Canonical YAML can be larger than
                # the reply limit when the model used flow-style YAML.
                result.update(examples_yaml=flow.examples_yaml(), examples_sha256=digest(accepted.encode()),
                              visible_case_id='1')
                examples = [dict(example_input=pair['inputs'], expected_output=pair['outputs'], visible=index == 0)
                            for index, pair in enumerate(flow.pairs)]
                if not examples_only:
                    if checkpoint is None and on_checkpoint is not None:
                        on_checkpoint(dict(result, status='BLOCKED', failed_stage='python',
                                           reason='python_pending', outcome='python_pending',
                                           verified=fixed_verification(task, None),
                                           reference=reference_verification(task, examples)))
                    request('python')
        status = 'PASS'
        if not examples_only:
            stage = 'execution'
            draft = flow.draft()
            examples = draft['examples']
            result['valid_draft'] = True
            executions = run_examples(draft)
            result.update(evaluate_examples(draft, executions), executed=True)
            status = result['status']
            if status != 'PASS':
                outcome = next((case['outcome'] for case in executions if case['outcome'] in BLOCKED_OUTCOMES),
                               'output_mismatch' if any(case['status'] == 'mismatch' for case in executions)
                               else 'execution_failed')
            stage = 'verification'
            try:
                result['verified'] = fixed_verification(task, draft)
            except RuntimeError as exc:
                if exc.args != ('cleanup_failed',):
                    raise
                result['verified'] = {'status': 'NOT_RUN', 'reason': 'cleanup_failed'}
                # A local cleanup blocker stops the batch while preserving agreement evidence.
                result['agreement_status'] = status
                status, outcome = 'BLOCKED', 'cleanup_failed'
            stage = 'execution'
    except (KeyboardInterrupt, modelspell.Cancelled):
        status, outcome = 'BLOCKED', 'interrupted'
        result['interrupted'] = True
    except modelspell.ModelSpellError as exc:
        status, outcome = 'BLOCKED', type(exc).__name__
    except AuthoringError as exc:
        outcome = exc.code
        status = 'BLOCKED' if outcome in BLOCKED_OUTCOMES else 'FAIL'
    except RuntimeError as exc:
        if exc.args != ('cleanup_failed',):
            raise
        status, outcome = 'BLOCKED', 'cleanup_failed'
    if 'verified' not in result:
        result['verified'] = fixed_verification(task, None)
    result['reference'] = reference_verification(task, examples, executions)
    if outcome:
        result.update(reason=outcome, outcome=outcome, failed_stage=stage)
    return dict(result, status=status)


def evaluate_examples(draft, executions=None):
    if executions is None:
        executions = run_examples(draft)
    cases = [dict(case_report(example['example_input'], execution), case_id=str(index), visible=example['visible'])
             for index, (example, execution) in enumerate(zip(draft['examples'], executions), 1)]
    if any(case['outcome'] in BLOCKED_OUTCOMES for case in cases):
        status = 'BLOCKED'
    else:
        status = 'PASS' if all(case['status'] == 'pass' for case in cases) else 'FAIL'
    held_back = [case for case in cases if not case['visible']]
    return dict(status=status, source=draft['source'], examples=cases, visible_case_status=cases[0]['status'],
                held_back=dict(total=len(held_back), passed=sum(case['status'] == 'pass' for case in held_back)))


def transient_blocker(result):
    if result['status'] != 'BLOCKED' or result.get('interrupted') or result['failed_stage'] in ('execution', 'verification'):
        return False
    attempts = result['attempts']
    error = attempts[-1].get('provider_error', {}) if attempts else {}
    status = error.get('http_status')
    if status == 429:
        return error.get('limit_source') == 'upstream_provider_shared_pool'
    return (error.get('type') in ('ConnectError', 'RequestTimeout')
            or type(status) is int and 500 <= status < 600)


def load_resume(path, manifest, jobs, contracts, count, mode):
    data = path.read_bytes()
    report = json.loads(data)
    if not isinstance(report, dict) or not manifest['source'] or report.get('manifest') != manifest:
        raise ValueError('resume manifest missing or incompatible; start a fresh report with the intended flags')
    allowed = {(task, level): instruction for task, _, level, instruction in jobs}
    stored = {(job['task'], job['difficulty']): job['instruction'] for job in manifest['jobs']}
    results = {}
    for item in report['results']:
        identity = (item['task'], item['difficulty'])
        if (identity not in allowed or identity in results or item['instruction'] != stored[identity]
                or item['status'] not in ('PASS', 'FAIL', 'BLOCKED')
                or type(item['request_count']) is not int or item['request_count'] < 0):
            raise ValueError('resume report contains an invalid or duplicate task result')
        if item['status'] == 'BLOCKED' and mode == 'two-call' and item.get('examples_valid') is True:
            accepted = _accepted_examples(item['attempts'])
            if item.get('visible_case_id') != '1' or digest(accepted.encode()) != item.get('examples_sha256'):
                raise ValueError('accepted examples checkpoint is missing, changed, or redacted')
            flow = YamlAuthoring(allowed[identity], count, **contracts.get(identity[0], {}))
            flow.accept('examples', accepted)
        results[identity] = item
    if type(report['request_count']) is not int or report['request_count'] != sum(i['request_count'] for i in results.values()):
        raise ValueError('resume report logical call counts do not match task evidence')
    return results, {'path': str(path.resolve()), 'sha256': digest(data)}


def _uncertain(item):
    if item.get('reason') == 'python_pending':
        return True
    attempts = item.get('attempts', [])
    if not attempts:
        return False
    last = attempts[-1]
    error = last.get('provider_error', {})
    return (last.get('send_outcome_uncertain') or error.get('type') == 'RequestTimeout'
            or error.get('type') == 'Cancelled' and error.get('sent') is not False)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Generate and run the playground presets through OpenRouter and Monty. Live runs may incur API charges.')
    task_ids = tuple(f'{index:02d}' for index in range(1, len(PRESETS) + 1))
    parser.add_argument('--task', choices=task_ids, action='append', help='Preset number. Repeat to select several.')
    parser.add_argument('--difficulty', choices=(*DIFFICULTIES, 'all'), default=DEFAULT_DIFFICULTY)
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'OpenRouter model ID (default: {DEFAULT_MODEL}).')
    parser.add_argument('--mode', choices=('legacy-json', 'two-call', 'one-shot-yaml'), default='legacy-json')
    parser.add_argument('--examples-only', action='store_true', help='Stop after structural validation in two-call mode.')
    parser.add_argument('--examples', type=int, help='Examples per prompt, 1–20 (default: 1 for YAML, 3 for JSON).')
    parser.add_argument('--temperature', type=float, default=0)
    parser.add_argument('--reasoning', choices=('off', 'low', 'medium', 'high'), help='Default: provider setting.')
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--timeout', type=float, default=120, help='Model request timeout in seconds (default: 120).')
    parser.add_argument('--report', type=Path, help='Write JSON results to this path.')
    parser.add_argument('--interface', type=Path, help='JSON interface for a single selected preset.')
    preview = parser.add_mutually_exclusive_group()
    preview.add_argument('--list', action='store_true', help='List preset numbers and titles without making requests.')
    preview.add_argument('--dry-run', action='store_true', help='Print the selected prompts and request budget without a key.')
    preview.add_argument('--resume', type=Path, metavar='REPORT',
                         help='Reuse a partial report. Repeat its original benchmark flags and use a new report path.')
    args = parser.parse_args(argv)
    if args.list:
        for task_id, (title, _) in zip(task_ids, PRESETS):
            print(f'{task_id}  {title}')
        return 0
    if args.examples_only and args.mode != 'two-call':
        parser.error('--examples-only requires --mode two-call')
    if args.examples is None:
        args.examples = 3 if args.mode == 'legacy-json' else 1
    if not 1 <= args.examples <= 20 or not 1 <= args.max_tokens <= 16384 or not 0 < args.timeout <= 300:
        parser.error('use 1–20 examples, 1–16384 max tokens, and a timeout in (0, 300]')
    settings = cli_settings(parser, args)
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    endpoint, send = bind_openrouter(parser, key, settings, args.timeout, dry_run=args.dry_run)

    difficulties = DIFFICULTIES if args.difficulty == 'all' else (args.difficulty,)
    jobs = [(task_id, title, level, variants[level])
            for task_id, (title, variants) in zip(task_ids, PRESETS)
            if not args.task or task_id in args.task for level in difficulties]
    contracts = load_preset_contracts() if args.mode != 'legacy-json' else {}
    if args.interface is not None:
        if len(jobs) != 1:
            parser.error('--interface requires one preset and one difficulty')
        try:
            interface = (load_interface(args.interface) if args.mode == 'legacy-json'
                         else parse_json(args.interface.read_text(encoding='utf-8')))
            if args.mode != 'legacy-json':
                validate_interface(interface)
        except (AuthoringError, OSError, ValueError) as exc:
            parser.error(f'invalid interface: {exc}')
        contracts = {jobs[0][0]: dict(interface=interface)}

    max_calls = 2 if args.examples_only or args.mode == 'one-shot-yaml' else 3

    def banner(maximum):
        print(f"{redact(settings['model'], key)} · up to {maximum} logical calls and {maximum} HTTP attempts · "
              f'{args.examples} examples and {args.max_tokens} output tokens per call', flush=True)

    if args.dry_run:
        banner(max_calls * len(jobs))
        for task_id, title, level, instruction in jobs:
            print(f'\n{task_id} {title} [{level}]')
            if args.mode == 'legacy-json':
                print(instruction)
            else:
                flow = YamlAuthoring(instruction, args.examples, one_shot=args.mode == 'one-shot-yaml',
                                     **contracts[task_id])
                materials = flow.materials('one-shot' if flow.one_shot else 'examples')
                print(materials['system'] + '\n\n' + materials['user'])
        return 0

    try:
        modelspell_source_sha256 = package_source_digest(modelspell)
    except (OSError, TypeError) as exc:
        parser.error(f'cannot fingerprint modelSpell source: {redact(str(exc), key)}')
    source = source_identity(ROOT)
    run_settings = dict(settings, example_count=args.examples, timeout=args.timeout)
    manifest = redact(dict(
        schema=1, mode=args.mode, examples_only=args.examples_only, settings=run_settings,
        endpoint=dict(kind=endpoint.kind, base_url=endpoint.base_url, routing={}),
        versions={name: version(name) for name in ('modelSpell', 'pydantic-monty', 'PyYAML')},
        jobs=[dict(task=task, difficulty=level, instruction=instruction,
                   contract_sha256=digest(json.dumps(contracts.get(task, {}), allow_nan=False).encode())) for task, _, level, instruction in jobs],
        prompts_sha256=digest_json({str(path.relative_to(ROOT)): digest(path.read_bytes())
                                    for path in (ROOT / 'scriptspell' / 'prompts').rglob('*') if path.is_file()}),
        modelspell_source_sha256=modelspell_source_sha256, source=source), key)

    previous, origin = {}, None
    if args.resume:
        args.report = args.report or args.resume.with_name(f'{args.resume.stem}.resumed.json')
        if args.report.exists() or args.report.resolve() == args.resume.resolve():
            parser.error('--resume requires a new report destination')
        try:
            previous, origin = load_resume(args.resume, manifest, jobs, contracts, args.examples, args.mode)
        except (OSError, ValueError, KeyError, AttributeError, TypeError, AuthoringError) as exc:
            parser.error(f'cannot resume: {redact(str(exc), key)}')
    args.report = args.report or Path('reports/authoring_staged.json')
    pending = [(task, title, level, instruction) for task, title, level, instruction in jobs
               if previous.get((task, level), {}).get('status') not in ('PASS', 'FAIL')]
    if pending and not key:
        parser.error('set OPENROUTER_API_KEY for an unattended run')
    prior_requests = sum(item['request_count'] for item in previous.values())
    requests = 0
    max_pending_calls = sum(1 if args.mode == 'two-call' and previous.get((task, level), {}).get('examples_valid')
                            else max_calls for task, _, level, _ in pending)
    banner(max_pending_calls)

    def counted_send(materials, model_settings):
        nonlocal requests
        requests += 1
        return send(materials, model_settings)

    results = dict(previous)
    revision = source['commit'][:7] + ('-dirty' if source['dirty'] else '') if source else None
    report = dict(status='INCOMPLETE', mode=args.mode, settings=run_settings, revision=revision, manifest=manifest,
                  tasks_requested=len(jobs), previous_request_count=prior_requests, interrupted=False)
    if origin:
        report['resumed_from'] = origin
    if args.mode == 'two-call':
        report['examples_only'] = args.examples_only

    def save(*, initial=False):
        ordered = [results[task, level] for task, _, level, _ in jobs if (task, level) in results]
        report.update(results=ordered, request_count=prior_requests + requests, invocation_request_count=requests,
                      http_attempt_count=None, http_attempt_max=prior_requests + requests, http_retry_count=0,
                      summary=summarize(ordered))
        if args.mode == 'two-call':
            report['examples_validation'] = yaml_counts(ordered)
        atomic_report(args.report, redact(report, key), exclusive=initial and bool(origin))

    save(initial=True)
    transient_streak = 0
    try:
        for task_id, title, level, instruction in pending:
            if transient_streak:
                sleep(TRANSIENT_PAUSE_SECONDS)
            identity = (task_id, level)
            old = previous.get(identity, {})
            checkpoint = old if args.mode == 'two-call' and old.get('examples_valid') is True else None
            if _uncertain(old):
                print(f'{task_id} [{level}] · prior request may have been sent; resuming as requested', flush=True)
            before, started = requests, monotonic()
            def save_task(result):
                if old:
                    result = dict(result, attempts=old['attempts'] + result['attempts'],
                                  blocked_history=[*old.get('blocked_history', []),
                                                   dict(reason=old.get('reason'), failed_stage=old.get('failed_stage'),
                                                        through_attempt=len(old['attempts']))])
                results[identity] = redact(dict(
                    result, task=task_id, title=title, difficulty=level, instruction=instruction,
                    preset_digest=digest(instruction.encode()), elapsed_seconds=old.get('elapsed_seconds', 0)
                    + monotonic() - started, request_count=old.get('request_count', 0) + requests - before), key)
                report['interrupted'] = result.get('interrupted', False)
                save()

            result = evaluate(counted_send, {}, instruction, args.examples, mode=args.mode,
                              task=task_id, checkpoint=checkpoint, examples_only=args.examples_only,
                              on_checkpoint=save_task, **contracts.get(task_id, {}))
            save_task(result)
            print_task(results[identity])
            if result['status'] == 'BLOCKED':
                if not transient_blocker(result) or transient_streak:
                    break
                transient_streak = 1
            else:
                transient_streak = 0
    except (KeyboardInterrupt, modelspell.Cancelled):
        report['interrupted'] = True

    if report['interrupted'] or any(result['status'] == 'BLOCKED' for result in results.values()):
        report['status'] = 'BLOCKED'
    elif any(result['status'] == 'FAIL' for result in results.values()):
        report['status'] = 'FAIL'
    else:
        report['status'] = 'PASS'
    save()
    print_summary(report, args.report, jobs)
    return 130 if report['interrupted'] else {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
