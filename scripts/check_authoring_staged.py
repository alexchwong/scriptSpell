"""Experimental authoring benchmark with separate inputs, expectations and Python calls."""
import argparse
import json
import os
from pathlib import Path
from time import monotonic

import modelspell

from scriptspell import AuthoringError, run_examples, validate_model_settings
from scriptspell.staged import StageError, StagedAuthoring, _interface, _MAX_REPLY
from scriptspell.workflow import display_json, parse_json
from scripts.check_authoring_presets import BLOCKED_OUTCOMES, DEFAULT_MODEL
from ui.presets import DEFAULT_DIFFICULTY, DIFFICULTIES, PRESETS
from ui.service import dispatch

def load_interface(path):
    return _interface(parse_json(path.read_text(encoding='utf-8')))


def evaluate(send, settings, instruction, example_count, *, interface=None):
    attempts = []
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    result = {'attempts': attempts}

    def capture(text):
        return text.replace(key, '[REDACTED]') if key else text

    def request(stage):
        materials = flow.materials(stage)
        attempt = dict(stage=stage, request=materials)
        attempts.append(attempt)
        started = monotonic()
        try:
            reply = send(materials, dict(settings))
            attempt['response'] = dict(text=capture(reply.text[:_MAX_REPLY]),
                                       truncated_for_report=len(reply.text) > _MAX_REPLY,
                                       finish_reason=reply.finish_reason, truncated=reply.truncated,
                                       provider=getattr(reply, 'provider', None),
                                       model=getattr(reply, 'model', None),
                                       response_id=getattr(reply, 'response_id', None))
            if reply.truncated or reply.finish_reason != 'stop':
                raise StageError('incomplete_model_response')
            flow.accept(stage, reply.text)
            attempt['validation'] = {'outcome': 'ok'}
        except AuthoringError as exc:
            details = getattr(exc, 'details', {})
            # The shared JSON parser preserves the underlying decoder exception.
            cause = exc.__context__
            if isinstance(cause, json.JSONDecodeError):
                details = dict(reason=cause.msg, line=cause.lineno, column=cause.colno)
            attempt['validation'] = dict(outcome=exc.code, **details)
            raise
        except modelspell.ModelSpellError as exc:
            attempt['provider_error'] = dict(type=type(exc).__name__,
                                             http_status=getattr(exc, 'status', None),
                                             body=capture(getattr(exc, 'body', '')[:_MAX_REPLY]))
            raise
        finally:
            attempt['elapsed_seconds'] = monotonic() - started

    try:
        flow = StagedAuthoring(instruction, example_count, interface)
        request('inputs')
        result.update(interface=flow.contract, inputs=flow.inputs)
        request('expectations')
        result['expectations'] = flow.outputs
        request('python')
        draft = flow.draft()
        execution = evaluate_examples(draft)
        for index, report in enumerate(execution['examples'], 1):
            report.update(case_id=str(index), visible=index == 1)
        execution['visible_case_status'] = execution['examples'][0]['status']
        held_back = execution['examples'][1:]
        execution['held_back'] = dict(total=len(held_back),
                                      passed=sum(case['status'] == 'pass' for case in held_back))
        if execution['status'] != 'PASS':
            execution['failed_stage'] = 'execution'
        return dict(result, **execution)
    except modelspell.ModelSpellError as exc:
        status, outcome = 'BLOCKED', type(exc).__name__
    except AuthoringError as exc:
        outcome = exc.code
        status = 'BLOCKED' if outcome in BLOCKED_OUTCOMES else 'FAIL'
    except RuntimeError as exc:
        if exc.args != ('cleanup_failed',):
            raise
        status, outcome = 'BLOCKED', 'cleanup_failed'
    failed_stage = attempts[-1]['stage'] if attempts else 'interface'
    if attempts and attempts[-1].get('validation', {}).get('outcome') == 'ok':
        failed_stage = 'execution'
    return dict(result, status=status, outcome=outcome, failed_stage=failed_stage)


