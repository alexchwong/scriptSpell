# scriptSpell language profile

Profile: **scriptspell-pure-v3**. Runtime: **pydantic-monty/client/runtime 1.5.0**.

## Scope

This is a tested pure-data subset of Monty, not a claim of unrestricted CPython compatibility. Validation is static-only; argument types, runtime errors and resource limits are checked on explicit Test/Run. Host Python must also parse the submitted source, so syntax acceptance is constrained by the installed Python version.

Input/output values remain concrete dicts with string keys, lists, strings, booleans, integers, finite Decimal and None. Internal sets, tuples, bytes, iterators, dates and specialised containers are allowed, but must be explicitly converted before return. Unsupported nested output values fail; they are never automatically stringified.

## Constructs

functions and closures, lambda, literal and computed function defaults, annotations, loops and conditions, assignment expressions, data-only structural matching, try/except/else/finally, assert, f-strings, list/dict/set comprehensions, eager generator expressions, starred unpacking, integer bit operations.

Additional details: module-level imports and function declarations only; nested helper functions and closures; helper parameters may have defaults, annotations, positional/keyword and variadic forms. The entry point remains exactly transform(inputs). Data-only match patterns include mappings, sequences, OR/as patterns and guards; class patterns are excluded. Regular private names and the throwaway underscore are allowed. The _ss_ namespace and double-underscore names are reserved. Builtins cannot be rebound.

Classes, decorators, with, async, yield, deletion, namespace mutation, reflection, dynamic evaluation, host access and clock reads are excluded. Floats, complex values, true division and powers remain outside the exact-value policy. Decimal context changes are unavailable.

## Caveats

- Internal bytes, tuples, sets, iterators, dates and specialised containers must be converted before return.
- Generator expressions and regex finditer are eagerly materialised by Monty.
- Builtin methods generally cannot be stored or passed as callbacks; use lambdas or user functions. Approved imported module functions can be used as callbacks, except CSV readers, which require direct calls.
- Imported modules themselves cannot be stored or passed as values.
- Integer objects have no exposed methods/attributes; as_integer_ratio/conjugate/real/imag are Decimal-only.
- CSV readers require direct calls and no **kwargs. Quoting must be default or a literal/string-preserving mode 0/1/3 (or the qualified approved constants); keyword unpacking and QUOTE_NONNUMERIC are excluded.
- bytes(iterable_of_ints) is unsupported; use text.encode, bytes(text, encoding), bytes(existing_bytes) or bytes(length).
- Regex: finditer is eager and ASCII flags have no effect. Callable replacement functions, Pattern positional range arguments, Match.expand/lastindex/lastgroup and re.subn are unavailable. Engine and replacement-template behaviour differ from CPython, so do not use re.ASCII as an ASCII-only guarantee; use explicit ASCII character classes instead.
- True division, powers and binary floating point are outside this exact-value profile.
- Decimal arithmetic uses precision 128 and traps Rounded/Inexact.
- Sets have Monty-specific ordering; do not rely on CPython set iteration order. Introspection, identity and hash functions are intentionally excluded.

## Excluded after negative probes

These names are familiar from CPython but absent in the pinned Monty 1.5.0 build, so they are not advertised. Each was removed after a direct probe rather than assumed:

- int object methods and properties: bit_count, bit_length, numerator, denominator, to_bytes, from_bytes.
- str.format_map, str.maketrans, str.translate.
- set.intersection_update, set.difference_update, set.symmetric_difference_update.
- date.fromordinal, date.toordinal, date.isocalendar; datetime.fold.
- defaultdict.default_factory.
- re.subn; re.U/UNICODE and re.X/VERBOSE; Match.expand, Match.lastindex, Match.lastgroup.
- unicodedata.decimal, unicodedata.digit; the UnicodeError constructor.

Some names failed initially only because the probe used the wrong receiver. as_integer_ratio, conjugate, real and imag exist on Decimal, not on int, and the catalogue below states the tested receiver. bytes(text, encoding), bytes(existing_bytes) and bytes(length) work, whereas bytes(iterable_of_ints) does not.

## Approved imports

