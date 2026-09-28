#!/usr/bin/env python3
"""Attach operational code and exact-candidate checks BEFORE qualification.

Patch parsed syntax nodes, retaining surrounding source comments. Preparation is
not qualification and must fail closed on any unreviewed command-plan change.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    file = ROOT / path
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch anchor, got {count}: {old!r}")
    file.write_text(text.replace(old, new))


replace("codex-rs/hepta-authbus/src/lib.rs", "mod issuer_registry;", "mod issuer_registry;\nmod metrics;")
path = ROOT / "scripts/authbus-exact-head-evidence.py"
text = path.read_text()
module = ast.parse(text)
lines = text.splitlines(keepends=True)
offsets = [0]
for line in lines:
    offsets.append(offsets[-1] + len(line))
edits = []


def edit(node, replacement):
    edits.append((offsets[node.lineno - 1] + node.col_offset,
                  offsets[node.end_lineno - 1] + node.end_col_offset,
                  replacement))


required = [node for node in module.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "REQUIRED" for target in node.targets)]
if len(required) != 1:
    raise SystemExit("expected exactly one REQUIRED plan")
values = list(ast.literal_eval(required[0].value))
for expected in ("inventory", "inventory_tests", "receipt_tests", "authbus", "doc_tests", "qualification", "workspace", "clippy", "clean_tree"):
    if values.count(expected) != 1:
        raise SystemExit(f"prepared command plan missing or duplicating {expected}: {values!r}")
position = values.index("inventory_tests") + 1
values[position:position] = ["implementation_map", "operations_contract"]
edit(required[0].value, "(\n    " + ",\n    ".join(repr(value) for value in values) + ",\n)")
functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
commands = functions["commands"]
results = [node for node in ast.walk(commands) if isinstance(node, ast.Assign)
           and any(isinstance(target, ast.Name) and target.id == "result" for target in node.targets)
           and isinstance(node.value, ast.Dict)]
if len(results) != 1:
    raise SystemExit("expected exactly one commands result dictionary")
result = results[0].value
keys = [ast.literal_eval(key) for key in result.keys]
if "inventory_tests" not in keys or "doc_tests" not in keys:
    raise SystemExit(f"prepared commands omitted native/lexical tests: {keys!r}")
for key, expression in [
    ("implementation_map", '[sys.executable, "scripts/generate-authbus-implementation-map.py", "--check"]'),
    ("operations_contract", '[sys.executable, "scripts/test-authbus-operations.py"]'),
]:
    if key in keys:
        raise SystemExit(f"unexpected duplicate command {key}")
    result.keys.append(ast.Constant(key))
    result.values.append(ast.parse(expression, mode="eval").body)
edit(results[0].value, ast.unparse(result))

elapsed = []
for node in ast.walk(functions["gates_pass"]):
    if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Subscript)
            and isinstance(node.left.value, ast.Name) and node.left.value.id == "row"
            and isinstance(node.left.slice, ast.Constant) and node.left.slice.value == "elapsed_seconds"
            and len(node.ops) == 1 and isinstance(node.ops[0], ast.Lt)):
        elapsed.append(node)
if len(elapsed) != 1:
    raise SystemExit("expected one nonnegative elapsed-time gate")
edit(elapsed[0], '(not math.isfinite(row["elapsed_seconds"]) or row["elapsed_seconds"] < 0)')
timeouts = [node for node in ast.walk(functions["main"]) if isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Attribute) and node.left.attr == "step_timeout"
            and isinstance(node.left.value, ast.Name) and node.left.value.id == "args"
            and len(node.ops) == 1 and isinstance(node.ops[0], ast.LtE)]
if len(timeouts) != 1:
    raise SystemExit("expected one positive step-timeout gate")
edit(timeouts[0], '(not math.isfinite(args.step_timeout) or args.step_timeout <= 0)')
for start, end, replacement in sorted(edits, reverse=True):
    text = text[:start] + replacement + text[end:]
if "import math\n" not in text:
    # Import position is known from the parsed module; preserve the module docstring.
    text = text.replace("import json\n", "import json\nimport math\n", 1)
ast.parse(text)
compile(text, str(path), "exec")
path.write_text(text)
print("Prepared native metrics, source-map gates and finite receipt validation.")
