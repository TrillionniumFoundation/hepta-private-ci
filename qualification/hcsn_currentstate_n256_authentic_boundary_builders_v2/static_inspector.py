"""Static guards for the symmetric layout repair; never import a builder."""

import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
ORACLE = HERE / "oracle_boundary_builder.py"
CANDIDATE = HERE / "candidate_boundary_builder.py"
COMPARATOR = HERE / "compare_runner.py"


def _tree(path):
    return ast.parse(path.read_text())


def _modules(tree):
    result = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            result.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _calls(tree, name):
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func.id if isinstance(node.func, ast.Name) else (
            node.func.attr if isinstance(node.func, ast.Attribute) else None
        )
        if target == name:
            result.append(node)
    return result


def verify():
    oracle, candidate, comparator = map(_tree, (ORACLE, CANDIDATE, COMPARATOR))
    forbidden = {"numpy", "scipy", "torch"}
    if (_modules(oracle) | _modules(candidate) | _modules(comparator)) & forbidden:
        raise ValueError("top-level numerical import")
    for name, tree in (("oracle", oracle), ("candidate", candidate)):
        calls = _calls(tree, "ascontiguousarray")
        if len(calls) != 1 or len(calls[0].args) != 1:
            raise ValueError(f"{name} canonicalization denominator")
        keywords = {item.arg: ast.literal_eval(item.value) for item in calls[0].keywords}
        if keywords != {"dtype": "<f8"}:
            raise ValueError(f"{name} canonicalization dtype")
        if len(_calls(tree, "build_boundary")):
            raise ValueError(f"{name} calls another builder")
    if any("boundary_builders" in module for module in _modules(comparator)):
        raise ValueError("comparator imports builder")
    if len(_calls(comparator, "compare_exact")) != 1:
        raise ValueError("comparator call denominator")
    return {
        "status": "PASS_V2_SOURCE_ONLY_LAYOUT_REPAIR",
        "canonicalizations_per_builder": 1,
        "authentic_reads": 0,
        "builder_calls": 0,
        "numerical_imports": 0,
        "execution_keys": 0,
    }
