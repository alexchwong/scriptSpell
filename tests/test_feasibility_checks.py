"""The complete monitored checks are ordinary pytests, using the CLI's shared logic."""
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'scripts'
pytestmark=[pytest.mark.feasibility, pytest.mark.skipif(
    not (TOOLS/'check_memory.py').exists(),reason='repository-only feasibility checks')]

@pytest.mark.parametrize('name',['check_memory','check_adversarial'])
def test_monitored_feasibility(name,monkeypatch,request):
    monkeypatch.syspath_prepend(str(TOOLS))
    spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    code=module.main(['--report',str(ROOT/'reports'/(name.removeprefix('check_')+'.json'))])
    if code==2 and not request.config.getoption('--strict-feasibility'):
        pytest.skip('BLOCKED: process observation or prerequisites unavailable; see reports/')
    assert code==0, 'Feasibility FAIL/BLOCKED; see reports/*.json'
