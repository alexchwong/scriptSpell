"""Run the playground's prompt presets in a paid, unattended OpenRouter batch."""
import argparse
import json
import os
from pathlib import Path

import modelspell
from scriptspell import AuthoringError, generate_draft, run_examples, validate_model_settings
from scriptspell.workflow import display_json
from ui.presets import DEFAULT_DIFFICULTY, DIFFICULTIES, PRESETS
from ui.service import dispatch

DEFAULT_MODEL = 'qwen/qwen3-coder-next'
BLOCKED_OUTCOMES = {'cleanup_failed', 'dependency_unavailable', 'platform_unavailable', 'worker_crash'}


def evaluate(send, settings, instruction, example_count, *, api_key=''):
    attempts = []

    def capture(text):
        if api_key:
            text = text.replace(api_key, '[REDACTED]')
        return dict(text=text[:6291456], truncated_for_report=len(text) > 6291456)

    def record(materials, model_settings):
        entry = dict(attempt=len(attempts) + 1, request=materials)
        attempts.append(entry)
        try:
            response = send(materials, model_settings)
        except modelspell.ModelSpellError as exc:
            entry['provider_error'] = dict(type=type(exc).__name__, http_status=getattr(exc, 'status', None))
            body = getattr(exc, 'body', '')
            if body:
                entry['provider_error']['body'] = capture(body)
            raise
        entry['response'] = dict(capture(response.text), finish_reason=response.finish_reason,
                                 truncated=response.truncated, model=getattr(response, 'model', None),
                                 provider=getattr(response, 'provider', None),
                                 response_id=getattr(response, 'response_id', None))
        return response

    def validation(details):
        if attempts:
            attempts[-1]['validation'] = details

    result = _evaluate(record, settings, instruction, example_count, validation)
    return dict(result, attempts=attempts)


def _evaluate(send, settings, instruction, example_count, on_attempt):
    try:
        draft = generate_draft(send, settings, instruction, example_count=example_count, on_attempt=on_attempt)
        if draft['unmet_requirements']:
            return dict(status='FAIL', outcome='requirements_unmet', source=draft['source'],
                        unmet_requirements=draft['unmet_requirements'])
        results = run_examples(draft)
    except modelspell.ModelSpellError as exc:
        return dict(status='BLOCKED', outcome=type(exc).__name__)
    except AuthoringError as exc:
        status = 'BLOCKED' if exc.code in BLOCKED_OUTCOMES else 'FAIL'
        return dict(status=status, outcome=exc.code, details=exc.details)
    except RuntimeError as exc:
        if exc.args != ('cleanup_failed',):
            raise
        return dict(status='BLOCKED', outcome='cleanup_failed')

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
    parser.add_argument('--report', type=Path, default=Path('reports/authoring_presets.json'))
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
    print(f"{settings['model']} · up to {2 * len(jobs)} paid requests · "
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
    report = dict(status='INCOMPLETE', settings=dict(settings, example_count=args.examples, timeout=args.timeout),
                  tasks_requested=len(jobs), results=results)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    save()  # Confirm the destination is writable before making any paid requests.
    interrupted = False
    try:
        for task_id, title, level, instruction in jobs:
            result = evaluate(send, settings, instruction, args.examples, api_key=key)
            results.append(dict(result, task=task_id, title=title, difficulty=level, instruction=instruction))
            print(f"{result['status']} {task_id} {title} [{level}]", flush=True)
            save()
            if result['status'] == 'BLOCKED':
                break
    except KeyboardInterrupt:
        interrupted = True
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
