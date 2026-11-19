"""Standard-library-only pre-import review for the numerical successor."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

IDENTITY = (
    "hcsn-original-visit897-source-migration-vjp-n128-numerical-successor-20261112-c06d"
)
KEY = f"{IDENTITY}-001"
PARENT = "859d0f75119b792c035af54c9872b5fb7636eca6"
BRANCH = (
    "research/hcsn-visit897-source-migration-vjp-n128-numerical-successor-20261112-c06d"
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    package = root / (
        "qualification/hcsn_source_migration_vjp_n128_numerical_successor"
    )
    request = json.loads((package / "REQUEST.json").read_text())
    source = json.loads((package / "SOURCE.json").read_text())
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
        len(request["historical_red_retained"]) == 4,
        "four_historical_red_records_retained",
    )
    require(
        request["execution_policy"]
        == {
            "event": "single branch-creation push",
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
    clear = source["parent_static_clear"]
    require(clear["head"] == PARENT, "parent_clear_head_exact")
    require(clear["run_id"] == 43269501620, "parent_clear_run_exact")
    require(clear["job_id"] == 131361931939, "parent_clear_job_exact")
    require(clear["artifact_id"] == 13967801304, "parent_clear_artifact_exact")
    require(clear["checks_passed"] == 34, "parent_clear_checks_exact")
    require(clear["checks_failed"] == 0, "parent_clear_zero_failures")

    workflow = (
        root
        / ".github/workflows/hcsn-visit897-source-migration-vjp-n128-numerical-successor.yml"
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
    require("Adam" not in called, "no_adam_constructor")
    source_text = (package / "source_flow.py").read_text()
    probe_text = (package / "native_probe.py").read_text()
    require("forward_limit: int = 42" in source_text, "forward_cap_literal")
    require("adjoint_limit: int = 2" in source_text, "adjoint_cap_literal")
    require("optimizer_updates: int = 0" in source_text, "optimizer_zero_literal")
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
