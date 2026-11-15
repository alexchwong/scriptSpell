from dataclasses import dataclass, asdict
from importlib.metadata import version, PackageNotFoundError

from ._version import __version__ as VERSION
PROFILE = 'scriptspell-pure-v5'
# Pure builtins only: no host I/O, dynamic evaluation or namespace reflection.
BUILTINS = frozenset('ArithmeticError AssertionError Exception IndexError KeyError LookupError MemoryError OverflowError RecursionError RuntimeError StopIteration TimeoutError TypeError ValueError ZeroDivisionError abs all any bin bool bytes chr dict divmod enumerate filter float format frozenset hex int isinstance iter len list map max min next oct ord range repr reversed round set slice sorted str sum tuple zip'.split())
IMPORTS = {
    'decimal': ('Decimal', 'InvalidOperation', 'DivisionByZero', 'Inexact', 'Rounded'),
    're': ('compile', 'escape', 'search', 'match', 'fullmatch', 'split', 'findall', 'finditer', 'sub', 'I', 'IGNORECASE', 'M', 'MULTILINE', 'S', 'DOTALL', 'A', 'ASCII', 'NOFLAG', 'error'),
    'datetime': ('date', 'datetime', 'timedelta', 'timezone'),
    'unicodedata': ('normalize', 'category', 'combining', 'name', 'lookup'),
    'math': ('gcd', 'lcm', 'isqrt', 'factorial', 'comb', 'perm', 'floor', 'ceil', 'trunc'),
    'itertools': ('chain', 'islice', 'repeat', 'cycle', 'count', 'accumulate', 'product', 'permutations', 'combinations', 'combinations_with_replacement', 'compress', 'dropwhile', 'takewhile', 'filterfalse', 'starmap', 'zip_longest', 'groupby', 'tee'),
    'functools': ('reduce', 'partial'),
    'collections': ('Counter', 'defaultdict', 'deque'),
    'bisect': ('bisect', 'bisect_left', 'bisect_right', 'insort', 'insort_left', 'insort_right'),
    'copy': ('copy', 'deepcopy'),
    'fnmatch': ('fnmatch', 'fnmatchcase', 'filter', 'translate'),
    'hashlib': ('md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512', 'sha3_224', 'sha3_256', 'sha3_384', 'sha3_512', 'blake2b', 'blake2s', 'shake_128', 'shake_256'),
    'base64': ('b64encode', 'b64decode', 'standard_b64encode', 'standard_b64decode', 'urlsafe_b64encode', 'urlsafe_b64decode', 'b32encode', 'b32decode', 'b16encode', 'b16decode', 'b85encode', 'b85decode', 'a85encode', 'a85decode'),
    'csv': ('reader', 'DictReader', 'QUOTE_MINIMAL', 'QUOTE_ALL', 'QUOTE_NONE'),
}
DATA_METHODS = frozenset('add adjusted append appendleft as_integer_ratio as_tuple astimezone block_size capitalize casefold center clear compare compare_signal compare_total compare_total_mag conjugate copy copy_abs copy_negate copy_sign count date day days decode difference digest digest_size digits discard dst elements encode end endswith exp expandtabs exponent extend extendleft find flags fma format from_iterable fromhex fromisoformat fromkeys get group groupdict groups hex hexdigest hour imag index insert intersection is_canonical is_finite is_infinite is_nan is_normal is_qnan is_signed is_snan is_subnormal is_zero isalnum isalpha isascii isdecimal isdigit isdisjoint isidentifier islower isnumeric isoformat isoweekday isprintable isspace issubset issuperset istitle isupper items join keys ljust ln log10 lower lstrip max_mag maxlen microsecond microseconds min_mag minute month most_common next_minus next_plus next_toward normalize number_class partition pattern pop popitem popleft quantize radix real remove removeprefix removesuffix replace reverse rfind rindex rjust rotate rpartition rsplit rstrip same_quantum scaleb second seconds setdefault sign sort span split splitlines sqrt start startswith strftime string strip strptime subtract swapcase symmetric_difference time timetz title to_eng_string to_integral_exact to_integral_value total tzinfo tzname union update upper utc utcoffset values weekday year zfill'.split())
DATA_METHODS = DATA_METHODS | frozenset('search match fullmatch findall finditer sub'.split())
METHODS = DATA_METHODS | frozenset('encode decode hex fromhex digest hexdigest digest_size block_size'.split())
METHODS = DATA_METHODS  # Legacy API field; module members are separate in IMPORTS.
FORBIDDEN_NAMES = frozenset(('eval exec compile globals locals vars dir getattr setattr delattr hasattr type id hash '
    'open print input breakpoint help object super complex bytearray memoryview __import__').split())
# An explicitly imported re.compile is allowed; bare compile remains unavailable.
RESERVED_NAMES = BUILTINS | FORBIDDEN_NAMES | {'Decimal'}

@dataclass(frozen=True)
class Limits:
    source_bytes: int = 65536
    value_bytes: int = 1048576
    nodes: int = 20000
    depth: int = 32
    memory_bytes: int = 67108864
    execution_seconds: float = 1.0
    wall_seconds: float = 5.0

    def checked(self):
        import math
        ceilings = Limits()
        for key, val in asdict(self).items():
            if type(val) not in (int, float) or not math.isfinite(val) or val <= 0 or val > getattr(ceilings, key):
                raise ValueError('invalid_limit')
            if key not in ('execution_seconds', 'wall_seconds') and type(val) is not int:
                raise ValueError('invalid_limit')
        return self


def profile():
    packages = {}
    for name in ('pydantic-monty', 'pydantic-monty-client', 'pydantic-monty-runtime'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return dict(version=VERSION, profile=PROFILE, codec=2, packages=packages,
                limits=asdict(Limits()), builtins=sorted(BUILTINS), methods=sorted(METHODS),
                validation='static_only', decimal_precision=128,
                imports={k:list(v) for k,v in IMPORTS.items()}, data_attributes=sorted(DATA_METHODS),
                syntax=['functions and closures','lambda','literal and computed function defaults','annotations',
                        'loops and conditions','assignment expressions','data-only structural matching','try/except/else/finally','assert','f-strings',
                        'list/dict/set comprehensions','eager generator expressions','starred unpacking','integer bit operations'],
                output_types=['dict[str, value]','list','str','bool','int','finite float','finite Decimal','None'],
                caveats=['Internal bytes, tuples, sets, iterators, dates and specialised containers must be converted before return.',
                         'Generator expressions are eagerly materialised by Monty.',
                         'Builtin methods must be called directly, not passed as callbacks.',
                         'Integer objects have no exposed methods/attributes; as_integer_ratio/conjugate/real/imag are Decimal-only.',
                         'CSV readers require direct calls, no **kwargs, and default/string-preserving quoting modes 0/1/3.',
                         'bytes(iterable_of_ints) is unsupported; use text.encode, bytes(text, encoding), bytes(existing_bytes) or bytes(length).',
                         'Regex finditer is eager, ASCII flags have no effect, and CPython replacement/engine semantics differ; see docs/language-profile.md.',
                         'Finite binary floats and true division are supported. Powers are unavailable.',
                         'Decimal arithmetic uses precision 128 and traps Rounded/Inexact.'])
