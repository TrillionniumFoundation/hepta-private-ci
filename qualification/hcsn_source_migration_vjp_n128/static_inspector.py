"""Zero-execution static inspector for the frozen N128 source-migration stage."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

IDENTITY = "hcsn-original-visit897-source-migration-vjp-n128-stage1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path("qualification/hcsn_source_migration_vjp_n128")
    request = json.loads((root / "REQUEST.json").read_text())
    inventory = json.loads((root / "SOURCE.json").read_text())
    hashes = {name: sha(name) for name in inventory["source_sha256"]}
    checks = []

    def require(condition, name):
        checks.append({"name": name, "passed": bool(condition)})
        if not condition:
            raise ValueError(name)

    require(request["identity"] == IDENTITY, "exact_identity")
    require(
        request["unique_execution_key"]
        == "hcsn-original-visit897-source-migration-vjp-n128-stage1",
        "one_unique_key",
    )
    require(
        request["maximum_calls"]
        == {"forwards": 42, "adjoints": 2, "optimizer_updates": 0},
        "exact_42F_2adjoint_0optimizer_budget",
    )
    require(request["intervals"] == 128, "N128_only")
    require(request["query_time"] == 0.02, "fixed_T_002")
    require(request["delay"] == 0.2, "fixed_delay_02")
    require(request["source_visit"] == 897, "fixed_visit897")
    require(request["source_laws"] == 1, "one_law_only")
    require(hashes == inventory["source_sha256"], "inventory_hashes_exact")
    require(
        sha(root / "inputs/SELECTED_ORIGINAL_LAW.json")
        == "7a4b7485bf224b5e343f2c17fccf4ea7ca2dfdd06121810d16c503134f9e92fb",
        "6223_selected_bytes",
    )
    require(
        sha(root / "inputs/seed37-c0_b1-step24-pos1-n128.json")
        == "8f4f77b8ba2bc1d1e3012f64ce9614711d178503601878e091b3db8e7eadaf09",
        "6234_N128_metadata_bytes",
    )
    require(
        sha(root / "inputs/seed37-c0_b1-step24-pos1-n128.npz")
        == "fda047c1a8fce3cc042246b5249859cd0a0ba449647460ba9e0a39592386ff7d",
        "6234_N128_array_bytes",
    )
    require(
        sha("qualification/hcsn_initial_law/migration.py")
        == "0e85587433dee39f583fe2c1409e127c75498c96928640890936fadaa12de517",
        "migration_source_bytes",
    )
    trees = {}
    for path in (
        root / "large_adjoint.py",
        root / "source_flow.py",
        root / "native_probe.py",
    ):
        trees[str(path)] = ast.parse(path.read_text(), filename=str(path))
    calls = [
        node
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    called_names = {
        node.func.id for node in calls if isinstance(node.func, ast.Name)
    } | {node.func.attr for node in calls if isinstance(node.func, ast.Attribute)}
    optimizer_step_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and node.func.attr == "step"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"optimizer", "optimiser"}
    ]
    require("Adam" not in called_names, "no_Adam_constructor")
    require(not optimizer_step_calls, "no_optimizer_step_call")
    require("Popen" not in called_names, "no_unbounded_child_process")
    require("run" not in called_names, "no_subprocess_run")
    source_text = (root / "source_flow.py").read_text()
    probe_text = (root / "native_probe.py").read_text()
    large_text = (root / "large_adjoint.py").read_text()
    require("forward_limit: int = 42" in source_text, "source_forward_cap_literal")
    require("adjoint_limit: int = 2" in source_text, "source_adjoint_cap_literal")
    require(
        "optimizer_updates: int = 0" in source_text, "source_optimizer_zero_literal"
    )
    require("len(directions) != 10" in probe_text, "ten_direction_denominator")
    require("FD_SCALES = (2e-4, 1e-4)" in probe_text, "two_fixed_FD_scales")
    require("TRANSPOSE_TOLERANCE = 5e-13" in probe_text, "transpose_gate_literal")
    require("MAX_STORED_SCALARS = 16000000" in large_text, "retained_scalar_cap")
    require("MAX_RHS = 100000" in large_text, "reverse_RHS_cap")
    require("MAX_STEPS = 4096" in large_text, "reverse_step_cap")
    require("MAX_JACOBIAN_NONZEROS = 50000" in large_text, "sparse_Jacobian_cap")
    require(
        '"fullnetwork_qualified": False' in probe_text
        and '"finite_domain_qualified": False' in probe_text,
        "explicit_nonqualification",
    )
    require(
        "RED_STOP_NO_READMISSION" in probe_text,
        "fail_closed_no_readmission_status",
    )
    result = {
        "identity": IDENTITY,
        "status": "CLEAR",
        "reviewed_source_commit": args.source_commit,
        "reviewed_source_sha256": hashes,
        "checks": checks,
        "candidate_imports": 0,
        "candidate_forwards": 0,
        "candidate_adjoints": 0,
        "candidate_optimizers": 0,
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
