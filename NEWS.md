# NEWS

## 0.1.0

- Fixed large-input transport stalls on older CPython releases, observed on macOS Python 3.10–3.12. Subprocess communication now uses one supervised call while preserving cancellation, deadlines and fail-closed cleanup.

- Headless restricted data transformations: submit a `transform(inputs)` script and receive exactly the declared output names. No model calls, UI or server.
- Submitted source runs in the pinned Monty interpreter and is never evaluated by host CPython. There is no runtime fallback.
- Results are dictionaries. Accepted `values` appear only when the outcome is `ok`.
- Exact integers and finite Decimal values survive transport unchanged. Lossy or unsupported guest results are refused, never stringified.
- Integers are bounded to 14,280 bits; Decimal coefficients to 4,300 digits and absolute exponents to 999,999.
- Decimal arithmetic uses precision 128 with Rounded and Inexact traps, so an over-precise calculation fails instead of rounding silently. Your own Decimal context is left unchanged.
- The source checker is static: it reports problems without compiling or running anything, and is not a correctness guarantee.
- A tested pure-data language subset: internal sets, tuples and bytes, lambdas, closures, helper defaults and annotations, exception handling, f-strings, unpacking, and approved imports from 14 pure-data modules.
- `isinstance` is available for data checks. Reflection, `eval`, `exec`, host I/O, classes, decorators, async, float maths and true division are not.
- Familiar names are not assumed compatible. APIs missing from the pinned runtime are listed in the documentation instead of being advertised.
- Every call uses fresh workers with execution and wall-clock deadlines, cancellation through a `threading.Event`, and a cleanup check that fails loudly rather than assuming workers stopped.
- Diagnostics never include source, input data or guest exception messages.
- Authoring helpers prepare a versioned prompt and validate a returned proposal without calling a model or running source. Dispatch, storage and publication stay with the caller.
- Fixed a result-type validation bypass: submitted code could shadow builtins used by the trusted encoder and publish an unsupported value as an accepted output. Submitted declarations now occupy a separate namespace, and transport tags are validated independently on the host.
- Multiline string, bytes and f-string contents are preserved when the invocation is wrapped, because the wrapper is built from the validated syntax tree rather than by re-indenting text.
- Requires the pinned Monty runtime (pydantic-monty 1.5.0). Windows execution is refused.
- AgentWiz integration is deferred to a later release.
