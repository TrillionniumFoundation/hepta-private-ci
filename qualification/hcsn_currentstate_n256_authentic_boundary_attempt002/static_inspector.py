"""AST and workflow guards that perform no authentic or numerical work."""

import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = HERE / "run.py"
AUDIT = HERE / "audit.py"
GUARD = HERE / "resource_guard.py"
WORKFLOW = ROOT / ".github/workflows/hcsn-currentstate-n256-authentic-boundary-attempt002.yml"


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


def _call_lines(tree, name):
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func.id if isinstance(node.func, ast.Name) else (
            node.func.attr if isinstance(node.func, ast.Attribute) else None
        )
        if target == name:
            result.append(node.lineno)
    return result


def verify():
    run, audit, guard = _tree(RUN), _tree(AUDIT), _tree(GUARD)
    forbidden = {"numpy", "scipy", "torch"}
    if (_modules(run) | _modules(audit) | _modules(guard)) & forbidden:
        raise ValueError("top-level numerical import")
    if any("boundary_builders_v2" in module for module in _modules(run)):
        raise ValueError("top-level builder import")
    if any("boundary_builders_v2" in module or "boundary_container_contract" in module for module in _modules(audit)):
        raise ValueError("audit lineage import")
    admit = _call_lines(run, "admit")
    dynamic_imports = _call_lines(run, "import_module")
    if len(admit) != 1 or len(dynamic_imports) != 3 or admit[0] >= min(dynamic_imports):
        raise ValueError("admission/import order")
    if _call_lines(run, "build_boundary") != sorted(_call_lines(run, "build_boundary")):
        raise ValueError("builder order")
    if len(_call_lines(run, "build_boundary")) != 2:
        raise ValueError("builder call denominator")
    if len(_call_lines(run, "compare_published")) != 1:
        raise ValueError("exact comparator denominator")
    run_source = RUN.read_text()
    v2_modules = (
        "qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2.oracle_boundary_builder",
        "qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2.candidate_boundary_builder",
        "qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2.compare_runner",
    )
    if not all(f'"{module}"' in run_source for module in v2_modules):
        raise ValueError("v2 builder identity")
    if '"qualification.hcsn_currentstate_n256_authentic_boundary_builders.' in run_source:
        raise ValueError("attempt001 builder lineage")
    workflow = WORKFLOW.read_text()
    required = (
        "research/hcsn-n256-authentic-boundary-attempt002-20261121-c06d",
        "hcsn-n256-authentic-boundary-hosted-20261121-c06d-002",
        "runs-on: ubuntu-24.04",
        "python-version: 3.12.3",
        "timeout-minutes: 10",
        "--only-binary=:all:",
        "if: always()",
        "terminal --enforce",
    )
    if not all(value in workflow for value in required):
        raise ValueError("workflow admission surface")
    if "pull_request:" in workflow or "continue-on-error" in workflow:
        raise ValueError("workflow retry or PR execution surface")
    return {
        "status": "PASS_ATTEMPT002_STATIC_ADMISSION",
        "builder_calls": 0,
        "authentic_reads": 0,
        "numerical_imports": 0,
        "new_execution_keys": 1,
    }
