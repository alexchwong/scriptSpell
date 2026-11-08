# Application integration

scriptSpell owns a reusable transformation engine. The host application owns the user
experience, models, contracts, data policy and workflow. There is no callback into the
host from submitted code and no requirement to use AgentWiz or modelSpell.

## Responsibility boundary

| Concern | scriptSpell | Host application (including AgentWiz) |
| --- | --- | --- |
| Language | Tested vocabulary, generated authoring instructions, static source policy | Explain supported tasks; prevent promises of arbitrary Python support |
| Model authoring | `prepare_authoring` and `validate_proposal` | Choose role/provider/model; credentials, dispatch, response parsing, token caps and repair budget |
| Interface | Receives input dictionary and fixed output names; enforces names and supported value types | Own input/output schemas, required fields, semantics and business validation |
| Testing | Execute each supplied test through `run` | Supply cases and expected answers, check contracts/results; keep held-out answers out of repair prompts |
| Execution | Monty invocation, exact-value codec, limits, cancellation, worker cleanup | Admission/concurrency, UI background task, overall budgets and downstream routing |
| Privacy | No guest host capabilities; generic runtime diagnostics | Local-only labels, cloud eligibility, release Gate, approved prompt content, log redaction |
| Storage | None | Block IDs, revisions, source, descriptions, evidence, atomic publication and audit trail |

A prompt is not a security control. Only provide authoring context approved for the
selected model. Source itself can contain identifiers. A script's successful execution
must never remove a local-only restriction or grant permission for a cloud call.

## Authoring and repair lifecycle

1. Resolve the model role and authorize context before prompt preparation/dispatch.
2. Convert the host contract into a JSON-serializable `interface` description containing
   the expected input/output names and types. `interface` is explanatory context, not a
   schema dialect interpreted or enforced by scriptSpell. Explain special value encoding.
3. Call `prepare_authoring(task, interface, examples, diagnostics)`. It returns
   `prompt_version`, `profile`, `response_schema`, `system` and `user`.
4. Send the two prompt strings through the application's model client. With modelSpell,
   the host creates the endpoint/messages and calls `modelspell.complete`; scriptSpell
   does not choose providers or translate its schema into provider-specific settings.
   Use the returned JSON schema if supported; validate the reply regardless.
5. Parse the reply as a JSON object and call `validate_proposal`. Do not extract and
   execute arbitrary fenced text. Shape/source failure means the candidate is rejected.
6. Check `unmet_requirements` and review `assumptions`. Run the source on approved test
   inputs with `run`, check the host output contract and compare expected values.
7. For repair, provide bounded, approved diagnostics to a new `prepare_authoring` call.
   Its diagnostics argument is just context; the caller supplies any prior candidate
   source needed by the model. Each reply is a new untrusted proposal. Cap attempts and
   paid requests at the application layer. Do not include held-out answers in feedback.
8. Publish only when the application's review and tests pass. Store the exact source,
   interface, library/profile/codec versions and evidence with the chosen revision.
   A description or summary is metadata, not executable authority.

`prepare_authoring` performs no model call and serializes at most 131,072 context
characters. Non-JSON values raise the standard serialization exception; excessive
context raises `ValueError('authoring_limit')`. Decimal values in runtime inputs are
supported directly, but Decimal objects in prompt context must be represented explicitly
as strings with a type explanation. Do not silently coerce them to binary floats.

The proposal object must contain exactly `source` (string, at most 65,536 characters),
`summary` (string, at most 4,096 characters), `assumptions` and `unmet_requirements`
(lists of at most 20 strings, each at most 4,096 characters). Source also has a UTF-8
byte ceiling; multibyte text can pass the character ceiling and fail source validation.
`validate_proposal` does not reject a nonempty unmet-requirements list on its own.

## Executing a saved block

Load a specific revision and verify its engine/profile and host contracts. Pass the
source string, resolved input dictionary and declared output names to `run`. Names
must be a nonempty list/tuple of at most 100 unique nonempty strings, each at most
128 characters. Call in a background thread if the application uses an async UI/server;
scriptSpell is synchronous and does not manage an event loop.

