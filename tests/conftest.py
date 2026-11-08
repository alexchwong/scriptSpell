def pytest_addoption(parser):
    parser.addoption('--strict-feasibility', action='store_true',
                     help='Fail, rather than skip, BLOCKED process-observed feasibility checks.')
