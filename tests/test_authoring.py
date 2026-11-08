from scriptspell import prepare_authoring,validate_proposal,profile

def test_proposal_is_checked_without_execution():
    p=dict(source='def transform(inputs):\n    while True:\n        pass',summary='loop',assumptions=[],unmet_requirements=[])
    assert validate_proposal(p)['outcome']=='ok'
    assert validate_proposal(dict(p,model='remote'))['outcome']=='invalid_proposal'

def test_prompt_captures_profile_and_is_independent():
    one=prepare_authoring('trim',{'inputs':['text'],'outputs':['out']})
    one['response_schema']['required'].clear()
    two=prepare_authoring('trim',{'inputs':['text'],'outputs':['out']})
    assert len(two['response_schema']['required'])==4
    assert profile()['profile'] in two['system']
    assert two['prompt_version']==3
    assert 'isinstance' in two['profile']['builtins']
