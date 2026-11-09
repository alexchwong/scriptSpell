"""Consumer-owned authoring and execution, with an offline model stand-in.

Run: python examples/application_adapter.py
The callback takes authoring materials and returns a parsed proposal dictionary.
A real application can implement it with modelSpell or another model client.
"""
from scriptspell import prepare_authoring, validate_proposal, run


def author_candidate(dispatch, task, interface=None, examples=(), diagnostics=None):
    # Only pass context the application has approved for this model/provider.
    materials = prepare_authoring(task, interface, examples, diagnostics)
    proposal = dispatch(materials)
    checked = validate_proposal(proposal)
    if checked['outcome'] != 'ok':
        raise ValueError('proposal_rejected')
    if proposal['unmet_requirements']:
        raise ValueError('requirements_unmet')
    # This returns a candidate, not permission to publish it.
    return proposal


def execute(source, inputs, output_names, *, cancel=None):
    result = run(source, inputs, output_names, cancel=cancel)
    if result['outcome'] != 'ok':
        raise RuntimeError(result['outcome'])
    return result['values']


def offline_model(materials):
    """Synthetic response; no network or credentials. Real dispatch belongs to the app."""
    assert materials['response_schema']['required'] == [
        'source', 'summary', 'assumptions', 'unmet_requirements', 'example_input', 'expected_output']
    return {
        'source': 'def transform(inputs):\n    return {"clean_text": inputs["text"].strip()}',
        'summary': 'Trim surrounding whitespace.',
        'assumptions': [],
        'unmet_requirements': [],
        'example_input': {'text': ' example '},
        'expected_output': {'clean_text': 'example'},
    }


def main():
    candidate = author_candidate(
        offline_model, 'Trim surrounding whitespace.',
        {'inputs': {'text': 'string'}, 'outputs': {'clean_text': 'string'}},
        examples=[{'inputs': {'text': ' example '},
                   'outputs': {'clean_text': 'example'}}])
    assert execute(candidate['source'], candidate['example_input'], list(candidate['expected_output'])) == candidate['expected_output']
    # The host checks its own output contract and expected answer before storing source.
    actual = execute(candidate['source'], {'text': ' synthetic '}, ['clean_text'])
    assert actual == {'clean_text': 'synthetic'}
    print('authoring and execution ok')


if __name__ == '__main__':
    main()
