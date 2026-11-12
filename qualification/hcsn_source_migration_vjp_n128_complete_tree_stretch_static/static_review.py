"""Zero-execution review of the repaired visit-897 N128 complete source tree."""

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

PACKAGE = Path(
    "qualification/hcsn_source_migration_vjp_n128_complete_tree_stretch_static"
)
PARENT = "ffcad5a6aa9bea30a66b7f217af93e7e850cd0b5"
IDENTITY = "hcsn-visit897-n128-complete-tree-stretch-static-20261112-c06d"
KEY = "hcsn-visit897-n128-complete-tree-stretch-static-20261112-c06d-001"
WORKFLOW = Path(".github/workflows/hcsn-source-migration-vjp-n128.yml")
LARGE = Path("qualification/hcsn_source_migration_vjp_n128/large_adjoint.py")
SPATIAL = Path("qualification/hcsn_graded/spatial.py")
LARGE_SHA256 = "930d2bf7f610cc61a0dcf8ef39d07aeb2ec2cb470c2acec8aa4a8df5b2ab284c"
SPATIAL_SHA256 = "ad6b6865374d1f7f6ed493d6485a60be9f39795d1eb232e681f32a020f5b50f0"
RUNTIME_SEEDS = {
    "qualification/hcsn_source_migration_vjp_n128/large_adjoint.py",
    "qualification/hcsn_source_migration_vjp_n128/native_probe.py",
    "qualification/hcsn_source_migration_vjp_n128/source_flow.py",
    "qualification/hcsn_initial_law/migration.py",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def qualification_import_path(module: str) -> str | None:
    if not module.startswith("qualification."):
        return None
    return f"{module.replace('.', '/')}.py"


def imported_qualification_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = ".".join(path.with_suffix("").parts[:-1])
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - node.level + 1]
                if node.module:
                    base.extend(node.module.split("."))
                modules.add(".".join(base))
            elif node.module:
                modules.add(node.module)
    return {
        candidate
        for module in modules
        if (candidate := qualification_import_path(module)) is not None
    }


def discover_runtime_closure(root: Path) -> set[str]:
    pending = list(RUNTIME_SEEDS)
    closure = set()
    while pending:
        relative = pending.pop()
        if relative in closure:
            continue
        path = root / relative
        if not path.is_file():
            raise AssertionError(f"missing runtime dependency: {relative}")
        closure.add(relative)
        for imported in imported_qualification_modules(path):
            if (root / imported).is_file() and imported not in closure:
                pending.append(imported)
    return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    request = json.loads((root / PACKAGE / "REQUEST.json").read_text())
    source = json.loads((root / PACKAGE / "SOURCE.json").read_text())
    ledger = json.loads((root / PACKAGE / "PARENT-RED-LEDGER.json").read_text())
    checks = {}

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks[name] = True

    check("identity_exact", request["identity"] == IDENTITY)
    check("key_exact", request["idempotency_key"] == KEY)
    check("parent_exact", request["parent_head"] == PARENT)
    check("static_only", request["static_only"] is True)
    check("no_numerical_identity", request["numerical_identity"] is None)
    check(
        "numerical_not_authorized",
        request["numerical_execution_authorized"] is False,
    )
    check(
        "all_execution_caps_zero",
        all(
            request[name] == 0
            for name in (
                "maximum_candidate_imports",
                "maximum_model_forwards",
                "maximum_adjoints",
                "maximum_backward_attempts",
                "maximum_optimizer_updates",
            )
        ),
    )
    check("global_hold", request["global_status"] == "HOLD")
    check("not_all_closed", request["all_closed"] is False)

    expected_hashes = source["source_sha256"]
    actual_hashes = {name: sha256(root / name) for name in expected_hashes}
    check("source_hashes_exact", actual_hashes == expected_hashes)
    check("repaired_large_exact", actual_hashes[str(LARGE)] == LARGE_SHA256)
    check("spatial_unchanged", actual_hashes[str(SPATIAL)] == SPATIAL_SHA256)

    closure = discover_runtime_closure(root)
    check("runtime_closure_exact", closure == set(source["runtime_closure"]))
    check("runtime_closure_manifest_bound", closure <= set(expected_hashes))

    names = run_git(root, "diff", "--name-only", PARENT, "HEAD").splitlines()
    expected_names = set(source["expected_changed_paths"])
    check(
        "changed_paths_exact",
        set(names) == expected_names and len(names) == len(expected_names),
    )
    check(
        "no_scientific_source_change",
        not any(name in closure for name in names),
    )

    records = ledger["records"]
    parent_clear = records[-2]
    inherited_red = records[-1]
    check("eleven_parent_records_retained", len(records) == 11)
    check(
        "parent_static_clear_exact",
        parent_clear["run_id"] == 43293507645
        and parent_clear["job_id"] == 131445592013
        and parent_clear["artifact_id"] == 13977608127
        and parent_clear["status"] == "CLEAR_STRETCH_FIELD_STATIC_ONLY"
        and parent_clear["optimizer_updates"] == 0,
    )
    check(
        "inherited_red_exact",
        inherited_red["run_id"] == 43293552915
        and inherited_red["job_id"] == 131445749358
        and inherited_red["status"] == "RED_OLD_SOURCE_SHA256_BINDING"
        and inherited_red["artifact_published"] is False
        and inherited_red["candidate_imports"] == 0,
    )
    check("parent_key_burned", ledger["parent_static_key_burned"] is True)
    check("parent_key_not_reused", ledger["parent_static_key_reused"] is False)
    check(
        "no_inherited_numerical_qualification",
        ledger["successor_inherits_numerical_qualification"] is False,
    )
    check(
        "historical_failures_unchanged",
        ledger["historical_failures_unchanged"] is True,
    )
    check(
        "historical_unknowns_unchanged",
        ledger["historical_unknowns_unchanged"] is True,
    )

    workflow = (root / WORKFLOW).read_text()
    check("workflow_points_to_new_package", str(PACKAGE) in workflow)
    check("workflow_key_exact", KEY in workflow)
    forbidden = (
        "native_probe",
        "pip install",
        "prlimit",
        "torch==",
        "numpy==",
        "scipy==",
        "Execute the single bounded 42-forward admission",
    )
    check(
        "workflow_has_no_numerical_lane",
        not any(text in workflow for text in forbidden),
    )

    result = {
        "schema": "hcsn-visit897-n128-complete-tree-stretch-static-review-v1",
        "identity": IDENTITY,
        "idempotency_key": KEY,
        "status": "CLEAR_COMPLETE_TREE_STRETCH_STATIC_ONLY",
        "checks_passed": len(checks),
        "checks_failed": 0,
        "runtime_closure_files": len(closure),
        "manifest_bound_files": len(expected_hashes),
        "candidate_imports": 0,
        "model_forwards": 0,
        "adjoints": 0,
        "backward_attempts": 0,
        "optimizer_updates": 0,
        "numerical_identity": None,
        "numerical_execution_authorized": False,
        "historical_failures_unchanged": True,
        "historical_unknowns_unchanged": True,
        "global_status": "HOLD",
        "all_closed": False,
        "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
