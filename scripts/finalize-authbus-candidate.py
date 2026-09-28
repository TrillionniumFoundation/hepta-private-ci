#!/usr/bin/env python3
"""Attach operational code and strict exact-candidate checks BEFORE qualification.

Whole-function replacements preserve the receipt's ordered gate contract and
avoid patching individual comparisons by uncertain source formatting.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    file = ROOT / path
    text = file.read_text()
    # Re-running preparation after a failed gate must be byte-stable. Accept
    # only the exact reviewed replacement, never an arbitrary missing anchor.
    if text.count(new) == 1:
        return
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
for name in ("implementation_map", "operations_contract"):
    if values.count(name) > 1:
        raise SystemExit(f"duplicate required gate: {name}")
values = [name for name in values if name not in ("implementation_map", "operations_contract")]
position = values.index("inventory_tests") + 1
values[position:position] = ["implementation_map", "operations_contract"]
edit(required[0].value, "(\n    " + ",\n    ".join(repr(value) for value in values) + ",\n)")
functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
results = [node for node in ast.walk(functions["commands"]) if isinstance(node, ast.Assign)
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
    expected = ast.parse(expression, mode="eval").body
    if keys.count(key) > 1:
        raise SystemExit(f"duplicate command {key}")
    if key in keys:
        actual = result.values[keys.index(key)]
        if ast.dump(actual) != ast.dump(expected):
            raise SystemExit(f"command changed and requires review: {key}")
    else:
        result.keys.append(ast.Constant(key))
        result.values.append(expected)
edit(results[0].value, ast.unparse(result))
strict_gate = '''def gates_pass(rows: list[dict[str, Any]], candidate: str) -> bool:
    if not isinstance(candidate, str) or SHA.fullmatch(candidate) is None:
        return False
    if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or [row.get("id") for row in rows] != list(REQUIRED)):
        return False
    for row in rows:
        elapsed = row.get("elapsed_seconds")
        code = row.get("exit_code")
        if (row.get("state") != "success" or type(code) is not int or code != 0
                or row.get("candidate") != candidate
                or not isinstance(row.get("log_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["log_sha256"]) is None
                or type(elapsed) not in (float, int)
                or not math.isfinite(elapsed) or elapsed < 0):
            return False
        if row["id"] in TEST_STEPS:
            passed = row.get("passed_tests")
            if type(passed) is not int or passed <= 0:
                return False
    return True'''
edit(functions["gates_pass"], strict_gate)
for start, end, replacement in sorted(edits, reverse=True):
    text = text[:start] + replacement + text[end:]
if "import math\n" not in text:
    text = text.replace("import json\n", "import json\nimport math\n", 1)
text = text.replace("if args.step_timeout <= 0:", "if not math.isfinite(args.step_timeout) or args.step_timeout <= 0:")
ast.parse(text)
compile(text, str(path), "exec")
path.write_text(text)
# --doc and --all-targets are distinct Rust execution modes. Require --doc for
# the native privacy contract; keep --all-targets mandatory for every owner gate.
replace("scripts/test-authbus-exact-head-evidence.py",
        '            self.assertIn("--all-targets", receipt.commands()[name])',
        '            self.assertIn("--doc" if name == "doc_tests" else "--all-targets", receipt.commands()[name])')
replace("scripts/test-authbus-exact-head-evidence.py",
        '    def test_zero_test_execution_is_not_qualification(self):',
        '''    def test_malformed_scalars_and_rows_fail_closed(self):
        for field, value in (("elapsed_seconds", float("nan")),
                             ("elapsed_seconds", float("inf")),
                             ("elapsed_seconds", True), ("exit_code", False)):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = value
            self.assertFalse(receipt.gates_pass(rows, self.candidate))
        self.assertFalse(receipt.gates_pass(None, self.candidate))
        self.assertFalse(receipt.gates_pass([None], self.candidate))
        for value in (True, 1.5, "1", None):
            rows = copy.deepcopy(self.rows)
            next(row for row in rows if row["id"] == "authbus")["passed_tests"] = value
            self.assertFalse(receipt.gates_pass(rows, self.candidate))

    def test_zero_test_execution_is_not_qualification(self):''')
print("Prepared native metrics, exact-candidate receipt gates and native doctest assertions.")