| Module | Available members |
| --- | --- |
| `decimal` | `Decimal`, `InvalidOperation`, `DivisionByZero`, `Inexact`, `Rounded` |
| `re` | `compile`, `escape`, `search`, `match`, `fullmatch`, `split`, `findall`, `finditer`, `sub`, `I`, `IGNORECASE`, `M`, `MULTILINE`, `S`, `DOTALL`, `A`, `ASCII`, `NOFLAG`, `error` |
| `datetime` | `date`, `datetime`, `timedelta`, `timezone` |
| `unicodedata` | `normalize`, `category`, `combining`, `name`, `lookup` |
| `math` | `gcd`, `lcm`, `isqrt`, `factorial`, `comb`, `perm`, `floor`, `ceil`, `trunc` |
| `itertools` | `chain`, `islice`, `repeat`, `cycle`, `count`, `accumulate`, `product`, `permutations`, `combinations`, `combinations_with_replacement`, `compress`, `dropwhile`, `takewhile`, `filterfalse`, `starmap`, `zip_longest`, `groupby`, `tee` |
| `functools` | `reduce`, `partial` |
| `collections` | `Counter`, `defaultdict`, `deque` |
| `bisect` | `bisect`, `bisect_left`, `bisect_right`, `insort`, `insort_left`, `insort_right` |
| `copy` | `copy`, `deepcopy` |
| `fnmatch` | `fnmatch`, `fnmatchcase`, `filter`, `translate` |
| `hashlib` | `md5`, `sha1`, `sha224`, `sha256`, `sha384`, `sha512`, `sha3_224`, `sha3_256`, `sha3_384`, `sha3_512`, `blake2b`, `blake2s`, `shake_128`, `shake_256` |
| `base64` | `b64encode`, `b64decode`, `standard_b64encode`, `standard_b64decode`, `urlsafe_b64encode`, `urlsafe_b64decode`, `b32encode`, `b32decode`, `b16encode`, `b16decode`, `b85encode`, `b85decode`, `a85encode`, `a85decode` |
| `csv` | `reader`, `DictReader`, `QUOTE_MINIMAL`, `QUOTE_ALL`, `QUOTE_NONE` |

Use import module [as alias] or from module import approved_member [as alias]. No wildcard or relative imports. Other modules are rejected. JSON/TOML parsing is deferred because default parsers introduce floats; parse exact values in the consumer. No runtime download or host import fallback is provided.

## Builtins and tested examples

| Name | Tested expression |
| --- | --- |
| `ArithmeticError` | `isinstance(ArithmeticError("x"), Exception)` |
| `AssertionError` | `isinstance(AssertionError("x"), Exception)` |
| `Exception` | `isinstance(Exception("x"), Exception)` |
| `IndexError` | `isinstance(IndexError("x"), Exception)` |
| `KeyError` | `isinstance(KeyError("x"), Exception)` |
| `LookupError` | `isinstance(LookupError("x"), Exception)` |
| `MemoryError` | `isinstance(MemoryError("x"), Exception)` |
| `OverflowError` | `isinstance(OverflowError("x"), Exception)` |
| `RecursionError` | `isinstance(RecursionError("x"), Exception)` |
| `RuntimeError` | `isinstance(RuntimeError("x"), Exception)` |
| `StopIteration` | `isinstance(StopIteration("x"), Exception)` |
| `TimeoutError` | `isinstance(TimeoutError("x"), Exception)` |
| `TypeError` | `isinstance(TypeError("x"), Exception)` |
| `ValueError` | `isinstance(ValueError("x"), Exception)` |
| `ZeroDivisionError` | `isinstance(ZeroDivisionError("x"), Exception)` |
| `abs` | `abs(-2)` |
| `all` | `all([True,True])` |
| `any` | `any([False,True])` |
| `bin` | `bin(5)` |
| `bool` | `bool([])` |
| `bytes` | `bytes("AB","utf-8").decode()` |
| `chr` | `chr(233)` |
| `dict` | `dict(a=1)` |
| `divmod` | `list(divmod(7,3))` |
| `enumerate` | `[list(x) for x in enumerate(["a"]) ]` |
| `filter` | `list(filter(lambda x:x>1,[1,2]))` |
| `format` | `format(12,"04d")` |
| `frozenset` | `sorted(frozenset([2,1,2]))` |
| `hex` | `hex(31)` |
| `int` | `int("12")` |
| `isinstance` | `isinstance([],list)` |
| `iter` | `list(iter([1,2]))` |
| `len` | `len([1,2])` |
| `list` | `list((1,2))` |
| `map` | `list(map(lambda x:x+1,[1,2]))` |
| `max` | `max(2,1)` |
| `min` | `min(2,1)` |
| `next` | `next(iter([1,2]))` |
| `oct` | `oct(9)` |
| `ord` | `ord("é")` |
| `range` | `list(range(3))` |
| `repr` | `repr("abc")` |
| `reversed` | `list(reversed([1,2]))` |
| `round` | `round(123,-1)` |
| `set` | `sorted(set([2,1,2]))` |
| `slice` | `[1,2,3][slice(0,2)]` |
| `sorted` | `sorted([2,1])` |
| `str` | `str(12)` |
| `sum` | `sum([1,2])` |
| `tuple` | `list(tuple([1,2]))` |
| `zip` | `[list(x) for x in zip([1],[2])]` |

