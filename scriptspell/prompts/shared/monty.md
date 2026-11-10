At module level use only approved imports and function definitions.
Use only the builtins, data attributes and module members in the following language profile.
Approved import aliases and from-imports work.
Imported modules must be used through their qualified members, not stored/passed as values.
Internal sets, tuples, bytes, dates, iterators and specialised containers are allowed; convert them explicitly to supported output types.
Lambdas, closures, callbacks, defaults, annotations, try/except/else/finally, assertions, f-strings, assignment expressions, data-only match patterns and unpacking are supported.
Use user-defined functions/lambdas as callbacks; builtin methods must be called directly.
No classes, decorators, with, async, yield, del, global/nonlocal, reflection, dynamic evaluation, host tools/files/network, print or clock reads.
Finite floats and true division are supported. No complex values or powers.
Use Decimal strings and exact operations; rounding traps apply.
Do not rebind builtins, use names containing double underscores, or access the reserved _ss_ namespace.
Never change contracts, limits, privacy or model selection.
