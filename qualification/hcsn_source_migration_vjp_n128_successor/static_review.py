"""Zero-execution source-tree review for the visit-897 N128 successor."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

PACKAGE = Path("qualification/hcsn_source_migration_vjp_n128_successor")
EXPECTED_IDENTITY = "hcsn-original-visit897-source-tree-successor-static-20261112-c06d"
EXPECTED_KEY = (
    "hcsn-original-visit897-source-tree-successor-static-clear-20261112-c06d-001"
)
EXPECTED_MIGRATION_SHA256 = (
    "0e85587433dee39f583fe2c1409e127c75498c96928640890936fadaa12de517"
)
OLD_DESKTOP_EVIDENCE = Path(
    "qualification/hcsn_source_migration_vjp_n128/evidence/STATIC-ADMISSION-FAILED.json"
)
OLD_REVIEW_EVIDENCE = Path(
    "qualification/hcsn_source_migration_vjp_n128/evidence/STATIC-INDEPENDENT-REVIEW.json"
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

    check("new_identity_exact", request["identity"] == EXPECTED_IDENTITY)
    check("new_key_exact", request["idempotency_key"] == EXPECTED_KEY)
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
                "maximum_optimizer_updates",
            )
        ),
    )
    check(
        "format_argv_exact",
        request["format_argv"]
        == [
            "just",
            "fmt",
            "--base",
            "000e667ad7a92eae0ad314929cb4293d6bb994d6",
        ],
    )
    check("global_hold", request["global_status"] == "HOLD")
    check("not_all_closed", request["all_closed"] is False)

    expected_hashes = source["source_sha256"]
    actual_hashes = {}
    for relative in sorted(expected_hashes):
        path = root / relative
        check(f"present:{relative}", path.is_file())
        actual_hashes[relative] = sha256(path)
    check("all_manifest_hashes_exact", actual_hashes == expected_hashes)
    check(
        "migration_bytes_exact",
        actual_hashes["qualification/hcsn_initial_law/migration.py"]
        == EXPECTED_MIGRATION_SHA256,
    )

    closure = discover_runtime_closure(root)
    manifest_runtime = set(source["runtime_closure"])
    check("runtime_closure_exact", closure == manifest_runtime)
    check(
        "runtime_closure_manifest_bound",
        all(relative in expected_hashes for relative in closure),
    )

    desktop = json.loads((root / OLD_DESKTOP_EVIDENCE).read_text())
    old_review = json.loads((root / OLD_REVIEW_EVIDENCE).read_text())
    check(
        "desktop_red_retained",
        desktop["job_id"] == "1a1d086d1a2-2564-1b95"
        and desktop["authoritative_process_status"]["exit_code"] == 2
        and desktop["admission_status"] == "RED_STOP_NO_READMISSION",
    )
    check(
        "desktop_zero_execution_retained",
        all(value == 0 for value in desktop["observed_candidate_calls"].values()),
    )
    check(
        "post_failure_review_not_admission",
        old_review["review_status"] == "CLEAR_POST_FAILURE_NOT_ADMISSION"
        and old_review["numerical_execution_authorized"] is False,
    )
    hosted = ledger["records"][1]
    check(
        "hosted_missing_file_red_retained",
        hosted["run_id"] == 43263814418
        and hosted["job_id"] == 131341874598
        and hosted["missing_path"] == "qualification/hcsn_initial_law/migration.py"
        and hosted["retained_status"] == "RED_SOURCE_BIND_MISSING_FILE",
    )
    check(
        "hosted_zero_execution_retained",
        all(
            hosted[name] == 0
            for name in (
                "candidate_imports",
                "model_forwards",
                "adjoints",
                "optimizer_updates",
            )
        ),
    )
    check(
        "no_inherited_qualification",
        ledger["successor_inherits_qualification"] is False,
    )
    check("unknowns_unchanged", ledger["historical_unknowns_unchanged"] is True)

    workflow = (
        root / ".github/workflows/hcsn-source-migration-vjp-n128.yml"
    ).read_text()
    check(
        "workflow_format_call_exact",
        "just fmt --base 000e667ad7a92eae0ad314929cb4293d6bb994d6" in workflow,
    )
    forbidden = (
        "just fmt -- --base",
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
        "schema": "hcsn-source-tree-successor-static-review-v1",
        "identity": EXPECTED_IDENTITY,
        "idempotency_key": EXPECTED_KEY,
        "status": "CLEAR_SOURCE_TREE_STATIC_ONLY",
        "checks_passed": len(checks),
        "checks_failed": 0,
        "runtime_closure_files": len(closure),
        "manifest_bound_files": len(expected_hashes),
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
