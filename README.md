# scriptSpell

scriptSpell is a headless Python library for **model-assisted authoring and restricted
execution of small data transformations**. Use it when an application needs to turn a
user's instructions into reusable code that cleans, extracts, groups or reshapes data.
It can serve AgentWiz or any other Python application.

The application supplies a task and interface, sends scriptSpell's authoring materials
to its chosen model, reviews and tests the proposed source, then stores it. Later it
passes that source and new inputs to scriptSpell to execute. Running an approved script
requires no model call.

scriptSpell supplies the tested language profile, authoring prompts, static checks,
exact-value transport and supervised Monty execution. It has **no model client, UI,
server, persistence or AgentWiz/modelSpell dependency**.

## Install

Requires Python 3.10+ and the pinned `pydantic-monty==1.5.0` dependency. Execution is
supported on Linux (including Ubuntu WSL2) and macOS. Native Windows execution returns
`platform_unavailable`; use WSL2.

Install a downloaded release wheel (pip also installs its dependencies):

```sh
python -m pip install /path/to/scriptspell-X.Y.Z-py3-none-any.whl
```

Applications should pin a published wheel URL and its SHA-256 from the
[GitHub release notes](https://github.com/alexchwong/scriptSpell/releases).
The wheel is pure Python; the Monty dependency supplies platform-specific components.
A wheel filename ending in `any` does not imply Windows execution support.

For development from a checkout:

```sh
python -m pip install '.[dev]'
python -m pytest -q -rs
python examples/application_adapter.py
```

## Run a transformation

```python
from decimal import Decimal
from scriptspell import run

source = '''from decimal import Decimal
def transform(inputs):
    return {"eligible": inputs["vaf"] >= Decimal("0.05")}
'''
result = run(source, {"vaf": Decimal("0.049999999999999999")}, ["eligible"])
if result["outcome"] == "ok":
    assert result["values"] == {"eligible": False}
else:
    raise RuntimeError(result["outcome"])
```

Scripts define `transform(inputs)` and return a dictionary with exactly the requested
output names. Inputs and outputs use exact built-in dict/list/str/bool/int/None and
finite Decimal values. No implicit bytes/tuple/set/float/date/custom-object conversion
is performed on output. The application validates its own field types and business rules.

## Author a transformation with a model

```python
from scriptspell import prepare_authoring, validate_proposal

materials = prepare_authoring(
    task="Trim surrounding whitespace.",
    interface={"inputs": {"text": "string"}, "outputs": {"clean_text": "string"}},
    examples=[{"inputs": {"text": " example "},
               "outputs": {"clean_text": "example"}}],
)
# Your application sends materials["system"] and materials["user"] to its model.
# Use materials["response_schema"] where the provider supports structured output.
# Parse the model's response as JSON to obtain proposal, then:
# checked = validate_proposal(proposal)
```

A proposal has exactly four fields: `source`, `summary`, `assumptions` and
`unmet_requirements`. A static `ok` means the proposal passed shape and source policy
checks; it does not prove it runs or meets the task. The application checks unmet
requirements and assumptions, runs synthetic test cases through `run`, validates
contracts and expected results, and decides whether to save the source.

For a repair, call `prepare_authoring` again with the same task/interface and approved
`diagnostics`. The application owns the retry budget and the data sent to the model.
Context arguments must be JSON serializable. For exact Decimal examples, use an explicit
text representation and describe its type; do not convert precise numbers to floats.

[examples/application_adapter.py](examples/application_adapter.py) demonstrates this full
flow with an offline model stand-in. [The integration guide](docs/application-integration.md)
describes model dispatch, runtime outcomes, cancellation and AgentWiz responsibilities.

## Public API

Import from `scriptspell`; underscore modules and codec details are private.

| API | Purpose |
| --- | --- |
| `__version__` | Installed library version; independent of the language/profile identifier. |
| `profile()` | Fresh capability dictionary: profile, codec, dependency versions, limits and vocabulary. |
| `prepare_authoring(task, interface, examples=(), diagnostics=None)` | Versioned `system`/`user` prompts, profile and response schema; no dispatch or source execution. |
| `validate_proposal(proposal)` | Check proposal shape and source policy; returns an outcome dictionary. |
| `validate_source(source)` | Static source-policy check; no submitted code execution. |
| `run(source, inputs, output_names, *, limits=None, cancel=None)` | Synchronous invocation; accepted `values` exist only on `ok`. |
| `Limits(...)` | Smaller finite resource ceilings; invalid configuration raises `ValueError`. |

Both validation functions use the supervised helper and require a supported platform.
`run` rechecks source and enforces declared output names on every invocation.
Pass a `threading.Event` as `cancel`. An unconfirmed cleanup raises
`RuntimeError('cleanup_failed')`; later invocations in that process fail closed. Never
assume workers have stopped after this exception. Diagnostics omit source, values and
guest exception messages; callers must apply their own privacy policy to stored artifacts.

## Language and numerical contract

The `scriptspell-pure-v3` vocabulary includes internal sets/tuples/bytes, lambdas,
closures, defaults and annotations, exception handling, f-strings, unpacking and approved
imports from 14 pure-data modules. The [language catalogue](docs/language-profile.md)
lists tested APIs and receiver-specific caveats. Authoring prompts derive from this profile.
Classes, decorators, async, reflection, arbitrary imports, host access, float arithmetic,
true division and powers are excluded. This is a restricted Python-like language, not
an arbitrary Python script runner.

Integers are bounded to 14,280 bits; Decimal coefficients to 4,300 digits and absolute
exponents to 999,999. Decimal arithmetic uses precision 128 with Rounded and Inexact
traps: over-precision calculations fail. The caller's Decimal context is unchanged.
The strict guest/host codec rejects forged tags, duplicate keys, unsupported outputs,
cycles and excessive depth before potentially lossy conversion.

Defaults: source 64 KiB, typed input/output encoding 1 MiB, depth 32, 20,000 visited
nodes, interpreter allocation budget 64 MiB, execution 1 second and host wall deadline
5 seconds. Encoding overhead counts. Cleanup may add several seconds plus scheduling
overhead. Only smaller limits are supported; see `profile()` and `Limits`.

## Isolation and limitations

Every call starts a trusted driver and fresh Monty workers. Submitted code is never
executed by host CPython. The driver receives no inherited credential environment;
Monty receives no mounts, host functions or OS handlers. There is no runtime fallback,
network access by submitted scripts, telemetry, automatic retry, persistence or upgrade.
Install dependencies before use; execution never downloads them.

The native workers retain OS privileges. Monty's language implementation provides the
restriction; this is not an OS sandbox or certification for hostile multi-tenant use.
Interpreter allocation limits are not total RSS limits. On POSIX the driver attempts a
768 MiB address-space backstop and disables core dumps.

Passing static checks or example tests does not guarantee correctness. In particular,
scriptSpell cannot decide whether de-identification is complete or whether data is safe
to release to a cloud model. That decision belongs to the application and human review.

## Development and releases

[DEVEL.md](DEVEL.md) contains maintenance and release gates. CI runs the offline suite,
strict monitored feasibility checks and installed-wheel checks; reports are uploaded.
Actual Ubuntu WSL2 observations are a separate release obligation.

```sh
python -m pytest -q -m feasibility --strict-feasibility
python scripts/build_release.py --smoke
```

The release builder uses committed `HEAD`, verifies wheel contents/version/license,
installs into a fresh environment and exercises authoring, validation and execution.
It prints the wheel SHA-256. On a push to `main`, the release workflow runs the tests,
then publishes a new version's wheel and NEWS notes. There is no PyPI publication.

The optional repository-only OpenRouter experiment uses synthetic tasks and paid calls:

```sh
python scripts/check_authoring_openrouter.py --model provider/model --task trim
python scripts/check_authoring_openrouter.py --model provider/model --repairs 2
```

It prompts privately for a key or reads `OPENROUTER_API_KEY`; no key is saved.
The first command makes one request; the second allows at most 18. Inspect
`reports/authoring_openrouter.json`. Automatic CI never calls a model. A passing fixed
example set is an authoring usability observation, not a guarantee for other tasks.
