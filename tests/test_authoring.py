from scriptspell import prepare_authoring,validate_proposal,profile

def test_proposal_is_checked_without_execution():
    p=dict(source='def transform(inputs):\n    while True:\n        pass',summary='loop',assumptions=[],unmet_requirements=[],example_input={},expected_output={'out':None})
    assert validate_proposal(p)['outcome']=='ok'
    assert validate_proposal(dict(p,model='remote'))['outcome']=='invalid_proposal'

def test_prompt_captures_profile_and_is_independent():
    one=prepare_authoring('trim',{'inputs':['text'],'outputs':['out']})
    one['response_schema']['required'].clear()
    two=prepare_authoring('trim',{'inputs':['text'],'outputs':['out']})
    assert len(two['response_schema']['required'])==6
    assert profile()['profile'] in two['system']
    assert two['prompt_version']==4
    assert 'isinstance' in two['profile']['builtins']



def candidate(**changes):
    result = dict(source='def transform(inputs):\n    return {"out": inputs["text"].strip()}',
                  summary='Trim', assumptions=[], unmet_requirements=[],
                  example_input={'text': ' a '}, expected_output={'out': 'a'})
    result.update(changes)
    return result


def test_instruction_only_authoring_has_the_same_complete_contract():
    import json
    supplied = [{'inputs': {'text': ' a '}, 'outputs': {'out': 'a'}}]
    inferred = prepare_authoring('Trim whitespace')
    explicit = prepare_authoring('Trim whitespace', {'inputs': {'text': 'string'},
                                                   'outputs': {'out': 'string'}}, supplied)
    assert inferred['response_schema'] == explicit['response_schema']
    assert json.loads(inferred['user'])['interface'] is None
    assert json.loads(explicit['user'])['examples'] == supplied
    assert validate_proposal(candidate())['outcome'] == 'ok'
    for name in ('example_input', 'expected_output'):
        missing = candidate()
        del missing[name]
        assert validate_proposal(missing)['outcome'] == 'invalid_proposal'


def test_example_validation_refuses_unsupported_or_unbounded_data():
    from decimal import Decimal
    bad_values = [[], 1, {'x': 0.5}, {'x': float('nan')}, {'x': Decimal('0.1')},
                  {'x': (1, 2)}, {1: 'bad'}, {'x': 1 << 14280}, {'x': 'a' * 131073}]
    cyclic = {}; cyclic['self'] = cyclic
    bad_values.append(cyclic)
    for value in bad_values:
        assert validate_proposal(candidate(example_input=value))['outcome'] == 'invalid_proposal'
    for value in ({}, {'': 1}, {'x' * 129: 1}, {str(i): i for i in range(101)}):
        assert validate_proposal(candidate(expected_output=value))['outcome'] == 'invalid_proposal'
    assert validate_proposal(candidate(example_input={'vaf': '0.05', 'count': 9007199254740993}))['outcome'] == 'ok'


IMPORT_RULE = 'never use bare `Decimal` without an import'


def test_explicit_import_rule_reaches_every_code_writing_prompt():
    import json
    from scriptspell import YamlAuthoring
    from scriptspell.staged import StagedAuthoring
    from scriptspell.workflow import improve_python
    examples = ('interface:\n  inputs:\n    - n: int\n  outputs:\n    - out: int\n'
                'examples:\n  - inputs:\n      - n: 1\n    outputs:\n      - out: 2\n')
    two_call = YamlAuthoring('Double n', 1)
    two_call.accept('examples', examples)
    one_shot = YamlAuthoring('Double n', 1, one_shot=True)
    legacy = StagedAuthoring('Double n', 1, {'inputs': {'n': 'integer'}, 'outputs': {'out': 'integer'}})
    legacy.accept('inputs', json.dumps({'examples': [{'n': 1}]}))
    legacy.accept('expectations', json.dumps({'outputs': {'1': {'out': 2}}}))
    captured = []

    class Stop(Exception):
        pass

    def dispatch(materials, settings):
        captured.append(materials)
        raise Stop
    draft = dict(source='def transform(inputs):\n    return {"out": 0}', instruction='Double n',
                 examples=[dict(id='a', example_input={'n': 1}, expected_output={'out': 2})])
    reports = [dict(example_id='a', status='mismatch', outcome='ok', actual={'out': 0})]
    try:
        improve_python(dispatch, {'model': 'test/model'}, draft, reports, ['a'])
    except Stop:
        pass
    systems = {'yaml-python': two_call.materials('python')['system'],
               'yaml-one-shot': one_shot.materials('one-shot')['system'],
               'python': legacy.materials('python')['system'],
               'repair': captured[0]['system']}
    for name, system in systems.items():
        assert IMPORT_RULE in system, name
        assert system.count(IMPORT_RULE) == 1, name
        assert profile()['profile'] in system, name
    assert profile()['profile'] == 'scriptspell-pure-v5'
