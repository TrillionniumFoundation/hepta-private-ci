"""Read-only byte/AST/global-binding checks for explicitly copied methods."""

import ast
import builtins
import dis
import hashlib
from pathlib import Path
from types import CodeType

from . import contract


def function_source(path, class_name, method_name):
    raw = path.read_bytes()
    tree = ast.parse(raw, filename=str(path))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    node = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    body = b"".join(raw.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
    return body, ast.dump(node, include_attributes=False).encode()


def global_names(code):
    names = {instruction.argval for instruction in dis.get_instructions(code) if instruction.opname == "LOAD_GLOBAL"}
    for value in code.co_consts:
        if isinstance(value, CodeType): names.update(global_names(value))
    return sorted(names)


def resolve(function, name):
    return function.__globals__[name] if name in function.__globals__ else getattr(builtins, name)


def verify(adapter_class):
    expected = {"model_parts": contract.model_parts, "module_identity": contract.module_identity}
    path = Path(__file__).with_name("adapter.py")
    rows = []
    for name in ("_parts", "_description"):
        before, old_ast = function_source(contract.BASE_PATH, "Adapter", name)
        after, new_ast = function_source(path, "GRUAdapter", name)
        contract.require(before == after and old_ast == new_ast, "Copied strict method bytes/AST differ")
        old, new = getattr(contract.strict.Adapter, name), getattr(adapter_class, name)
        contract.require(global_names(old.__code__) == global_names(new.__code__), "Copied method global inventory differs")
        bindings = []
        for symbol in global_names(old.__code__):
            original, current = resolve(old, symbol), resolve(new, symbol)
            allowed = symbol in expected
            contract.require(current is expected[symbol] if allowed else current is original, "Unexpected global binding: " + symbol)
            bindings.append({"name": symbol, "same_object": current is original, "permitted_local_replacement": allowed,
                             "module": getattr(current, "__module__", getattr(current, "__name__", type(current).__module__))})
        rows.append({"method": name, "full_source_bytes": len(before), "original_source_sha256": hashlib.sha256(before).hexdigest(),
                     "copied_source_sha256": hashlib.sha256(after).hexdigest(), "ast_sha256": hashlib.sha256(old_ast).hexdigest(),
                     "bytes_equal": True, "ast_equal": True, "globals": bindings})
    inherited = ("__init__", "capture", "_mutable", "_prepare", "_apply", "restore")
    contract.require(all(getattr(adapter_class, name) is getattr(contract.strict.Adapter, name) for name in inherited), "Unexpected override of strict adapter execution")
    return {"strict_source_sha256": contract.BASE_SHA256, "copied_methods": rows,
            "unchanged_inherited_methods": list(inherited), "only_local_global_replacements": sorted(expected),
            "global_monkey_patch": False, "runtime_exec_or_code_rewrite": False}
