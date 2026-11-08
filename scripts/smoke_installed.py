"""Exercise the installed consumer API, not a source checkout or a mocked runtime."""
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
import sys
import scriptspell

assert Path(scriptspell.__file__).is_relative_to(Path(sys.prefix))
assert scriptspell.__version__ == version('scriptSpell') == scriptspell.profile()['version']
materials = scriptspell.prepare_authoring('Threshold an exact VAF.', {
    'inputs': {'vaf': 'Decimal'}, 'outputs': {'eligible': 'boolean'}})
proposal = {
    'source': 'from decimal import Decimal\ndef transform(inputs):\n    return {"eligible": inputs["vaf"] >= Decimal("0.05")}',
    'summary': 'Compare with an exact threshold.',
    'assumptions': [], 'unmet_requirements': []}
assert materials['response_schema']['required'] == list(proposal)
assert scriptspell.validate_proposal(proposal)['outcome'] == 'ok'
result = scriptspell.run(proposal['source'], {'vaf': Decimal('0.049999999999999999')}, ['eligible'])
assert result['outcome'] == 'ok', result
assert result['values'] == {'eligible': False}, result
print('smoke ok:', scriptspell.__file__)
