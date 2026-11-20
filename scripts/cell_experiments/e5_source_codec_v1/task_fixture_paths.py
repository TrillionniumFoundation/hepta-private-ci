"""Bounded literal path propagation for already fixed test inputs; no eval/I/O."""

import ast
import itertools
import posixpath

from context_graph import dotted

MAX_CHOICES = 256
VIRTUAL_ROOT = "/__bound_repository__/"


def values(node, environment, allowed):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        value = environment.get(node.id)
        return value if value is not None and len(value) <= MAX_CHOICES else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        left, right = (
            values(node.left, environment, allowed),
            values(node.right, environment, allowed),
        )
        if left is None or right is None or len(left) * len(right) > MAX_CHOICES:
            return None
        operation = (
            posixpath.join if isinstance(node.op, ast.Div) else lambda a, b: a + b
        )
        return {operation(a, b) for a, b in itertools.product(left, right)}
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        parent = values(node.value, environment, allowed)
        return None if parent is None else {posixpath.dirname(p) for p in parent}
    if not isinstance(node, ast.Call):
        return None
    call = dotted(node.func)
    if call not in allowed:
        return None
    arguments = [values(arg, environment, allowed) for arg in node.args]
    if any(arg is None for arg in arguments):
        return None
    if call in {"Path", "pathlib.Path", "str"} and len(arguments) == 1:
        return arguments[0]
    if call == "os.path.dirname" and len(arguments) == 1:
        return {posixpath.dirname(p) for p in arguments[0]}
    if call == "os.path.abspath" and len(arguments) == 1:
        return {
            posixpath.normpath(posixpath.join(VIRTUAL_ROOT, p)) for p in arguments[0]
        }
    if call == "os.path.join" and arguments:
        count = 1
        for arg in arguments:
            count *= len(arg)
        if count <= MAX_CHOICES:
            return {posixpath.join(*parts) for parts in itertools.product(*arguments)}
    return None


def allowed_calls(graph, unit, node):
    imported = {
        (r["module"], r["name"], r["alias"])
        for u in graph.by_path[unit["path"]]
        for r in u["imports"]
    }
    rebound = {
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }
    rebound |= {a.arg for a in ast.walk(node) if isinstance(a, ast.arg)}
    calls = set()
    if ("os", None, "os") in imported and "os" not in rebound:
        calls |= {"os.path.dirname", "os.path.join", "os.path.abspath"}
    if ("pathlib", None, "pathlib") in imported and "pathlib" not in rebound:
        calls.add("pathlib.Path")
    if ("pathlib", "Path", "Path") in imported and "Path" not in rebound:
        calls.add("Path")
    if not graph.lookup(unit["path"], "str") and "str" not in rebound:
        calls.add("str")
    return calls


