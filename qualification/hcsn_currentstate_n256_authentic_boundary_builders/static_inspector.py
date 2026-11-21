"""AST-only admission guards for the unexecuted builder sources."""

import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
ORACLE = HERE / "oracle_boundary_builder.py"
CANDIDATE = HERE / "candidate_boundary_builder.py"
RUNNER = HERE / "compare_runner.py"


def _tree(path):
    return ast.parse(path.read_text())


def _modules(tree):
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _calls(tree):
    result = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            result.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            result.add(node.func.attr)
    return result


def _literal(tree, name):
    matches = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    if len(matches) != 1:
        raise ValueError(f"literal identity: {name}")
    return ast.literal_eval(matches[0])


def verify():
    oracle = _tree(ORACLE)
    candidate = _tree(CANDIDATE)
    runner = _tree(RUNNER)
    if _literal(oracle, "EXECUTION_ALLOWED") or _literal(candidate, "EXECUTION_ALLOWED"):
        raise ValueError("builder execution enabled")
    if _literal(runner, "EXECUTION_ALLOWED"):
        raise ValueError("runner execution enabled")
    oracle_modules = _modules(oracle)
    candidate_modules = _modules(candidate)
    runner_modules = _modules(runner)
    if any("engineering" in item or "sparse_dynamic" in item for item in oracle_modules):
        raise ValueError("oracle imports candidate lineage")
    if any("dense_oracle" in item or "oracle_boundary_builder" in item for item in candidate_modules):
        raise ValueError("candidate imports oracle lineage")
    if any("builder" in item for item in runner_modules):
        raise ValueError("runner imports a builder")
    if not any(item.endswith("boundary_codec") for item in oracle_modules):
        raise ValueError("oracle codec binding")
    if not any(item.endswith("boundary_codec") for item in candidate_modules):
        raise ValueError("candidate codec binding")
    if runner_modules != {
        "pathlib",
        "qualification.hcsn_currentstate_n256_boundary_container_contract.compare_boundary",
    }:
        raise ValueError("runner import surface")
    forbidden_import_fragments = ("scipy.sparse.linalg", "serializer", "torch")
    for module in oracle_modules | candidate_modules | runner_modules:
        if any(fragment in module for fragment in forbidden_import_fragments):
            raise ValueError(f"forbidden import: {module}")
    forbidden_calls = {
        "_action",
        "_stream_action",
        "_run_lane",
        "expm",
        "expm_multiply",
        "publish_atomic",
    }
    if (_calls(oracle) | _calls(candidate) | _calls(runner)) & forbidden_calls:
        raise ValueError("propagation or publication call")
    if _calls(runner) - {"Path", "read_bytes", "compare_exact"}:
        raise ValueError("runner call surface")
    expected_sections = {
        "extended_generator",
        "initial",
        "lower_selector",
        "discounted_selectors",
    }
    for path in (ORACLE, CANDIDATE):
        text = path.read_text()
        if not all(f'"{name}"' in text for name in expected_sections):
            raise ValueError(f"builder section coverage: {path.name}")
        if "CONTAINER_BYTES = 545171" not in text:
            raise ValueError(f"container envelope: {path.name}")
    return {
        "status": "PASS_STATIC_AUTHENTIC_BUILDERS_HOLD",
        "builders": 2,
        "authentic_builder_calls": 0,
        "comparison_calls": 0,
        "propagation_calls": 0,
    }
