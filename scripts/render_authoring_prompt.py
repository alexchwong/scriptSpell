"""Print an authoring message exactly as the modelSpell adapter would send it."""
import argparse
from pathlib import Path

from scriptspell import YamlAuthoring
from scriptspell.prompt_files import load_preset_contracts
from scriptspell.staged import StagedAuthoring, _interface
from scriptspell.yaml_contract import validate_interface
from scriptspell.workflow import AuthoringError, generation_preview, parse_json
from ui.presets import DEFAULT_DIFFICULTY, DIFFICULTIES, PRESETS
from ui.service import prompt_preview


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    tasks = parser.add_mutually_exclusive_group(required=True)
    task_ids = [f'{number:02d}' for number in range(1, len(PRESETS) + 1)]
    tasks.add_argument('--task', choices=task_ids)
    tasks.add_argument('--instruction', type=Path, help='Read the task from a text file.')
    parser.add_argument('--difficulty', choices=DIFFICULTIES, default=DEFAULT_DIFFICULTY)
    parser.add_argument('--stage', choices=('one-shot', 'examples', 'inputs', 'expectations', 'python'), required=True)
    parser.add_argument('--mode', choices=('two-call', 'one-shot-yaml', 'legacy-json'), default='legacy-json')
    parser.add_argument('--examples', type=int)
    parser.add_argument('--examples-yaml', type=Path, help='Accepted YAML reply for the two-call Python stage.')
    parser.add_argument('--interface', type=Path)
    parser.add_argument('--inputs', type=Path, help='Saved reply from the input stage.')
    parser.add_argument('--expected-outputs', type=Path, help='Saved reply from the expected-output stage.')
    parser.add_argument('--role', choices=('system', 'user', 'both'), default='both')
    args = parser.parse_args(argv)
    if args.examples is None:
        args.examples = 3 if args.mode == 'legacy-json' else 1
    stages = {'two-call': ('examples', 'python'), 'one-shot-yaml': ('one-shot',),
              'legacy-json': ('one-shot', 'inputs', 'expectations', 'python')}
    if args.stage not in stages[args.mode]:
        parser.error('--stage is incompatible with --mode')
    if args.mode == 'two-call' and args.stage == 'python' and not args.examples_yaml:
        parser.error('--examples-yaml is required for the two-call Python stage')
    if args.mode == 'legacy-json':
        if args.stage in ('expectations', 'python') and not args.inputs:
            parser.error('--inputs is required for this stage')
        if args.stage == 'python' and not args.expected_outputs:
            parser.error('--expected-outputs is required for the Python stage')
        if args.stage == 'one-shot' and args.interface:
            parser.error('--interface is for staged authoring')
    try:
        task = (PRESETS[int(args.task) - 1][1][args.difficulty] if args.task else
                args.instruction.read_text(encoding='utf-8'))
        if args.mode != 'legacy-json':
            options = load_preset_contracts()[args.task] if args.task else {}
            if args.interface:
                interface = parse_json(args.interface.read_text(encoding='utf-8'))
                validate_interface(interface)
                options = dict(interface=interface)
            flow = YamlAuthoring(task, args.examples, one_shot=args.mode == 'one-shot-yaml', **options)
            if args.stage == 'python':
                flow.accept('examples', args.examples_yaml.read_text(encoding='utf-8'))
            materials = flow.materials(args.stage)
        elif args.stage == 'one-shot':
            materials = generation_preview(task, args.examples)
        else:
            interface = _interface(parse_json(args.interface.read_text(encoding='utf-8'))) if args.interface else None
            flow = StagedAuthoring(task, args.examples, interface)
            if args.stage in ('expectations', 'python'):
                flow.accept('inputs', args.inputs.read_text(encoding='utf-8'))
            if args.stage == 'python':
                flow.accept('expectations', args.expected_outputs.read_text(encoding='utf-8'))
            materials = flow.materials(args.stage)
    except (AuthoringError, OSError, ValueError) as exc:
        issues = getattr(exc, "details", {}).get("issues", [])
        parser.error("\n".join([str(exc), *map(str, issues)]))
    preview = prompt_preview(materials)
    if args.role == 'both':
        print('SYSTEM\n\n' + preview['full_system'] + '\n\nUSER\n\n' + preview['user'])
    else:
        print(preview['full_system' if args.role == 'system' else 'user'], end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
