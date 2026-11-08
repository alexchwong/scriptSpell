# scriptSpell 0.1.0

Headless, restricted data transformations with exact values and authoring helpers. No AgentWiz or modelSpell dependency; no model calls, UI or server.

**Implementation candidate, not release-certified.** The suite and memory gate have been
observed on Linux x86_64 under CPython 3.10 and 3.13; the adversarial gate passes on 3.13
and one probe remains BLOCKED on 3.10. macOS Apple Silicon is still unverified. Do not treat
this as an OS sandbox or a certified boundary for hostile multi-tenant workloads.

## Install and use

```sh
python -m pip install .
python -m pip install '.[dev]'
python -m pytest -q
python probe_runtime.py
```

```python
from decimal import Decimal
from scriptspell import run

source = '''from decimal import Decimal
def transform(inputs):
    return {"eligible": inputs["vaf"] >= Decimal("0.05")}
'''
result = run(source, {"vaf": Decimal("0.049999999999999999")}, ["eligible"])
assert result["outcome"] == "ok"
assert result["values"] == {"eligible": False}
```

The public functions are `profile`, `validate_source`, `prepare_authoring`,
`validate_proposal` and `run`; `Limits` sets smaller finite resource ceilings.
`run` accepts a `threading.Event` as `cancel`. Results are dictionaries; accepted
`values` appear only for `outcome == 'ok'`. Generic diagnostics never include
source/data or guest exception messages. Invalid limit configuration raises
`ValueError`. An unconfirmed helper reap raises `RuntimeError('cleanup_failed')`.
Never catch that exception and assume workers have stopped.

Source checks are **static only**, not a compile or correctness guarantee.
Authoring helpers prepare versioned prompts and validate proposals without model
calls or source execution. The caller owns privacy, task contracts, storage,
model dispatch and atomic publication. The manual OpenRouter experiment lives
outside the product package.

## Automated feasibility checks

After installing `.[dev]`, ordinary pytest includes both monitored checks:

```sh
python -m pytest -q -rs
python -m pytest -q -m feasibility --strict-feasibility
```

They write `reports/memory.json` and `reports/adversarial.json`. Missing process
observations are skipped/BLOCKED in ordinary pytest and fail in strict mode.
CI uses strict mode. The optional check_memory.py/check_adversarial.py wrappers
remain available and call the same implementations.

## Manually test authoring

```sh
python check_authoring_openrouter.py --model provider/model --task trim
python check_authoring_openrouter.py --model provider/model --repairs 2
```

Replace provider/model with your model ID. The runner prompts privately for an
OpenRouter key or reads OPENROUTER_API_KEY, uses synthetic tasks, and tests valid
proposals through Monty. The first command uses one paid request; the second
allows at most 18. Inspect reports/authoring_openrouter.json for generated source,
validation, visible/held-out correctness, attempts, timing and token usage.
No API key is saved. Normal pytest and automatic CI never call OpenRouter.
PASS means the supplied tasks passed; it is not a general claim about every authoring job.


## Language and values

Define `transform(inputs)` and return exactly the declared output names.
The audited `scriptspell-pure-v3` vocabulary includes internal sets/tuples/bytes,
lambdas, closures, helper defaults and annotations, exception handling, f-strings,
unpacking and approved imports from 14 pure-data modules. Read
[docs/language-profile.md](docs/language-profile.md) for the complete tested catalogue and
receiver-specific caveats; the authoring prompt is derived from this same profile.

Every advertised builtin, data attribute and imported member has an executable
compatibility fixture for Monty 1.5.0. Familiar names are not assumed compatible:
several CPython APIs are missing or differ. Classes, decorators, async, namespace
reflection/mutation, arbitrary imports, guest host-access capabilities, float
math, true division and powers remain excluded. Imported modules are restricted
to qualified approved members. CSV readers are direct-call/string-mode only.

Inputs/results are exact built-in dict/list/str/bool/int/None or finite Decimal.
No implicit bytes/tuple/set/float/date/custom-object output conversion. Integers are bounded to
14,280 bits (conservative transport limit); Decimal coefficients to 4,300 digits
and absolute exponents to 999,999. Decimal arithmetic uses precision 128 with
Rounded and Inexact traps; over-precision calculations fail. The caller's Decimal
context is unchanged. Submitted bindings are isolated from the trusted encoder. The strict guest/host
codec rejects forged tags, duplicate keys, unsupported results,
cycles and excessive depth before Monty's potentially lossy conversion.

Defaults: source 64 KiB, typed input/output encoding 1 MiB, depth 32, 20,000
visited nodes, interpreter allocation budget 64 MiB, execution 1 second, host
wall deadline 5 seconds. Serialization overhead counts: accepted text can be
smaller than 1 MiB. Cleanup adds up to 2 seconds plus scheduling overhead.
Only smaller limits are supported in this version.

Each call starts a trusted Python driver and fresh Monty workers. The submitted
program is never evaluated by host CPython. The driver has no inherited
credential environment, uses a fixed installed binary, and is killed/reaped on
cancellation/deadline. Monty receives no mounts, host functions or OS handlers.
The native processes retain OS privileges; isolation is provided by Monty's
language implementation. Interpreter allocations are not total RSS. On POSIX,
the driver attempts a 768 MiB address-space backstop and disables core dumps;
this is not a hard RSS guarantee. Windows execution is refused.

The core library has no automatic runtime fallback, network calls, telemetry, result logging,
persistence, retries or upgrades. No repository hosting or PyPI name reservation
is implied. Install dependencies before use; execution never downloads them.

## Build

```sh
python -m build --no-isolation
```

Tests use synthetic fixtures. The GitHub workflow runs on push and pull request,
builds the wheel, installs it, and tests from outside the source directory.
Both feasibility pytests run in CI and their reports are uploaded; they also pass
locally under `--strict-feasibility` on WSL2. Real-model authoring is tested manually.

Reinstall after applying
profile changes: `python -m pip install '.[dev]'`.
