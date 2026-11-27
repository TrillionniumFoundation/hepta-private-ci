"""Zero-execution review of the visit-897 N128 grading-to-stretch repair."""

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

PACKAGE = Path("qualification/hcsn_source_migration_vjp_n128_stretch_static")
PARENT = "ec608133a275a97f6712561a08af218fee4ebe26"
IDENTITY = "hcsn-visit897-n128-stretch-field-static-20261112-c06d"
KEY = "hcsn-visit897-n128-stretch-field-static-20261112-c06d-001"
LARGE = Path("qualification/hcsn_source_migration_vjp_n128/large_adjoint.py")
SPATIAL = Path("qualification/hcsn_graded/spatial.py")
PARENT_LARGE_SHA256 = "adff7aa227287200eda6cb14fd62adaa9ed3a4b57891978baa83f35e4f26591a"
SPATIAL_SHA256 = "ad6b6865374d1f7f6ed493d6485a60be9f39795d1eb232e681f32a020f5b50f0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def class_fields(tree: ast.AST, name: str) -> dict[str, ast.expr | None]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            fields = {}
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    fields[item.target.id] = item.value
            return fields
    raise AssertionError(f"missing class: {name}")


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
        "numerical_not_authorized", request["numerical_execution_authorized"] is False
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
    check(
        "parent_large_hash_retained",
        request["exact_change"]["parent_blob_sha256"] == PARENT_LARGE_SHA256,
    )
    check("spatial_source_unchanged", actual_hashes[str(SPATIAL)] == SPATIAL_SHA256)

    names = run_git(root, "diff", "--name-only", PARENT, "HEAD").splitlines()
    expected_names = set(source["expected_changed_paths"])
    check(
        "changed_paths_exact",
        set(names) == expected_names and len(names) == len(expected_names),
    )
    numstat = run_git(root, "diff", "--numstat", PARENT, "HEAD", "--", str(LARGE))
    check("scientific_numstat_one_for_one", numstat == f"1\t1\t{LARGE}")
    patch = run_git(root, "diff", "--unified=0", PARENT, "HEAD", "--", str(LARGE))
    removed = [
        line.strip()
        for line in patch.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    added = [
        line.strip()
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    check(
        "one_removed_field_access",
        removed == ["-        or model.spatial.grading != 6.0"],
    )
    check(
        "one_added_field_access", added == ["+        or model.spatial.stretch != 6.0"]
    )

    large_text = (root / LARGE).read_text()
    large_tree = ast.parse(large_text, filename=str(LARGE))
    attrs = [
        node.attr for node in ast.walk(large_tree) if isinstance(node, ast.Attribute)
    ]
    check("no_grading_attribute_in_large_adjoint", "grading" not in attrs)
    check(
        "exact_stretch_gate_present",
        large_text.count("model.spatial.stretch != 6.0") == 1,
    )

    spatial_text = (root / SPATIAL).read_text()
    spatial_tree = ast.parse(spatial_text, filename=str(SPATIAL))
    fields = class_fields(spatial_tree, "GradedSpatialGenerator")
    check("stretch_field_exists", "stretch" in fields)
    check("grading_field_absent", "grading" not in fields)
    default = fields["stretch"]
    check(
        "stretch_default_exact",
        isinstance(default, ast.Constant) and default.value == 6.0,
    )
    check("nodes_use_stretch", spatial_text.count("self.stretch") == 4)
    check("no_compatibility_alias", "def grading" not in spatial_text)

    records = ledger["records"]
    parent = records[-1]
    check("nine_parent_records_retained", len(records) == 9)
    check(
        "latest_parent_red_exact",
        parent["run_id"] == 43285117987
        and parent["job_id"] == 131416350055
        and parent["artifact_id"] == 13973049539
        and parent["artifact_sha256"]
        == "389b82348b8a91c67f4e8523d1251fbe7efe9e3b4407eaf44469bb23bce25c84"
        and parent["status"] == "UNKNOWN_TERMINAL_NO_RESULT_NO_READMISSION"
        and parent["source_migration_setup_executed"] is True,
    )
    check("parent_key_burned", ledger["parent_key_burned"] is True)
    check("parent_key_not_reused", ledger["parent_key_reused"] is False)
    check(
        "no_inherited_qualification",
        ledger["successor_inherits_qualification"] is False,
    )
    check("unknowns_unchanged", ledger["historical_unknowns_unchanged"] is True)

    result = {
        "schema": "hcsn-visit897-n128-stretch-field-static-review-v1",
        "identity": IDENTITY,
        "idempotency_key": KEY,
        "status": "CLEAR_STRETCH_FIELD_STATIC_ONLY",
        "checks_passed": len(checks),
        "checks_failed": 0,
        "candidate_imports": 0,
        "model_forwards": 0,
        "adjoints": 0,
        "backward_attempts": 0,
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
