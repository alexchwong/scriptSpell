# Application integration

scriptSpell owns a reusable transformation engine. The host application owns the user
experience, models, contracts, data policy and workflow. There is no callback into the
host from submitted code and no requirement to use AgentWiz or modelSpell.

## Responsibility boundary

| Concern | scriptSpell | Host application (including AgentWiz) |
| --- | --- | --- |
| Language | Tested vocabulary, generated authoring instructions, static source policy | Explain supported tasks; prevent promises of arbitrary Python support |
| Model authoring | Prompts, bounded format corrections, completion checks and draft validation | Choose role, endpoint and options; authorize each dispatch and own credentials, request limits and spending |
| Interface | Receives input dictionary and fixed output names; enforces names and supported value types | Own input/output schemas, required fields, semantics and business validation |
| Testing | Execute each supplied test through `run` | Supply cases and expected answers, check contracts/results; keep held-out answers out of repair prompts |
| Execution | Monty invocation, exact-value codec, limits, cancellation, worker cleanup | Admission/concurrency, UI background task, overall budgets and downstream routing |
| Privacy | No guest host capabilities; generic runtime diagnostics | Local-only labels, cloud eligibility, release Gate, approved prompt content, log redaction |
| Storage | None | Block IDs, revisions, source, descriptions, evidence, atomic publication and audit trail |

A prompt is not a security control. Only provide authoring context approved for the
selected model. Source itself can contain identifiers. A script's successful execution
must never remove a local-only restriction or grant permission for a cloud call.

## Authoring and repair lifecycle

Use the authoring workflows with a dispatcher that authorizes the actual messages
on every call, including format corrections and repair prompts with prior source or
test evidence. Resolve the model role and per-run settings in the caller.

```python
from scriptspell import generate_draft, model_messages

def dispatch(materials, settings):
    messages = model_messages(materials)
    authorize_and_admit(messages, materials["request_context"])
    return modelspell.complete(endpoint, model, messages, cancel=cancel, **resolved_options)

draft = generate_draft(dispatch, {}, "Trim text.")
```

`request_context` has `stage` and one-based `attempt` values. A format correction
increments the content attempt. A transport attempt belongs to the same content attempt.
For prebound dispatch use empty per-call settings. A mapping with `model` and only
the keys `model`, `temperature`, `reasoning` and `max_tokens` uses the legacy
`validate_model_settings()` helper. Other maps reach the dispatcher with their
keys and values intact.

Return a completion with `text`, `finish_reason` and `truncated`. A normal
completion requires `finish_reason="stop"` and no truncation. With native LM Studio,
preserve `transport="lmstudio_native"` to allow a successful reply with
`finish_reason=None`. The native truncation heuristic requires an output token cap
and a usable provider token count. Without that signal, valid native content can
be accepted. Propagate cancellation with its partial result attached to the error.

For standalone use, bind an endpoint and model ID or the discovered `ModelInfo`.

```python
from scriptspell.modelspell_adapter import make_dispatch

dispatch = make_dispatch(endpoint, model, options={"temperature": 0, "max_tokens": 4096},
                         cancel=cancel)
draft = generate_draft(dispatch, {}, "Trim text.")
```

The factory imports optional modelSpell when called and snapshots option containers
before offline preflight. The current candidate uses `check_completion()`. The
published 0.3.0 pin uses `check_settings()` and checks the JSON encoding of a
non-null provider policy at binding. With that pin the SDK checks the model argument
and timeout before sending. For OpenRouter pinning, authorize and resolve selection
using the [modelSpell selection example](https://github.com/alexchwong/modelSpell/blob/7e23d9d15076e53336f556bffebe83341a6ee9b3/examples/batch_selection.py)
and pass `selection.policy` as `options["provider"]`. Use a caller-owned dispatcher
for retry controls and backend-specific `extra` fields. The playground and paid
preset and staged CLIs use Managed routing and zero transport retries.

The manual proposal API remains available for applications that own the full
authoring loop.

1. Resolve the model role and authorize context before prompt preparation/dispatch.
2. If a host contract is available, convert it into a JSON-serializable `interface` description containing
   the expected input/output names and types. `interface` is explanatory context, not a
   schema dialect interpreted or enforced by scriptSpell. Explain special value encoding.
   Otherwise omit it: names and types are inferred from the instructions and examples.
3. Call `prepare_authoring(task, interface, examples, diagnostics)`. It returns
   `prompt_version`, `profile`, `response_schema`, `system` and `user`.
4. Send the two prompt strings through the application's model client. With modelSpell,
   the host creates the endpoint/messages and calls `modelspell.complete`; scriptSpell
   does not choose providers or translate its schema into provider-specific settings.
   Use the returned JSON schema if supported; validate the reply regardless.
5. Parse the reply as a JSON object and call `validate_proposal`. Do not extract and
   execute arbitrary fenced text. Shape/source failure means the candidate is rejected.
6. Check `unmet_requirements` and review `assumptions`. Review the returned example input
   and expected output, then execute the example through `run`. Add independent approved test
   inputs with `run`, check the host output contract and compare expected values.
   Expected answers generated alongside code are not independent proof of correctness.
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
(lists of at most 20 strings, each at most 4,096 characters), plus `example_input` and
`expected_output` dictionaries. These are required in the SAME model response as source,
in the product API and developer UI alike. Code-only replies are rejected. The production
prompt preserves any example values supplied in the task or `examples`, generating missing
parts. Context `examples` continue to use the existing `inputs`/`outputs` pair format.

Each returned example contains only exact JSON dictionaries/lists/strings/booleans/null/integers,
with depth at most 32, at most 20,000 visited values, integer bit length at most 14,280 and
at most 131,072 serialized characters. Floats, Decimal objects and custom objects are refused.
Use decimal strings and explicitly convert calculated decimal results to strings for examples.
`expected_output` has 1–100 nonempty names, each at most 128 characters. Use those names for
`run` when inferring an interface; check against fixed names when the host supplied a contract.
The validator checks shape/source without executing or certifying the example's correctness.

Version 0.2.0 / prompt version 4 replaces the four-field 0.1.x proposal. Update consumer
parsers, fixtures and persistence to retain both examples; do not strip them before validation.
Source also has a UTF-8 byte ceiling; multibyte text can pass the character ceiling and fail source validation.
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

The initial Workshop integration uses the injected path. On each send, check locality,
authorization, Stop and request admission against the actual messages. Use zero
paid probes and zero transport retries, with Managed routing or an existing provider
mapping under the modelSpell 0.3.0 pin. The Manual and Automatic selector APIs are
outside the initial Workshop integration.

AgentWiz owns the scheduler, block revisions, local-only flags, release Gate, contract
validation and publication. Map an explicit scriptSpell engine path to named inputs
and outputs and let scriptSpell own its Monty workers and cleanup. Bridge Stop using
the cancellation event. Existing arbitrary Python scripts need explicit rewriting or
a separate engine path. Verify the pinned wheel in AgentWiz for a coordinated release.

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
