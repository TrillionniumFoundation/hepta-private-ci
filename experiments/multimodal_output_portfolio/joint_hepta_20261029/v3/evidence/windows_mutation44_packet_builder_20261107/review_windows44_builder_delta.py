"""Check the frozen builder revision as source bytes without executing either."""

import ast
import difflib
import hashlib
import json
from pathlib import Path

BASE = Path("/dev/shm/ndu_windows44_checkpoint_20261107")
OUT = Path("/dev/shm/ndu_root_continuation_20261107/windows44_builder_root.json")
PINS = {
    "build_windows44_checkpoint.py": "9c923c9c67fba4f4f50cadd8d5d0fec06d6f30fde37e371942c2d3efd39197dd",
    "build_windows44_checkpoint_v2.py": "e934b2a451f748bc83bcecaca027351e8184dcce5c0e9c75a2a9a765cccbde6d",
}
sources = {}
for name, expected in PINS.items():
    raw = (BASE / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("BUILDER_IDENTITY")
    sources[name] = raw
old, new = sources.values()
preformat = (BASE / "build_windows44_checkpoint_v2.before_format.py.txt").read_bytes()
if ast.dump(ast.parse(preformat)) != ast.dump(ast.parse(new)):
    raise ValueError("FORMAT_CHANGED_AST")
delta = "".join(
    difflib.unified_diff(
        old.decode().splitlines(keepends=True),
        new.decode().splitlines(keepends=True),
        fromfile="frozen_windows44_v1",
        tofile="windows44_final_v2",
    )
).encode()
if delta != (BASE / "BUILDER_FINAL_V2_FROM_V1.patch").read_bytes():
    raise ValueError("REVIEWED_DELTA_CHANGED")
unchanged = ("need", "digest", "identity", "write", "read_reader", "verify_only")
trees = [ast.parse(raw) for raw in (old, new)]
for name in unchanged:
    functions = [
        [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        for tree in trees
    ]
    if any(len(nodes) != 1 for nodes in functions):
        raise ValueError("FUNCTION_MEMBERSHIP")
    if ast.dump(functions[0][0]) != ast.dump(functions[1][0]):
        raise ValueError("PRESERVED_FUNCTION_CHANGED")
result = {
    "decision": "PASS_SOURCE_REVISION_BINDING",
    "builder_sha256": PINS,
    "formatted_and_preformat_AST_equal": True,
    "reviewed_patch_exact_bytes": True,
    "unchanged_function_ASTs": unchanged,
    "review_scope": "Root reviewed the complete original source and exact final delta.",
    "builder_or_archived_source_executed": False,
    "new_native_qualification": False,
}
with OUT.open("x") as output:
    json.dump(result, output, indent=2)
    output.write("\n")
print(result["decision"])