def resolve(graph, root_keys):
    pending, seen, bound, unresolved, paths = [], set(), set(), set(), set()
    exhausted = False
    for key in root_keys:
        unit = graph.units[key]
        node = graph.definitions.get(key)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        environment = {"__file__": {VIRTUAL_ROOT + unit["path"]}}
        for dec in node.decorator_list:
            if (
                not isinstance(dec, ast.Call)
                or not (dotted(dec.func) or "").endswith(".parametrize")
                or len(dec.args) < 2
            ):
                continue
            try:
                names, rows = (
                    ast.literal_eval(dec.args[0]),
                    ast.literal_eval(dec.args[1]),
                )
                names = (
                    [n.strip() for n in names.split(",")]
                    if isinstance(names, str)
                    else list(names)
                )
                for row in rows:
                    row = [row] if len(names) == 1 else row
                    for name, value in zip(names, row):
                        if isinstance(value, str):
                            environment.setdefault(name, set()).add(value)
            except (ValueError, TypeError, SyntaxError):
                pass  # Unknown values stay unknown; no evaluation or pruning.
        pending.append((key, environment))
    while pending:
        key, environment = pending.pop(0)
        marker = (
            key,
            tuple(sorted((k, tuple(sorted(v))) for k, v in environment.items())),
        )
        if marker in seen:
            continue
        seen.add(marker)
        if len(seen) > MAX_CHOICES:
            unresolved.add(key)
            exhausted = True
            break
        unit, node = graph.units[key], graph.definitions.get(key)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        allowed = allowed_calls(graph, unit, node)
        # A source-ordered abstract walk propagates only the whitelisted string
        # operations above. Branch-dependent writes are rejected, not guessed.
        assigned, positions = set(), {}
        repeated = set()
        for statement in ast.walk(node):
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        if target.id in assigned:
                            repeated.add(target.id)
                        assigned.add(target.id)
                        positions[target.id] = statement.lineno
        top_assignments = {
            id(n) for n in node.body if isinstance(n, (ast.Assign, ast.AnnAssign))
        }
        for statement in ast.walk(node):
            if (
                isinstance(statement, (ast.Assign, ast.AnnAssign))
                and id(statement) not in top_assignments
            ):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                repeated.update(t.id for t in targets if isinstance(t, ast.Name))
            if isinstance(statement, (ast.AugAssign, ast.NamedExpr)):
                repeated.update(
                    n.id for n in ast.walk(statement.target) if isinstance(n, ast.Name)
                )
        for name in repeated:
            environment.pop(name, None)
        for statement in node.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                value = (
                    values(statement.value, environment, allowed)
                    if statement.value is not None
                    else None
                )
                for target in targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id not in repeated
                        and value is not None
                    ):
                        environment[target.id] = value
        io_seen, io_ok = False, True
        for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
            name = dotted(call.func) or ""
            candidates = None
            if name == "open":
                io_seen = True
                candidates = (
                    values(call.args[0], environment, allowed) if call.args else None
                )
            elif name.endswith((".read_text", ".read_bytes")):
                io_seen = True
                candidates = values(call.func.value, environment, allowed)
            elif name in {
                "subprocess.Popen",
                "subprocess.run",
                "subprocess.call",
                "subprocess.check_output",
            }:
                io_seen = True
                if (
                    call.args
                    and isinstance(call.args[0], (ast.List, ast.Tuple))
                    and len(call.args[0].elts) == 2
                ):
                    candidates = values(call.args[0].elts[1], environment, allowed)
            else:
                for helper in graph.lookup(unit["path"], name, unit["parent_class"]):
                    definition = graph.definitions.get(helper["unit_id"])
                    if not isinstance(
                        definition, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        continue
                    child = {"__file__": {VIRTUAL_ROOT + helper["path"]}}
                    for formal, argument in zip(definition.args.args, call.args):
                        argument_values = values(argument, environment, allowed)
                        if argument_values is not None:
                            child[formal.arg] = argument_values
                    pending.append((helper["unit_id"], child))
                continue
            late_binding = any(
                positions.get(n.id, 0) > call.lineno
                for n in ast.walk(call)
                if isinstance(n, ast.Name)
            )
            if candidates is None or late_binding:
                io_ok = False
                continue
            for candidate in candidates:
                normalized = posixpath.normpath(candidate)
                if normalized.startswith(VIRTUAL_ROOT):
                    normalized = normalized[len(VIRTUAL_ROOT) :]
                if (
                    normalized.startswith("/")
                    or normalized.startswith("../")
                    or normalized not in graph.files
                    or normalized in graph.runtime
                ):
                    io_ok = False
                else:
                    paths.add(normalized)
        if io_seen:
            (bound if io_ok else unresolved).add(key)
    return {
        "paths": sorted(paths),
        "resolved_units": [] if exhausted else sorted(bound - unresolved),
        "unresolved_units": sorted(unresolved),
        "abstract_invocations": len(seen),
        "bounded_analysis_exhausted": exhausted,
    }
