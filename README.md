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

For development setup, offline pytest, live OpenRouter authoring and the optional
browser playground, see [DEVEL.md](DEVEL.md). The playground stays outside the product wheel.

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

A proposal has exactly six fields: `source`, `summary`, `assumptions`,
`unmet_requirements`, `example_input` and `expected_output`. Every response must include
code and both example dictionaries together; code-only proposals are rejected. The shared
production prompt preserves examples supplied in instructions or `examples` and generates
missing parts. `interface` is optional: `prepare_authoring("Trim surrounding whitespace.")`
infers names/types from the instructions. Supplied interfaces remain fixed.
Examples use JSON objects, arrays, strings, booleans, null and integers; use strings for
decimals and explicitly return strings for decimal results in JSON examples.

A static `ok` means the proposal passed shape and source policy checks; it does not prove it runs or meets the task. The application checks unmet
requirements and assumptions, runs the proposed example and independent synthetic test cases
through `run`, validates contracts and expected results, and decides whether to save the source.

The low-level helpers also accept caller-approved `diagnostics` for another request.
Use the revision workflow below for dedicated repair and expectation correction.
The application owns the request budget and the data sent to the model.
Context arguments must be JSON serializable. For exact Decimal examples, use an explicit
text representation and describe its type; do not convert precise numbers to floats.

[examples/application_adapter.py](examples/application_adapter.py) demonstrates this full
flow with an offline model stand-in. [The integration guide](docs/application-integration.md)
describes model dispatch, runtime outcomes, cancellation and AgentWiz responsibilities.

## Authoring workflow and local playground

The revision workflow uses a caller-supplied `dispatch(materials, settings)` function.
Send the system/user messages and response schema from `materials` using your provider
adapter. Return an object with `text`, `finish_reason` and `truncated` attributes, such
as a modelSpell completion result. scriptSpell itself needs no API key or model provider.
Settings are `model` plus optional `temperature` (0–2), `reasoning` (off, low, medium,
or high), and `max_tokens` (positive integer). Omitted settings use provider defaults.
The journal records requested settings. Provider application of those settings is unverified.

```python
from scriptspell import AuthoringSession

session = AuthoringSession("runs")
settings = {"model": "provider/model", "max_tokens": 4096}
revision = session.generate(None, dispatch, settings, "Trim text.", example_count=3)
reports = session.run(revision)
failed = [r["example_id"] for r in reports if r["status"] == "mismatch"]
if failed:
    attempt_id = session.improve(revision, dispatch, settings, failed)
    candidate = session.attempt(attempt_id)
    # After reviewing the candidate and its full suite results:
    # revision = session.decide(revision, attempt_id, True)
print(session.export(revision))
```

Generation requests Python and all 1–20 examples together, with one retry for a format error. Use `examples=[{"inputs":
..., "outputs": ...}]` for structured examples the workflow can verify against the
response. Supplied parts are preserved by value and incomplete pairs can be filled.
Examples embedded in prose rely on the model's interpretation. Expected outputs are
named objects, with `null` valid as a field value. Comparison is type-exact, ignores
object key order and preserves list order. Actual values appear only after successful
execution, and failure evidence can be sent to the model only by an explicit repair.

`session.correct(revision, dispatch, settings, example_id, guidance)` proposes one new
expected output. `session.decide(revision, attempt_id, True)` accepts it and reruns
the suite. Repair runs its candidate suite before acceptance and records regressions
against the preceding run. Passing, failing and rejected candidates can be inspected in
history. Use `session.edit` for a manual example edit, `session.snapshot` to inspect a
revision, and `session.restore(active_revision, selected_revision)` to create a fresh,
untested revision from a prior snapshot. Model proposals are bound to the active revision.

In a checkout with the development extra installed, run `python -m ui`. Use an OpenRouter
key from the environment or enter it in the page, load models and choose a preset or
enter an instruction. Presets offer easy, medium and hard guidance for the same task. Generate, review the examples, then run them. Use **Edit / correct**
to change a saved example or request a proposed expectation, or select failing cases
and use **Improve Python** to propose new code. **Save Python** exports the selected revision.

Each launch starts a new session. Its local `runs/<session-id>/journal.json` contains
drafts, attempts and test results. Exports use
`runs/<session-id>/<revision-id>/<export-id>/script.py` with adjacent `metadata.json`
recording revision and test status. OpenRouter credentials stay in memory. Use synthetic
data because model requests send task material to OpenRouter and the journal retains it.

To test the same presets in a batch, run from the checkout with the development extra
installed and `OPENROUTER_API_KEY` set in your environment.

```sh
python -m scripts.check_authoring_presets --list
python -m scripts.check_authoring_presets --difficulty all --dry-run
python -m scripts.check_authoring_presets --task 02 --model qwen/qwen3-coder-next --examples 3
python -m scripts.check_authoring_presets
```

The default batch runs 20 medium presets and generates three examples per proposal.
Generation retries a format error once, for up to 40 requests by default.
`--difficulty all` runs 60 variants, for up to 120 requests. Set temperature,
reasoning, token cap, timeout and report path with `--temperature`, `--reasoning`,
`--max-tokens`, `--timeout`, and `--report`. The default report is
`reports/authoring_presets.json`. Exit codes are 0 for PASS, 1 for FAIL, and 2 for BLOCKED.
A blocked provider or runtime stops the batch. A pass measures whether the generated
Python matches the model-generated expectations. The report includes both values for
review.

## Public API

Import from `scriptspell`; underscore modules and codec details are private.

| API | Purpose |
| --- | --- |
| `__version__` | Installed library version; independent of the language/profile identifier. |
| `profile()` | Fresh capability dictionary: profile, codec, dependency versions, limits and vocabulary. |
| `prepare_authoring(task, interface=None, examples=(), diagnostics=None)` | Versioned prompts/schema requiring code and examples together; no dispatch or source execution. |
| `generate_draft(dispatch, settings, instruction, …)` | One request for a draft with stable example IDs. |
| `run_examples(draft, *, cancel=None)` | Local Monty suite with typed expected/actual values and per-case status. |
| `correct_expected(…)`, `improve_python(…)`, `edit_example(…)` | Return revised drafts. Python repair also returns full candidate results. |
| `AuthoringSession(root="runs")` | Serialize revision edits, track model attempts and test results, and export Python. |
| `validate_model_settings(model, …)` | Validate provider-neutral authoring controls before dispatch. |
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

## Authoring compatibility

Version 0.2.0 changes the proposal shape (prompt version 4). Consumers of 0.1.x must accept
and retain `example_input` and `expected_output`, and update model stand-ins accordingly.
Use `list(proposal["expected_output"])` for inferred output names; when a host contract is
supplied, verify those names against it. Model dispatch remains the caller's responsibility.
The UI and headless applications use this same production contract.

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
