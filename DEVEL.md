# Coding-agent development and maintenance directives

Read this file before changing the repository. It owns agent workflow, maintenance policy
and **what belongs in each document**.

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

Authoring helpers are included; model transport remains outside the product library. The
development-only OpenRouter runner uses stdlib HTTPS directly at the owner's request. It is
not imported by the product and never runs during automatic CI. API contract:
https://openrouter.ai/docs/api-reference/chat-completion. Use synthetic fixtures only, cap
calls, and keep hidden answers out of repairs.

The tests do not prove the absence of all interpreter vulnerabilities, and passing fixed
attacks does not certify OS isolation. Publication requires the observed gates below.

## Environment and required commands

Install the development extra, then run the offline suite:

```sh
python -m pip install '.[dev]'
python -m pytest -q -rs
```

Reinstall after changing `profile.py`, `source.py`, the guest codec or the limits, so a
previously installed copy cannot supply an old profile to the tests or the manual runner.

The two monitored feasibility checks are ordinary pytest tests that write
`reports/memory.json` and `reports/adversarial.json`. Missing process observations are
skipped as BLOCKED in ordinary pytest and fail under strict mode:

```sh
python -m pytest -q -m feasibility --strict-feasibility
```

The optional `check_memory.py` and `check_adversarial.py` wrappers call the same
implementations and need the `dev` extra for `psutil`; they are repository tooling, not
part of the product wheel. `_feasibility_case.py` and `feasibility_support.py` are private
test drivers. `authoring_jobs.py` holds the synthetic authoring tasks; hidden cases never
enter model requests or repair feedback.

Never bypass process-identity verification and never mark an unobservable measurement PASS.
Identity is confirmed by sampling argv for the exact script path and the per-launch token
until the child has exec'd, because a single sample can catch the still-forked parent's
image and mislabel a live child as unobservable. Do not reduce that to one sample.

## Release gates

Do not describe 0.1.0 as release-certified. A gate is observed, not inferred, and BLOCKED is
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
separate, manually measured usability result: run `check_authoring_openrouter.py` with a
model and key, and keep its report. Sampled RSS may miss short peaks, summed RSS
double-counts shared pages, and the monitor thresholds are observations with a kill
backstop, not kernel-enforced limits.