Only read `values` when `outcome == 'ok'`. Recheck the host output schema and publish
all outputs atomically before allowing subsequent blocks to consume them. On every
other outcome, stop that step and leave its outputs unpublished. Never fall back to
host CPython execution after refusal or runtime failure.

| Outcome | Host handling |
| --- | --- |
| `ok` | Read `values` for `run`; validation success only for validation calls |
| `invalid_proposal` | Reject malformed authoring reply |
| `invalid_inputs` | Reject unsupported values or invalid output-name declaration |
| `source_rejected` | Show safe `issues` codes/lines; repair or reject source |
| `invalid_result` | Reject output shape/types or malformed guest export |
| `runtime_error` | Script failed; diagnose with approved synthetic inputs |
| `limit_exceeded` | Interpreter resource failure; simplify source/data |
| `deadline` | Wall/runtime deadline; stop step |
| `cancelled` | Mark cancelled; do not publish |
| `dependency_unavailable`, `platform_unavailable` | Fix deployment; do not switch execution engines |
| `worker_crash`, `cleanup_failed` | Fail step; inspect host health, block work when cleanup is unconfirmed |

Treat any unknown outcome as failure. Results do not all have the same keys: early
rejections may omit `elapsed` or `metadata`. Inspect optional fields with `.get()`.
`profile()` and normal helper results expose package/profile/codec provenance. A source
digest and effective limits are available in run metadata after source admission; they
are evidence, not correctness or privacy approval.

Pass a `threading.Event` via `cancel` and set it on Stop. A host timeout around a thread
alone does not cancel its workers. Signal cancellation and wait for `run` to finish
before releasing ownership of the task. Invalid `Limits` raises `ValueError`; failure
to confirm worker cleanup raises `RuntimeError('cleanup_failed')`, and subsequent
helper calls in that application process return `cleanup_failed`. Treat this as a host
health failure and restart the affected host process through the application's recovery
procedure. Do not retry execution or clear private library state to bypass it.

## AgentWiz adapter boundary

At the reviewed AgentWiz devel revision, `agentwiz/script_step.py` executes Python files
with JSON stdin/stdout through a subprocess supervisor. AgentWiz does not yet depend on
scriptSpell. Its existing script format is not the `transform(inputs)` interface and
must not be sent unchanged to Monty.

A consumer-side integration must add an explicit scriptSpell engine path, map block
contracts to named inputs/outputs, and route model authoring through the application's
model role and modelSpell client. Keep the workflow scheduler, block revision store,
local-only flags, release Gate, contract validation and publication in AgentWiz.
For scriptSpell calls, let scriptSpell own the Monty workers and cleanup; bridge Stop
using the cancellation event instead of wrapping them with a second process owner.
Existing arbitrary Python scripts require explicit rewriting or a separate engine path;
there is no compatibility fallback.

This change supplies the library-side contract and executable example. It does not
modify AgentWiz, migrate its stored blocks or certify that adapter. Test the pinned
candidate wheel in AgentWiz before publishing a coordinated integration release.

## Dependency and compatibility policy

Pin the release wheel URL/hash from its actual release notes and retain Monty's pinned
dependency. Never construct a hash or assume an unreleased wheel exists. For a Hatch
consumer with direct URL dependencies, add this to its pyproject:

```toml
[tool.hatch.metadata]
allow-direct-references = true
```

No modelSpell dependency is needed in scriptSpell itself.

`scriptspell.__version__` is the library SemVer release, `profile()['profile']` identifies
the language contract, `profile()['codec']` the exact-value protocol, and authoring
materials contain a separate `prompt_version`. Retain these independently. Revalidate
and retest saved source after engine/profile changes. Before 1.0, minor releases may
change public interfaces; patch releases preserve their call shape. Do not import
private worker, runtime, source-checker or codec functions from a consumer.
