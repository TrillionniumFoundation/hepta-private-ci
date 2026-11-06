"""Bind a narrow auditable Python callback to its actual source, code and immutable globals."""
import ast
import builtins
import dis
import hashlib
import inspect
import marshal
from pathlib import Path
import sys
import types
from .contracts import canonical, digest

BASELINES = ("direct_stop", "fixed_budget", "one_step_voi", "strong_planner")
PURE_BUILTINS = {n: getattr(builtins, n) for n in (
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len", "list", "max", "min",
    "pow", "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip", "frozenset")}


class PolicyBindingError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise PolicyBindingError(message)


def _literal(value):
    need(value is None or type(value) in (bool, int, float, str, tuple), "Mutable or executable policy global")
    if type(value) is tuple:
        for item in value:
            _literal(item)
    canonical(value)
    return value


def policy_binding(callback):
    """No closures, decorators, imported dependencies, mutable globals or hidden default state.

    This is reproducibility enforcement for trusted research code, not a Python sandbox.
    External concurrent mutation, dynamic attribute tricks and a compromised interpreter
    remain outside the contract. Dependencies must be expressed as audited source or inputs.
    """
    need(type(callback) is types.FunctionType and callback.__closure__ is None, "A plain top-level function is required")
    need(callback.__name__ == callback.__qualname__ and callback.__name__.isidentifier(), "Nested or anonymous callback")
    need(callback.__defaults__ is None and not callback.__kwdefaults__, "Default state is not supported")
    code = callback.__code__
    need(code.co_qualname == callback.__qualname__ and code.co_argcount == 5 and code.co_kwonlyargcount == 0
         and not code.co_flags & (inspect.CO_VARARGS | inspect.CO_VARKEYWORDS | inspect.CO_GENERATOR | inspect.CO_COROUTINE),
         "Callback must accept exactly five positional inputs")
    module = sys.modules.get(callback.__module__)
    need(module is not None and vars(module).get(callback.__name__) is callback, "Callback is not its module export")
    path = Path(inspect.getsourcefile(callback) or "").resolve()
    need(path.is_file() and path.suffix == ".py" and Path(module.__file__).resolve() == path
         and Path(code.co_filename).resolve() == path, "Auditable module source is required")
    source = path.read_bytes()
    tree = ast.parse(source, filename=code.co_filename)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == callback.__name__]
    need(len(nodes) == 1 and not nodes[0].decorator_list, "One undecorated top-level definition is required")
    compiled = compile(source, code.co_filename, "exec", dont_inherit=True, optimize=sys.flags.optimize)
    candidates = [c for c in compiled.co_consts if type(c) is types.CodeType and c.co_name == callback.__name__]
    actual = marshal.dumps(code, 2)
    need(len(candidates) == 1 and actual == marshal.dumps(candidates[0], 2), "Runtime code differs from source")
    referenced = {}

    def audit(current):
        for instruction in dis.get_instructions(current):
            need(instruction.opname not in ("IMPORT_NAME", "IMPORT_FROM", "IMPORT_STAR", "STORE_GLOBAL", "DELETE_GLOBAL"),
                 "Import or global mutation in callback")
            if instruction.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                name = instruction.argval
                if name in callback.__globals__:
                    referenced[name] = _literal(callback.__globals__[name])
                else:
                    need(name in PURE_BUILTINS and callback.__builtins__.get(name) is PURE_BUILTINS[name],
                         "Unsupported or replaced builtin: "+name)
        for constant in current.co_consts:
            if type(constant) is types.CodeType:
                audit(constant)
    audit(code)
    return {"schema": "ndu.audited_callback.v1", "module": callback.__module__, "qualname": callback.__qualname__,
            "source_sha256": hashlib.sha256(source).hexdigest(), "code_sha256": hashlib.sha256(actual).hexdigest(),
            "globals_sha256": digest(referenced), "python": sys.implementation.name+" "+sys.version}


def verify_policy(arm, settings, callback):
    if arm in BASELINES:
        need(callback is None and "policy_binding" not in settings, "Registered baseline cannot be replaced by a callback")
        return None
    need(callback is not None, "Full/candidate arms require an explicit audited callback")
    actual = policy_binding(callback)
    need(settings.get("policy_binding") == actual, "Actual callback differs from the frozen binding")
    return actual
