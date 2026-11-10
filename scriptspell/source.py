"""Nonexecuting AST policy, run only inside the bounded trusted driver."""
import ast
from math import isfinite
from .profile import BUILTINS, DATA_METHODS, IMPORTS, FORBIDDEN_NAMES, RESERVED_NAMES

ALLOWED = {getattr(ast, n) for n in '''Module NamedExpr Match match_case MatchValue MatchSingleton MatchSequence MatchMapping MatchStar MatchAs MatchOr FunctionDef Lambda arguments arg Return Assign AnnAssign AugAssign Expr If For While Break Continue Pass Raise Assert Try ExceptHandler Call Name Load Store Constant List Dict Tuple Set Subscript Slice Attribute BinOp UnaryOp BoolOp Compare IfExp ListComp DictComp SetComp GeneratorExp comprehension keyword Starred JoinedStr FormattedValue Add Sub Mult Div FloorDiv Mod BitAnd BitOr BitXor LShift RShift Invert UAdd USub Not And Or Eq NotEq Lt LtE Gt GtE In NotIn Is IsNot Import ImportFrom alias'''.split()}


def private(name):
    return name.startswith('_ss_') or '__' in name


def binding_issue(name):
    return private(name) or name in RESERVED_NAMES


def check(source, limits):
    if type(source) is not str or len(source.encode('utf-8')) > limits.source_bytes:
        return [{'code':'source_limit','line':None}]
    try: tree=ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return [{'code':'syntax','line':getattr(exc,'lineno',None)}]
    issues=[]
    def issue(node,code,symbol=None,message=None):
        row={'code':code,'line':getattr(node,'lineno',None)}
        if symbol is not None:row['symbol']=symbol[:64]
        if message:row['message']=message
        issues.append(row)
    transforms=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='transform']
    if len(transforms)!=1:issue(tree,'entrypoint')
    if transforms:
        a=transforms[0].args
        if len(a.args)!=1 or a.args[0].arg!='inputs' or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
            issue(transforms[0],'entrypoint')
    for n in tree.body:
        if type(n) not in (ast.FunctionDef,ast.Import,ast.ImportFrom):issue(n,'top_level')
    names=[n.name for n in tree.body if isinstance(n,ast.FunctionDef)]
    if len(names)!=len(set(names)):issue(tree,'duplicate_function')
    parents={id(child):parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    module_bindings={a.asname or a.name:a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
    local_bindings={n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    local_bindings.update(n.arg for n in ast.walk(tree) if isinstance(n,ast.arg))
    local_bindings.update(n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef))
    local_bindings.update(n.name for n in ast.walk(tree) if isinstance(n,ast.ExceptHandler) and n.name)
    local_bindings.update(a.asname or a.name for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names)
    pattern_bindings=[n.name for n in ast.walk(tree) if isinstance(n,(ast.MatchAs,ast.MatchStar)) and n.name]
    pattern_bindings += [n.rest for n in ast.walk(tree) if isinstance(n,ast.MatchMapping) and n.rest]
    local_bindings.update(pattern_bindings)
    csv_bindings={a.asname or a.name for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module=='csv' for a in n.names if a.name in ('reader','DictReader')}
    def csv_call_allowed(call):
        for kw in call.keywords:
            if kw.arg is None:return False
            if kw.arg=='quoting':
                if isinstance(kw.value,ast.Constant) and type(kw.value.value) is int and kw.value.value in (0,1,3):continue
                if isinstance(kw.value,ast.Attribute) and isinstance(kw.value.value,ast.Name) and module_bindings.get(kw.value.value.id)=='csv' and kw.value.attr in ('QUOTE_MINIMAL','QUOTE_ALL','QUOTE_NONE'):continue
                return False
        return True
    regex_compile_bound=any(isinstance(n,ast.ImportFrom) and n.module=='re' and any(a.name=='compile' and (a.asname or a.name)=='compile' for a in n.names) for n in ast.walk(tree))
    for n in ast.walk(tree):
        if len(issues)>=20:break
        if type(n) not in ALLOWED:
            issue(n,'unsupported_syntax',type(n).__name__);continue
        if isinstance(n,ast.FunctionDef):
            if n.decorator_list:issue(n,'decorator_denied')
            if binding_issue(n.name):issue(n,'reserved_name',n.name)
        elif isinstance(n,ast.arg):
            if binding_issue(n.arg):issue(n,'reserved_name',n.arg)
        elif isinstance(n,(ast.MatchAs,ast.MatchStar)):
            if n.name and binding_issue(n.name):issue(n,'reserved_name',n.name)
        elif isinstance(n,ast.MatchMapping):
            if n.rest and binding_issue(n.rest):issue(n,'reserved_name',n.rest)
        elif isinstance(n,ast.ExceptHandler):
            if n.name and binding_issue(n.name):issue(n,'reserved_name',n.name)
        elif isinstance(n,ast.Import):
            for alias in n.names:
                target=alias.asname or alias.name
                if alias.name not in IMPORTS or private(target) or (target in RESERVED_NAMES and target!=alias.name):issue(n,'import_denied',alias.name)
        elif isinstance(n,ast.ImportFrom):
            if n.level or n.module not in IMPORTS:
                issue(n,'import_denied',n.module or 'relative');continue
            for alias in n.names:
                target=alias.asname or alias.name
                if alias.name not in IMPORTS[n.module] or private(target) or (target in RESERVED_NAMES and target!=alias.name):
                    issue(n,'import_denied',alias.name)
        elif isinstance(n,ast.Name):
            parent=parents.get(id(n))
            if n.id in csv_bindings and isinstance(n.ctx,ast.Load) and not (isinstance(parent,ast.Call) and parent.func is n and csv_call_allowed(parent)):
                issue(n,'csv_mode_denied',n.id,'CSV readers require direct calls with literal string-preserving quoting modes and no keyword unpacking.')
            if n.id in module_bindings and isinstance(n.ctx,ast.Load) and not (isinstance(parent,ast.Attribute) and parent.value is n):
                issue(n,'module_reference_denied',n.id,'Imported modules may only be used through their advertised qualified members.')
            if private(n.id) or (n.id in FORBIDDEN_NAMES and not (n.id=='compile' and regex_compile_bound)):
                issue(n,'name_denied',n.id,'Name is unavailable in the pure data profile.')
            elif isinstance(n.ctx,ast.Load) and n.id not in BUILTINS|local_bindings and n.id!='Decimal':
                issue(n,'name_denied',n.id,'Unknown name; use declared bindings or advertised builtins/imports.')
            elif isinstance(n.ctx,ast.Store) and n.id in RESERVED_NAMES:
                issue(n,'reserved_name',n.id)
        elif isinstance(n,ast.Attribute):
            module=module_bindings.get(n.value.id) if isinstance(n.value,ast.Name) else None
            parent=parents.get(id(n))
            if module=='csv' and n.attr in ('reader','DictReader') and not (isinstance(parent,ast.Call) and parent.func is n and csv_call_allowed(parent)):
                issue(n,'csv_mode_denied',n.attr,'CSV readers require direct calls with literal string-preserving quoting modes and no keyword unpacking.')
            if private(n.attr) or (module in IMPORTS and n.attr not in IMPORTS[module]) or (module not in IMPORTS and n.attr not in DATA_METHODS):
                issue(n,'attribute_denied',n.attr,'Attribute is unavailable; use an advertised data method or module member.')
            elif isinstance(n.ctx,ast.Store):issue(n,'attribute_write_denied',n.attr)
        elif isinstance(n,ast.Call):
            if isinstance(n.func,ast.Name) and n.func.id not in BUILTINS|local_bindings and n.func.id!='Decimal':
                issue(n,'call_denied',n.func.id,'Unknown callable; use a defined function or an advertised builtin/import.')
            if isinstance(n.func,ast.Name) and (private(n.func.id) or (n.func.id in FORBIDDEN_NAMES and not (n.func.id=='compile' and regex_compile_bound))):
                issue(n,'call_denied',n.func.id,'Call is unavailable in the pure data profile.')
            elif not isinstance(n.func,(ast.Name,ast.Attribute,ast.Lambda,ast.Subscript,ast.Call)):
                issue(n,'call_denied',type(n.func).__name__)
        elif isinstance(n,ast.Constant) and (type(n.value) not in (str,int,float,bool,bytes,type(None))
                                            or (type(n.value) is float and not isfinite(n.value))):
            issue(n,'literal_denied')
    return issues


def validate_source(source):
    from .runtime import _invoke
    return _invoke({'action':'validate','source':source})
