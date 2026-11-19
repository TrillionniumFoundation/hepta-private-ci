"""Standard-library-only pre-import review for the stretch-field successor."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

IDENTITY = "hcsn-visit897-n128-stretch-vjp-20261112-c06d"
KEY = f"{IDENTITY}-001"
PARENT = "0b50f80c3ee8d4652d220bde5be2944e72ca803e"
BYTE_GATE_PARENT = "37672f24f828989f328de42dbd7b70603038e04a"
BRANCH = "research/hcsn-visit897-n128-stretch-vjp-20261112-c06d"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    package = root / (
        "qualification/hcsn_source_migration_vjp_n128_stretch_attempt"
    )
    request = json.loads((package / "REQUEST.json").read_text())
    source = json.loads((package / "SOURCE.json").read_text())
    forensic = json.loads((package / "FORENSIC.json").read_text())
    checks = []

    def require(value, name):
        checks.append({"name": name, "passed": bool(value)})
        if not value:
            raise AssertionError(name)

    hashes = {name: sha(root / name) for name in source.get("source_sha256", {})}
    require(request["identity"] == IDENTITY, "identity_exact")
    require(request["unique_execution_key"] == KEY, "unique_key_exact")
    require(request["parent_head"] == PARENT, "parent_head_exact")
    require(source["parent_head"] == PARENT, "source_parent_head_exact")
    require(hashes == source["source_sha256"], "all_source_hashes_exact")
    require(
        request["maximum_calls"]
        == {
            "candidate_forwards": 42,
            "continuous_adjoint_calls": 2,
            "backward_attempts": 2,
            "optimizer_updates": 0,
        },
        "exact_call_denominator",
    )
    require(len(request["directions"]) == 10, "ten_fixed_directions")
    require(request["fd_scales"] == [0.0002, 0.0001], "two_fixed_fd_scales")
    require(
        request["transpose_gate"]
        == {
            "coordinates": 125,
            "absolute_tolerance": 5e-13,
            "independent_fraction_recompute": True,
        },
        "all_125_transpose_coordinates",
    )
    require(len(request["negative_guards"]) == 12, "twelve_negative_guards")
    require(
        len(request["historical_records_retained"]) == 12,
        "twelve_historical_records_retained",
    )
    require(
        request["execution_policy"]
        == {
            "event": "single branch-creation push after Draft PR",
            "github_run_attempt": 1,
            "retry_same_key": False,
            "tuning_after_failure": False,
            "stop_on_any_red_or_unknown": True,
            "preserve_raw_originals": True,
        },
        "one_attempt_fail_closed_policy",
    )
    require(request["numerical_execution_authorized"] is True, "admission_authorized")
    require(request["global_status"] == "HOLD", "global_hold")
    require(request["all_closed"] is False, "all_closed_false")
    require(
        forensic["parent_red"]
        == {
            "pr": 6266,
            "head": BYTE_GATE_PARENT,
            "run_id": 43272612558,
            "job_id": 131372742074,
            "artifact_id": 13967868905,
            "artifact_sha256": (
                "ac1b6fb49a610120a7f9a5b8fe6d81a7c827729c004e4fca89a6fb73203a5203"
            ),
            "terminal_status": "UNKNOWN_TERMINAL_NO_RESULT_NO_READMISSION",
        },
        "parent_red_exact",
    )
    require(
        forensic["first_exact_mismatch"]["field"] == "active"
        and forensic["first_exact_mismatch"]["coordinate"] == [1]
        and forensic["first_exact_mismatch"]["ulp_error"] == 1,
        "first_mismatch_exact",
    )
    recompute = forensic["original_exact_migrate_recompute"]
    require(recompute["active_mismatches"] == 0, "exact_migrate_active_zero")
    require(recompute["content_mismatches"] == 0, "exact_migrate_content_zero")
    require(
        recompute["maximum_absolute_error"] == 0.0,
        "exact_migrate_maximum_absolute_error_zero",
    )
    require(
        recompute["exporter_operation"]
        == "migrate(basis, probability, content).solve_inputs()",
        "exact_migrate_exporter_operation_exact",
    )
    require(
        recompute["accumulation"]
        == (
            "decimal-round-trip Fraction coefficients and exact lift weights; "
            "final-scalar FP64 conversion"
        ),
        "exact_migrate_accumulation_provenance_exact",
    )
    require(
        next(
            item
            for item in request["historical_records_retained"]
            if item["kind"] == "hosted_reviewer_schema_preimport_failure"
        )
        == {
            "kind": "hosted_reviewer_schema_preimport_failure",
            "run_id": 43275048169,
            "job_id": 131381121252,
            "artifact_id": None,
            "artifacts_found": 0,
            "unique_execution_key": (
                "hcsn-original-visit897-source-migration-vjp-n128-"
                "exact-migrate-successor-20261112-c06d-001"
            ),
            "candidate_imports": 0,
            "candidate_forwards": 0,
            "continuous_adjoint_calls": 0,
            "optimizer_updates": 0,
            "status": "RED_PREIMPORT_REVIEWER_SCHEMA_NO_ARTIFACT_NO_READMISSION",
        },
        "parent_reviewer_schema_red_exact",
    )
    require(
        next(
            item
            for item in request["historical_records_retained"]
            if item["kind"] == "hosted_ast_set_count_preimport_failure"
        )
        == {
            "kind": "hosted_ast_set_count_preimport_failure",
            "run_id": 43277019131,
            "job_id": 131388014924,
            "artifact_id": None,
            "artifacts_found": 0,
            "unique_execution_key": (
                "hcsn-original-visit897-source-migration-vjp-n128-"
                "reviewer-schema-successor-20261112-c06d-001"
            ),
            "candidate_imports": 0,
            "candidate_forwards": 0,
            "continuous_adjoint_calls": 0,
            "backward_attempts": 0,
            "optimizer_updates": 0,
            "status": "RED_PREIMPORT_AST_SET_COUNT_NO_ARTIFACT_NO_READMISSION",
        },
        "parent_ast_set_count_red_exact",
    )
    require(
        next(
            item
            for item in request["historical_records_retained"]
            if item["kind"] == "hosted_inventory_manifest_preimport_failure"
        )
        == {
            "kind": "hosted_inventory_manifest_preimport_failure",
            "run_id": 43283690593,
            "job_id": 131411347208,
            "artifact_id": None,
            "artifacts_found": 0,
            "unique_execution_key": (
                "hcsn-original-visit897-source-migration-vjp-n128-"
                "ast-count-successor-20261112-c06d-001"
            ),
            "candidate_imports": 0,
            "candidate_forwards": 0,
            "continuous_adjoint_calls": 0,
            "backward_attempts": 0,
            "optimizer_updates": 0,
            "status": "RED_PREIMPORT_SOURCE_SHA256_MISSING_NO_ARTIFACT_NO_READMISSION",
        },
        "parent_inventory_manifest_red_exact",
    )
    clear = source["parent_static_clear"]
    require(
        clear["head"] == PARENT,
        "parent_static_clear_head_exact",
    )
    require(clear["run_id"] == 43295541106, "parent_clear_run_exact")
    require(clear["job_id"] == 131452747276, "parent_clear_job_exact")
    require(clear["artifact_id"] == 13978213955, "parent_clear_artifact_exact")
    require(
        clear["artifact_sha256"]
        == "9ef74498fab4e22584c9177f7e17babca074e3b196023097d33d80d4c9f669b1",
        "parent_clear_artifact_sha_exact",
    )
    require(clear["checks_passed"] == 27, "parent_clear_checks_exact")
    require(clear["checks_failed"] == 0, "parent_clear_zero_failures")

    workflow = (
        root
        / ".github/workflows/hcsn-visit897-n128-stretch-vjp.yml"
    ).read_text()
    require(f"      - {BRANCH}" in workflow, "workflow_branch_exact")
    require(f"  group: {KEY}" in workflow, "workflow_key_exact")
    require(
        "GITHUB_RUN_ATTEMPT: ${{ github.run_attempt }}" in workflow, "run_attempt_bound"
    )
    require("prlimit" in workflow, "kernel_resource_cap_present")
    require("--as=3221225472" in workflow, "address_space_cap_literal")
    require("--cpu=900" in workflow, "cpu_cap_literal")
    require("timeout=1000" in workflow, "wall_cap_literal")
    require("numpy==2.3.5" in workflow, "numpy_pin")
    require("scipy==1.17.0" in workflow, "scipy_pin")
    require("torch==2.8.0" in workflow, "torch_pin")
    require(
        f"just fmt --base {PARENT}" in workflow,
        "repository_format_gate_exact",
    )

    trees = {
        name: ast.parse((package / name).read_text(), filename=name)
        for name in ("source_flow.py", "native_probe.py")
    }
    calls = [
        node
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    called = {node.func.id for node in calls if isinstance(node.func, ast.Name)} | {
        node.func.attr for node in calls if isinstance(node.func, ast.Attribute)
    }
    migrate_calls = sum(
        isinstance(node.func, ast.Name) and node.func.id == "migrate" for node in calls
    )
    require("Adam" not in called, "no_adam_constructor")
    require("migrate" in called, "original_exact_migrate_called")
    source_text = (package / "source_flow.py").read_text()
    probe_text = (package / "native_probe.py").read_text()
    require("forward_limit: int = 42" in source_text, "forward_cap_literal")
    require("adjoint_limit: int = 2" in source_text, "adjoint_cap_literal")
    require("optimizer_updates: int = 0" in source_text, "optimizer_zero_literal")
    require(migrate_calls == 2, "freeze_and_runtime_use_exact_migrate_twice")
    require("probability[:17] @" not in source_text, "no_prerounded_probability_matmul")
    require("lift_float.T @ content" not in source_text, "no_prerounded_content_matmul")
    require("FD_SCALES = (2e-4, 1e-4)" in probe_text, "fd_literals")
    require("TRANSPOSE_TOLERANCE = 5e-13" in probe_text, "transpose_literal")
    require("RED_STOP_NO_READMISSION" in probe_text, "red_stop_literal")
    require('"fullnetwork_qualified": False' in probe_text, "fullnetwork_not_qualified")
    require('"migration_domain_qualified": False' in probe_text, "domain_not_qualified")

    result = {
        "identity": IDENTITY,
        "unique_execution_key": KEY,
        "status": "CLEAR_NUMERICAL_ADMISSION_PREIMPORT",
        "checks": checks,
        "checks_passed": len(checks),
        "checks_failed": 0,
        "candidate_imports": 0,
        "candidate_forwards": 0,
        "adjoints": 0,
        "optimizer_updates": 0,
        "global_status": "HOLD",
        "all_closed": False,
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

