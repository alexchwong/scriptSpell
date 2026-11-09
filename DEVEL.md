# Coding-agent development and maintenance directives

Read this file before changing the repository. It owns agent workflow, maintenance policy
and **what belongs in each document**. `.clinerules` defines the handover-review workflow;
do not change it without explicit owner instruction.

## Quick start

Run from the repository root on Linux, macOS or Ubuntu WSL2 (native Windows execution is unsupported):

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q -rs
```

Work only in this checkout's `.venv`; never use system or conda Python for development.
Use `python -m pytest`, never bare `pytest`. Never commit `.venv/`, reports or API keys.
Installation downloads dependencies; pytest itself makes no hosted API or model calls,
even if `OPENROUTER_API_KEY` is set. Process-observed checks can report BLOCKED skips;
use `python -m pytest -q -m feasibility --strict-feasibility` when strict observation is required.
Editable installs use current source; reinstall when dependencies or package metadata change.

### OpenRouter live authoring quick start

```bash
. .venv/bin/activate
python scripts/check_authoring_openrouter.py --list
python scripts/check_authoring_openrouter.py --model qwen/qwen3-coder-next --task trim --repairs 0
# Optional full six-task battery: at most 18 paid requests, 4096 output tokens each.
python scripts/check_authoring_openrouter.py --model qwen/qwen3-coder-next --repairs 2
```

The runner reads `OPENROUTER_API_KEY` or prompts privately; it never saves the key.
The trim command allows one paid request. Set `--model` to the desired OpenRouter slug.
Inspect `reports/authoring_openrouter.json`: exit 0 is PASS, 1 FAIL, 2 BLOCKED.
A blocked or unrun check is never a pass. Live model calls are manual and excluded from CI.

The separate preset batch runner (`python -m scripts.check_authoring_presets --dry-run`)
uses the playground catalog, modelSpell adapter and public generation/test functions.
Keep it opt-in and use mocked completions in automated tests. The six-task runner above
uses fixed visible and held-out answers, while preset batches test generated cases.

### Developer playground

```bash
. .venv/bin/activate
python -m ui                       # opens a local browser page
python -m ui --no-browser          # prints the token-protected URL
```

Run the playground from the checkout. Keep `ui/` out of the wheel and sdist.
The browser uses the public `AuthoringSession` workflow. The adapter uses pinned
modelSpell 0.3.0 for discovery, setting checks and dispatch. The library imports
neither UI nor model transport. Blank generation settings use provider defaults.
Model requests have a 120-second timeout. Generation retries a format error once. It does not
execute code. Accepted corrections and proposed repairs run the suite in Monty.

The server binds only to 127.0.0.1 and checks a per-launch token and local Host/Origin.
Keep provider keys in process memory and out of browser storage, journals and exports.
Store each revision session in its generated, ignored `runs/` directory. Keep exact
integers in server-formatted JSON strings at the browser boundary. Actual Decimal values
use a display marker and are compared in the library before formatting.

Serialize edits, persist journal changes atomically, and guard every accept against its
origin revision. Do not overwrite prior exports. Closing the server cancels active
model/runtime work and joins handlers without bypassing Monty cleanup ownership.

## Workflow and testing

Inspect actual changes and preserve uncommitted work. Keep corrections within the agreed
scope; no unrelated refactoring. Do not commit, push, merge, tag or publish without instruction.
Verify handover claims; report checks actually passed, failed or blocked and the tested platform.
Add tests for functional changes and boundary regressions, not documentation or file wording.
Keep offline tests deterministic, with synthetic fixtures and fake model responses.
Never weaken a check to obtain a pass. Keep README user-facing and maintenance detail here.

## Documentation ownership and placement

| Document | Put here | Keep out |
| --- | --- | --- |
| `README.md` | User installation, API use, limits, numerical contract, supported platforms and current limitations. | Agent policy, release-gate procedure, dated measurement results. |
| `DEVEL.md` | Standing directives agents need to develop and maintain the repository; essential setup and check commands; release gates. | User instructions, detailed language/API inventories, historical decisions and build logs. |
| `NEWS.md` | Concise user-visible changes, grouped by release. | Internal maintenance narratives, test logs, fixture counts and owner procedures. |
| `docs/language-profile.md` | The tested language contract: constructs, approved imports and modules, receiver-specific examples and exclusions. | Policy, history, release sign-off and dated evidence. |

Before adding documentation, classify its audience and purpose and update the owning
document. Merge with existing coverage rather than copying it. A directive issued by the
owner still belongs here if it governs agent work. Keep this file concise and imperative:
add a directive only when it changes what an agent must or must not do. Update the owning
document in the same change as behaviour, layout, commands or tests.

Do not add `HANDOVER.md`, `PROPOSAL.md` or `FEASIBILITY.md`. Current task state belongs in
the issue or pull request, measured evidence belongs in `reports/*.json` and the CI
artifacts, and release obligations belong in [Release gates](#release-gates). Never restate
a measurement as prose: a date-stamped evidence narrative is stale as soon as the next run
finishes.

## Standing directives

Keep the public API headless and independent of consumers. Source is data until Monty
executes it; never add host exec/eval or a CPython fallback. Capability configuration is
private. Changes to AST policy, guest codec, numeric semantics, limits or Monty versions
require corresponding boundary regression tests.

`source.check` and `_guest.SUPPORT` are private trusted worker components, not public
bypasses. The reserved `_ss_` namespace and builtin names cannot be rebound by submitted
code. The entire result is encoded inside the guest before export. `runtime` owns the
invocation process group. Avoid subprocess monkeypatches in lifecycle tests; cancellation
and deadlines must exercise actual workers.

Submitted declarations run inside `_ss_invoke_user`. Never concatenate submitted
definitions into the trusted encoder's global namespace: a submitted name that shadows a
builtin used by the encoder can corrupt exported types. The isolation must hold even when
the static filter is bypassed, and a fixed test-only fixture proves it. Build the wrapper
from the validated syntax tree rather than re-indenting raw text, so multiline string,
bytes and f-string contents survive; keep the literal-preservation regressions.

The private decoder independently validates tag shape, arity and scalar types, and must not
assume a well-formed outer list has honest contents. Reject unknown names and
dynamic/reflection aliases, check modules against their own member lists, keep CSV
string-only, and never let imported module values flow around the member guard.

Every profile name requires a fixture in `tests/profile_cases.py`. The catalogue shows
tested receivers; do not assume an API on Decimal exists on int. Monty upgrades must rerun
these probes, including from-import aliases and the namespace isolation regression. Update
`docs/language-profile.md` for vocabulary changes; authoring instructions must remain
derived from `profile()`.

Keep model transport outside the product library. Preserve the version 4 single-example
prompt and proposal shape for existing consumers. The revision workflow also supports
count-specific multi-example generation, correction and repair. All prompt construction,
validation, comparisons and revision semantics belong in the library. Update the public
workflow and UI together when these contracts change. The
development-only OpenRouter runner uses stdlib HTTPS directly at the owner's request. It is
not imported by the product and never runs during automatic CI. API contract:
https://openrouter.ai/docs/api-reference/chat-completion. Use synthetic fixtures only, cap
calls, and keep hidden answers out of repairs.

The tests do not prove the absence of all interpreter vulnerabilities, and passing fixed
attacks does not certify OS isolation. Publication requires the observed gates below.

## Environment and required commands

After the quick-start setup, run the offline suite:

```sh
python -m pytest -q -rs
```

Use the editable installation above for source changes. For a non-editable installation,
reinstall after changing the profile, source policy, guest codec or limits to avoid stale code.

The two monitored feasibility checks are ordinary pytest tests that write
`reports/memory.json` and `reports/adversarial.json`. Missing process observations are
skipped as BLOCKED in ordinary pytest and fail under strict mode:

```sh
python -m pytest -q -m feasibility --strict-feasibility
```

The optional `scripts/check_memory.py` and `scripts/check_adversarial.py` wrappers call the same
implementations and need the `dev` extra for `psutil`; they are repository tooling, not
part of the product wheel. `scripts/_feasibility_case.py` and `scripts/feasibility_support.py` are private
test drivers. `scripts/authoring_jobs.py` holds the synthetic authoring tasks; hidden cases never
enter model requests or repair feedback.

Run repository tools from the repository root after installing the project as above:

```sh
python scripts/check_memory.py
python scripts/check_adversarial.py
python examples/runtime_roundtrip.py
```

The developer UI lives in `ui/`; development commands and their private helpers live in
`scripts/`; runnable consumer demonstrations live in `examples/`. None of these directories is shipped in the product wheel.

Never bypass process-identity verification and never mark an unobservable measurement PASS.
Identity is confirmed by sampling argv for the exact script path and the per-launch token
until the child has exec'd, because a single sample can catch the still-forked parent's
image and mislabel a live child as unobservable. Do not reduce that to one sample.

## Release gates

Do not describe a version as release-certified without its observed gates. A gate is observed, not inferred, and BLOCKED is
never a pass. Record the platform and Python version with every observation.

| Gate | Requirement before publication |
| --- | --- |
| F1 packages/platforms | Observed runs on Linux x86_64, macOS Apple Silicon and actual Ubuntu WSL2, on Python 3.10 and 3.13. |
| F2 capabilities | Automated adversarial report on an observable platform: host file, environment, process, socket and DNS access refused. |
| F3 resources/lifecycle | Automated memory and process-tree report on an observable platform: thresholds observed, allocation refused, deadline and cleanup verified. |
| F4 exact values | Integer, Decimal and strict-export regressions repeated on the required matrix. |
| F5 source/API/package | Source validation stays nonexecuting; the wheel installs and tests from outside the checkout on the required matrix. |

CI runs strict feasibility on push and pull request and uploads the JSON reports, but a
workflow definition is not proof that a remote job ran. Real-model authoring quality is a
separate, manually measured usability result: run `scripts/check_authoring_openrouter.py` with a
model and key, and keep its report. Sampled RSS may miss short peaks, summed RSS
double-counts shared pages, and the monitor thresholds are observations with a kill
backstop, not kernel-enforced limits.

Release tooling must run on every supported patch release, not just the interpreter used
locally. Gate standard-library features by capability (`hasattr(tarfile, "data_filter")`)
rather than by minor version: `pyproject.toml` supports all of Python 3.10, but `tarfile`'s
extraction filter only arrived in 3.10.12, and a runner can resolve `3.10` to 3.10.11.
`build_release.py` therefore extracts with `filter="data"` where available and validates
members itself where it is not. Run `python scripts/build_release.py --smoke` on more than one
interpreter before claiming the wheel can be released.

## Versioning and wheel releases

`scriptspell/_version.py` is the single library version source, in `X.Y.Z` form.
Hatch metadata, `scriptspell.__version__` and `profile()['version']` must agree.
Profile, codec and authoring prompt identifiers are separate compatibility contracts.
Use patch versions for compatible fixes; document public interface changes in minor
versions before 1.0. Add a matching `## X.Y.Z` heading to NEWS.

Develop on `devel` or a task branch; merge an authorized, tested release candidate to `main`.
Push/PR CI runs offline and strict feasibility tests and
builds, verifies and smoke-tests the installed wheel. `tests.yml` is also reusable by
the release workflow. Do not add live-model calls to either workflow.

`python scripts/build_release.py --smoke` builds from **committed HEAD**, never the
working tree. It checks exact package contents, version/license metadata and NEWS;
installs the wheel and its dependencies in a fresh environment; and tests authoring,
validation and real execution outside the checkout. Dependency installation may need
index access. Use `python -m build --wheel` for an uncommitted development wheel.
Only the package, license and distribution metadata ship in the release wheel.

`release.yml` follows modelSpell: a main push (or manual dispatch on main) runs CI,
then creates a GitHub release `vX.Y.Z` with the wheel, NEWS section and hashed install
URL. It does not publish to PyPI. An existing release is left intact; changed shipped
files require a version bump. Documentation outside README, tests and tooling alone
need no bump. A pre-existing tag for a new release must resolve to the tested commit.

Before merging a new version to main, complete F1–F5 above, including actual WSL2
observations, and test the committed candidate wheel in any coordinated consumer.
Automation cannot supply the WSL2 observation or certify a downstream adapter. Do not
replace a published wheel; fix defects in a new patch release. Never commit generated
dist files or reports. Keep integration examples consumer-neutral and offline.