def evaluate_examples(draft):
    results = run_examples(draft)
    cases = []
    for example, result in zip(draft['examples'], results):
        case = dict(status=result['status'], outcome=result['outcome'],
                    input_json=display_json(example['example_input']),
                    expected_json=display_json(result['expected']))
        if 'actual' in result:
            case['actual_json'] = display_json(result['actual'])
        cases.append(case)
    if any(case['outcome'] in BLOCKED_OUTCOMES for case in cases):
        status = 'BLOCKED'
    else:
        status = 'PASS' if all(case['status'] == 'pass' for case in cases) else 'FAIL'
    return dict(status=status, source=draft['source'], examples=cases)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Generate and run the playground presets through OpenRouter and Monty. Live runs incur API charges.')
    task_ids = tuple(f'{index:02d}' for index in range(1, len(PRESETS) + 1))
    parser.add_argument('--task', choices=task_ids, action='append', help='Preset number. Repeat to select several.')
    parser.add_argument('--difficulty', choices=(*DIFFICULTIES, 'all'), default=DEFAULT_DIFFICULTY)
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'OpenRouter model ID (default: {DEFAULT_MODEL}).')
    parser.add_argument('--examples', type=int, default=3, help='Examples per prompt, 1–20 (default: 3).')
    parser.add_argument('--temperature', type=float, default=0)
    parser.add_argument('--reasoning', choices=('off', 'low', 'medium', 'high'), help='Default: provider setting.')
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--timeout', type=float, default=120, help='Model request timeout in seconds (default: 120).')
    parser.add_argument('--report', type=Path, default=Path('reports/authoring_staged.json'))
    parser.add_argument('--interface', type=Path, help='JSON interface for a single selected preset.')
    preview = parser.add_mutually_exclusive_group()
    preview.add_argument('--list', action='store_true', help='List preset numbers and titles without making requests.')
    preview.add_argument('--dry-run', action='store_true', help='Print the selected prompts and request budget without a key.')
    args = parser.parse_args(argv)
    if args.list:
        for task_id, (title, _) in zip(task_ids, PRESETS):
            print(f'{task_id}  {title}')
        return 0
    if not 1 <= args.examples <= 20 or not 1 <= args.max_tokens <= 16384 or not 0 < args.timeout <= 300:
        parser.error('use 1–20 examples, 1–16384 max tokens, and a timeout in (0, 300]')
    try:
        settings = validate_model_settings(model=args.model, temperature=args.temperature,
                                           reasoning=args.reasoning, max_tokens=args.max_tokens)
    except AuthoringError as exc:
        parser.error(exc.code)

    difficulties = DIFFICULTIES if args.difficulty == 'all' else (args.difficulty,)
    jobs = [(task_id, title, level, variants[level])
            for task_id, (title, variants) in zip(task_ids, PRESETS)
            if not args.task or task_id in args.task for level in difficulties]
    options = {}
    if args.interface is not None:
        if len(jobs) != 1:
            parser.error('--interface requires one preset and one difficulty')
        try:
            options['interface'] = load_interface(args.interface)
        except (AuthoringError, OSError, UnicodeError) as exc:
            parser.error(f'invalid interface: {exc}')
    print(f"{settings['model']} · up to {3 * len(jobs)} paid requests · "
          f'{args.examples} examples and {args.max_tokens} output tokens per request', flush=True)
    if args.dry_run:
        for task_id, title, level, instruction in jobs:
            print(f'\n{task_id} {title} [{level}]\n{instruction}')
        return 0
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    if not key:
        parser.error('set OPENROUTER_API_KEY for an unattended run')

    send = dispatch(modelspell.Endpoint('openrouter', api_key=key), modelspell.CancelHandle(), {},
                    timeout=args.timeout)
    results = []
    requests = 0

    def counted_send(materials, model_settings):
        nonlocal requests
        requests += 1
        return send(materials, model_settings)

    report = dict(status='INCOMPLETE', settings=dict(settings, example_count=args.examples, timeout=args.timeout),
                  tasks_requested=len(jobs), request_count=0, results=results)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    save()  # Confirm the destination is writable before making any paid requests.
    interrupted = False
    try:
        for task_id, title, level, instruction in jobs:
            before = requests
            started = monotonic()
            result = evaluate(counted_send, settings, instruction, args.examples, **options)
            results.append(dict(result, task=task_id, title=title, difficulty=level, instruction=instruction,
                                request_count=requests - before, elapsed_seconds=monotonic() - started))
            report['request_count'] = requests
            print(f"{result['status']} {task_id} {title} [{level}]", flush=True)
            save()
            if result['status'] == 'BLOCKED':
                break
    except KeyboardInterrupt:
        interrupted = True
        report['request_count'] = requests
    if interrupted or any(result['status'] == 'BLOCKED' for result in results):
        report['status'] = 'BLOCKED'
    elif any(result['status'] == 'FAIL' for result in results):
        report['status'] = 'FAIL'
    else:
        report['status'] = 'PASS'
    save()
    print(f"{report['status']} · {len(results)}/{len(jobs)} prompt variants · {args.report}")
    return 130 if interrupted else {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
