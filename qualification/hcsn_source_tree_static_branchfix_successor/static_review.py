"""Independent zero-execution review for the branch-binding successor."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

PACKAGE = Path("qualification/hcsn_source_tree_static_branchfix_successor")
ORIGINAL_PARENT_PACKAGE = Path("qualification/hcsn_source_migration_vjp_n128_successor")
PRIOR_SUCCESSOR_PACKAGE = Path("qualification/hcsn_source_tree_static_just_successor")
IDENTITY = "hcsn-original-visit897-source-tree-static-branchfix-successor-20261112-c06d"
KEY = (
    "hcsn-original-visit897-source-tree-static-branchfix-successor-clear-"
    "20261112-c06d-001"
)
PARENT_HEAD = "c53211b70163c217d79bf3c218c7a7dd883ee2af"
EXPECTED_JUST_ACTION_SHA256 = (
    "c3cd9dbcbe45215f172f76ecb827ca90db329e76c6caffed7b3c156565d4587d"
)
RUNTIME_SEEDS = {
    "qualification/hcsn_source_migration_vjp_n128/large_adjoint.py",
    "qualification/hcsn_source_migration_vjp_n128/native_probe.py",
    "qualification/hcsn_source_migration_vjp_n128/source_flow.py",
    "qualification/hcsn_initial_law/migration.py",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    request = json.loads((root / PACKAGE / "REQUEST.json").read_text())
    source = json.loads((root / PACKAGE / "SOURCE.json").read_text())
    original_parent_source = json.loads(
        (root / ORIGINAL_PARENT_PACKAGE / "SOURCE.json").read_text()
    )
    prior_successor_source = json.loads(
        (root / PRIOR_SUCCESSOR_PACKAGE / "SOURCE.json").read_text()
    )
    ledger = json.loads((root / PACKAGE / "PARENT-RED-LEDGER.json").read_text())
    provenance = json.loads(args.provenance.read_text())
    checks = {}

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks[name] = True

    check("identity_exact", request["identity"] == IDENTITY)
    check("key_exact", request["idempotency_key"] == KEY)
    check("parent_exact", request["parent_head"] == PARENT_HEAD)
    check("static_only", request["static_only"] is True)
    check("no_numerical_identity", request["numerical_identity"] is None)
    check(
        "numerical_not_authorized",
        request["numerical_execution_authorized"] is False,
    )
    check(
        "zero_execution_caps",
        all(
            request[name] == 0
            for name in (
                "maximum_candidate_imports",
                "maximum_model_forwards",
                "maximum_adjoints",
                "maximum_optimizer_updates",
            )
        ),
    )
    check(
        "format_argv_exact",
        request["format_argv"] == ["just", "fmt", "--base", PARENT_HEAD],
    )
    check("global_hold", request["global_status"] == "HOLD")
    check("not_all_closed", request["all_closed"] is False)

    check("just_version_exact", provenance["version"] == "just 1.51.0")
    check("just_path_absolute", Path(provenance["executable_path"]).is_absolute())
    check("just_executable_sha256_shape", len(provenance["executable_sha256"]) == 64)
    check(
        "just_action_sha256_exact",
        provenance["setup_action_sha256"] == EXPECTED_JUST_ACTION_SHA256,
    )
    check(
        "just_installer_source_exact",
        provenance["installer_action"]
        == "taiki-e/install-action@44c6d64aa62cd779e873306675c7a58e86d6d532"
        and provenance["tool_spec"] == "just@1.51.0",
    )

    original_parent_hashes = original_parent_source["source_sha256"]
    check("original_parent_manifest_count", len(original_parent_hashes) == 27)
    check(
        "original_parent_manifest_hashes_exact",
        {
            relative: sha256(root / relative)
            for relative in sorted(original_parent_hashes)
        }
        == original_parent_hashes,
    )
    prior_successor_hashes = prior_successor_source["source_sha256"]
    check("prior_successor_manifest_count", len(prior_successor_hashes) == 7)
    check(
        "prior_successor_manifest_hashes_exact",
        {
            relative: sha256(root / relative)
            for relative in sorted(prior_successor_hashes)
        }
        == prior_successor_hashes,
    )
    successor_hashes = source["source_sha256"]
    check(
        "successor_manifest_hashes_exact",
        {relative: sha256(root / relative) for relative in sorted(successor_hashes)}
        == successor_hashes,
    )
    check(
        "prior_successor_inventory_bound",
        sha256(root / PRIOR_SUCCESSOR_PACKAGE / "SOURCE.json")
        == request["parent_successor_inventory_sha256"],
    )
    check(
        "setup_action_bound",
        successor_hashes[".github/actions/setup-ci-tools/action.yml"]
        == EXPECTED_JUST_ACTION_SHA256,
    )

    closure = discover_runtime_closure(root)
    check("runtime_closure_count", len(closure) == 11)
    check("runtime_closure_exact", closure == set(source["runtime_closure"]))
    check(
        "runtime_closure_original_parent_bound",
        all(relative in original_parent_hashes for relative in closure),
    )

    records = ledger["records"]
    check("four_parent_red_records", len(records) == 4)
    check(
        "parent_red_counts_zero",
        all(
            all(
                record[name] == 0
                for name in (
                    "candidate_imports",
                    "model_forwards",
                    "adjoints",
                    "optimizer_updates",
                )
            )
            for record in records
        ),
    )
    check("old_keys_not_reissued", ledger["old_keys_reissued"] is False)
    check(
        "no_inherited_qualification",
        ledger["successor_inherits_qualification"] is False,
    )
    check("unknowns_unchanged", ledger["historical_unknowns_unchanged"] is True)

    workflow = (
        root / ".github/workflows/hcsn-source-tree-static-branchfix-successor.yml"
    ).read_text()
    expected_branch_line = f"      - {request['expected_branch']}"
    check(
        "workflow_push_branch_exact",
        workflow.count(expected_branch_line) == 1
        and f"    branches:\n{expected_branch_line}\n" in workflow,
    )
    check("workflow_setup_action", "uses: ./.github/actions/setup-ci-tools" in workflow)
    check(
        "workflow_format_exact",
        f"just fmt --base {PARENT_HEAD}" in workflow,
    )
    forbidden = (
        "native_probe",
        "pip install",
        "prlimit",
        "torch==",
        "numpy==",
        "scipy==",
        "42-forward",
        "optimizer.step",
    )
    check(
        "workflow_has_no_numerical_lane",
        not any(item in workflow for item in forbidden),
    )

    result = {
        "schema": "hcsn-source-tree-static-branchfix-successor-review-v1",
        "identity": IDENTITY,
        "idempotency_key": KEY,
        "status": "CLEAR_SOURCE_TREE_STATIC_ONLY",
        "checks_passed": len(checks),
        "checks_failed": 0,
        "original_parent_manifest_files": len(original_parent_hashes),
        "prior_successor_manifest_files": len(prior_successor_hashes),
        "successor_manifest_files": len(successor_hashes),
        "runtime_closure_files": len(closure),
        "just_version": provenance["version"],
        "just_executable_path": provenance["executable_path"],
        "just_executable_sha256": provenance["executable_sha256"],
        "candidate_imports": 0,
        "model_forwards": 0,
        "adjoints": 0,
        "optimizer_updates": 0,
        "numerical_identity": None,
        "numerical_execution_authorized": False,
        "historical_red_retained": True,
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