## Data methods and attributes with tested receiver examples

This table identifies the tested receiver. A method existing for Decimal does not imply it exists for int, or for every other type. Other argument combinations may raise ordinary runtime errors. Do not infer unsupported overloads from a familiar CPython name.

| Name | Tested expression |
| --- | --- |
| `add` | `sorted(v)` |
| `adjusted` | `Decimal("2").adjusted()` |
| `append` | `v` |
| `appendleft` | `list(v)` |
| `as_integer_ratio` | `list(Decimal("2").as_integer_ratio())` |
| `as_tuple` | `list(Decimal("2").as_tuple().digits)` |
| `astimezone` | `datetime.datetime(2024,1,2,tzinfo=datetime.timezone.utc).astimezone(datetime.timezone.utc).isoformat()` |
| `block_size` | `hashlib.sha256().block_size` |
| `capitalize` | `"abc".capitalize()` |
| `casefold` | `"Straße".casefold()` |
| `center` | `"a".center(3,"-")` |
| `clear` | `v` |
| `compare` | `Decimal("2").compare(Decimal("3"))` |
| `compare_signal` | `Decimal("2").compare_signal(Decimal("3"))` |
| `compare_total` | `Decimal("2").compare_total(Decimal("3"))` |
| `compare_total_mag` | `Decimal("2").compare_total_mag(Decimal("3"))` |
| `conjugate` | `Decimal("2").conjugate()` |
| `copy` | `[1].copy()` |
| `copy_abs` | `Decimal("2").copy_abs()` |
| `copy_negate` | `Decimal("2").copy_negate()` |
| `copy_sign` | `Decimal("2").copy_sign(Decimal("-1"))` |
| `count` | `"aba".count("a")` |
| `date` | `datetime.datetime(2024,1,2).date().isoformat()` |
| `day` | `datetime.date(2024,1,2).day` |
| `days` | `datetime.timedelta(days=2).days` |
| `decode` | `b"abc".decode()` |
| `difference` | `sorted({1,2}.difference({2}))` |
| `digest` | `hashlib.sha256(b"abc").digest().hex()` |
| `digest_size` | `hashlib.sha256().digest_size` |
| `digits` | `list(Decimal("2").as_tuple().digits)` |
| `discard` | `sorted(v)` |
| `dst` | `datetime.timezone.utc.dst(None)` |
| `elements` | `sorted(collections.Counter("aba").elements())` |
| `encode` | `"é".encode("utf-8").hex()` |
| `end` | `re.search("a","ba").end()` |
| `endswith` | `"abc".endswith("c")` |
| `exp` | `Decimal("0").exp()` |
| `expandtabs` | `"a\tb".expandtabs(2)` |
| `exponent` | `Decimal("2.0").as_tuple().exponent` |
| `extend` | `v` |
| `extendleft` | `list(v)` |
| `find` | `"abc".find("b")` |
| `flags` | `int(re.compile("a",re.I).flags) & int(re.I)` |
| `fma` | `Decimal("2").fma(Decimal("3"),Decimal("1"))` |
| `format` | `"{}".format(3)` |
| `from_iterable` | `list(itertools.chain.from_iterable([[1],[2]]))` |
| `fromhex` | `bytes.fromhex("616263").decode()` |
| `fromisoformat` | `datetime.date.fromisoformat("2024-01-02").day` |
| `fromkeys` | `dict.fromkeys(["a","b"],0)` |
| `get` | `{"a":1}.get("a")` |
| `group` | `re.search("(a)","ba").group(1)` |
| `groupdict` | `re.search("(?P<key>a)","a").groupdict()` |
| `groups` | `list(re.search("(a)","a").groups())` |
| `hex` | `b"abc".hex()` |
| `hexdigest` | `hashlib.sha256(b"abc").hexdigest()` |
| `hour` | `datetime.datetime(2024,1,2,3).hour` |
| `imag` | `Decimal("2").imag` |
| `index` | `"abc".index("b")` |
| `insert` | `v` |
| `intersection` | `sorted({1,2}.intersection({2}))` |
| `is_canonical` | `Decimal("2").is_canonical()` |
| `is_finite` | `Decimal("2").is_finite()` |
| `is_infinite` | `Decimal("2").is_infinite()` |
| `is_nan` | `Decimal("2").is_nan()` |
| `is_normal` | `Decimal("2").is_normal()` |
| `is_qnan` | `Decimal("2").is_qnan()` |
| `is_signed` | `Decimal("2").is_signed()` |
| `is_snan` | `Decimal("2").is_snan()` |
| `is_subnormal` | `Decimal("2").is_subnormal()` |
| `is_zero` | `Decimal("2").is_zero()` |
| `isalnum` | `'abc'.isalnum()` |
| `isalpha` | `'abc'.isalpha()` |
| `isascii` | `'abc'.isascii()` |
| `isdecimal` | `'1'.isdecimal()` |
| `isdigit` | `'1'.isdigit()` |
| `isdisjoint` | `{1}.isdisjoint({2})` |
| `isidentifier` | `'abc'.isidentifier()` |
| `islower` | `'a'.islower()` |
| `isnumeric` | `'½'.isnumeric()` |
| `isoformat` | `datetime.date(2024,1,2).isoformat()` |
| `isoweekday` | `datetime.date(2024,1,2).isoweekday()` |
| `isprintable` | `'abc'.isprintable()` |
| `isspace` | `' '.isspace()` |
| `issubset` | `{1}.issubset({1,2})` |
| `issuperset` | `{1,2}.issuperset({1})` |
| `istitle` | `'Title'.istitle()` |
| `isupper` | `'A'.isupper()` |
| `items` | `[list(x) for x in {"a":1}.items()]` |
| `join` | `",".join(["a","b"])` |
| `keys` | `list({"a":1}.keys())` |
| `ljust` | `"a".ljust(3,"-")` |
| `ln` | `Decimal("1").ln()` |
| `log10` | `Decimal("10").log10()` |
| `lower` | `"A".lower()` |
| `lstrip` | `" a ".lstrip()` |
| `max_mag` | `Decimal("2").max_mag(Decimal("3"))` |
| `maxlen` | `collections.deque([1],maxlen=2).maxlen` |
| `microsecond` | `datetime.datetime(2024,1,2,3,4,5,6).microsecond` |
| `microseconds` | `datetime.timedelta(microseconds=4).microseconds` |
| `min_mag` | `Decimal("2").min_mag(Decimal("3"))` |
| `minute` | `datetime.datetime(2024,1,2,3,4).minute` |
| `month` | `datetime.date(2024,1,2).month` |
| `most_common` | `[list(x) for x in collections.Counter("aba").most_common()]` |
| `next_minus` | `Decimal("0").next_minus().is_signed()` |
| `next_plus` | `Decimal("0").next_plus().is_signed()` |
| `next_toward` | `Decimal("2").next_toward(Decimal("2"))` |
| `normalize` | `Decimal("2").normalize()` |
| `number_class` | `Decimal("2").number_class()` |
| `partition` | `list("a:b".partition(":"))` |
| `pattern` | `re.compile("a").pattern` |
| `pop` | `v` |
| `popitem` | `v` |
| `popleft` | `list(v)` |
| `quantize` | `Decimal("2").quantize(Decimal("1"))` |
| `radix` | `Decimal("2").radix()` |
| `real` | `Decimal("2").real` |
| `remove` | `v` |
| `removeprefix` | `"prefix".removeprefix("pre")` |
| `removesuffix` | `"suffix".removesuffix("fix")` |
| `replace` | `"abc".replace("b","x")` |
| `reverse` | `v` |
| `rfind` | `"aba".rfind("a")` |
| `rindex` | `"aba".rindex("a")` |
| `rjust` | `"a".rjust(3,"-")` |
| `rotate` | `list(v)` |
| `rpartition` | `list("a:b".rpartition(":"))` |
| `rsplit` | `"a b c".rsplit(None,1)` |
| `rstrip` | `" a ".rstrip()` |
| `same_quantum` | `Decimal("2").same_quantum(Decimal("3"))` |
| `scaleb` | `Decimal("2").scaleb(1)` |
| `second` | `datetime.datetime(2024,1,2,3,4,5).second` |
| `seconds` | `datetime.timedelta(seconds=3).seconds` |
| `setdefault` | `v` |
| `sign` | `Decimal("-2").as_tuple().sign` |
| `sort` | `v` |
| `span` | `list(re.search("a","ba").span())` |
| `split` | `"a b".split()` |
| `splitlines` | `"a\nb".splitlines()` |
| `sqrt` | `Decimal("4").sqrt()` |
| `start` | `re.search("a","ba").start()` |
| `startswith` | `"abc".startswith("a")` |
| `strftime` | `datetime.date(2024,1,2).strftime("%Y-%m-%d")` |
| `string` | `re.search("a","ba").string` |
| `strip` | `" a ".strip()` |
| `strptime` | `datetime.datetime.strptime("2024-01-02","%Y-%m-%d").day` |
| `subtract` | `dict(v)` |
| `swapcase` | `"Ab".swapcase()` |
| `symmetric_difference` | `sorted({1,2}.symmetric_difference({2,3}))` |
| `time` | `datetime.datetime(2024,1,2,3).time().isoformat()` |
| `timetz` | `datetime.datetime(2024,1,2,3).timetz().isoformat()` |
| `title` | `"a b".title()` |
| `to_eng_string` | `Decimal("2").to_eng_string()` |
| `to_integral_exact` | `Decimal("2").to_integral_exact()` |
| `to_integral_value` | `Decimal("2").to_integral_value()` |
| `total` | `collections.Counter("aba").total()` |
| `tzinfo` | `datetime.datetime(2024,1,2).tzinfo` |
| `tzname` | `datetime.timezone.utc.tzname(None)` |
| `union` | `sorted({1}.union({2}))` |
| `update` | `v` |
| `upper` | `"a".upper()` |
| `utc` | `str(datetime.timezone.utc)` |
| `utcoffset` | `datetime.datetime(2024,1,2,tzinfo=datetime.timezone.utc).utcoffset().days` |
| `values` | `list({"a":1}.values())` |
| `weekday` | `datetime.date(2024,1,2).weekday()` |
| `year` | `datetime.date(2024,1,2).year` |
| `zfill` | `"7".zfill(3)` |
| `search` | `re.compile("a").search("ba").group()` |
| `match` | `re.compile("a").match("ab").group()` |
| `fullmatch` | `re.compile("a").fullmatch("a").group()` |
| `findall` | `re.compile("a").findall("aba")` |
| `finditer` | `[m.group() for m in re.compile("a").finditer("aba")]` |
| `sub` | `re.compile("a").sub("x","aba")` |

