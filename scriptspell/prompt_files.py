"""Read the packaged prompt catalog and render literal text templates."""
import json
import re
from importlib.resources import files
from string import Template

_ROOT = files('scriptspell').joinpath('prompts')


def _read(path):
    return _ROOT.joinpath(*path.split('/')).read_text(encoding='utf-8').strip()


def _index():
    return json.loads(_read('index.json'))


def render(name, **values):
    return Template(_read(_index()['templates'][name])).substitute(values)


def load_presets():
    index = _index()
    levels = index['difficulty_sections']
    presets = []
    for number, entry in enumerate(index['presets'], 1):
        if entry['id'] != f'{number:02d}':
            raise ValueError('Preset IDs must match the catalog order')
        parts = re.split(r'^## (Task|Medium guidance|Easy guidance)\s*$', _read(entry['file']), flags=re.M)
        sections = dict(zip(parts[1::2], map(str.strip, parts[2::2])))
        variants = {level: '\n\n'.join(sections[heading] for heading in headings)
                    for level, headings in levels.items()}
        presets.append((entry['title'], variants))
    return tuple(levels), index['default_difficulty'], tuple(presets)



def task_text(task, **data):
    sections = [render('shared/task', task=task)]
    for name, value in data.items():
        if value is not None:
            label = name.replace('_', ' ').capitalize()
            sections.append(f'{label}\n\n{json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2)}')
    return '\n\n'.join(sections)