The executable fixture definitions, including setup statements and expected typed results, are in tests/profile_cases.py. tests/test_profile_compatibility.py proves that every advertised builtin, data attribute and imported member has a fixture. Imports are tested both qualified and through from-import aliases.

## Reproducible checks

```sh
python -m pip install '.[dev]'
python -m pytest -q tests/test_profile_compatibility.py tests/test_profile_syntax_security.py
python -m pytest -q
```

No API key or model calls are needed. Language conformance tests exercise the pinned runtime; OS/Python support still requires the full intended platform matrix. Process-observation gates can remain BLOCKED in restricted environments.

## Sources

Checked on 8 November 2026. The executable fixtures decide what is advertised for the pinned build; these pages explain the divergences behind it.

- [Monty limitations overview](https://pydantic.dev/docs/monty/limitations/)
- [Built-in functions](https://pydantic.dev/docs/monty/limitations/builtins/)
- [Standard library modules](https://pydantic.dev/docs/monty/limitations/modules/)
- [re module](https://pydantic.dev/docs/monty/limitations/re/)
- [decimal module](https://pydantic.dev/docs/monty/limitations/decimal/)
- [csv module](https://pydantic.dev/docs/monty/limitations/csv/)

Per-name pages for the other advertised modules follow the same `limitations/<name>/` path. The complete set is the `limitations/` directory of the Monty repository, published verbatim.
