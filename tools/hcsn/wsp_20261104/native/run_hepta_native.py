#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Cross-check native planning and guarded editing on a published Hepta head.

This is numerical/operator qualification on 64 ORIGINAL TRAIN rows, never a new
held-out utility result. The full nonlinear policy experiment is separate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

from run_current100k_native import Mcp, encode_weight, pin_binary, sha, verify_binary

FIXTURE_SHA = "6230881d25b9511d176fefd31778a6552444e22d2c0d8a8afaa7ad40eb3975c1"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["binary", "fixture", "work-dir", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    started = time.perf_counter()
    fixture_bytes = args.fixture.read_bytes()
    assert sha(fixture_bytes) == FIXTURE_SHA, "fixture commitment differs"
    f = json.loads(fixture_bytes)
    work = args.work_dir.resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    config = work / "runtime.json"
    config.write_text(json.dumps({"state_dir": str(work / "state"),
        "controller_workspace_roots": [str(work)], "weight_workers": {},
        "hosts": {"unused": {"ssh_target": "unused.invalid",
            "remote_state_dir": str(work / "unused"), "allow_execute": False}}}))
    pinned, binary_sha, binary_stat = pin_binary(args.binary.resolve(), work)
    mcp = Mcp(pinned, config, work / "mcp.stderr.log")
    try:
        plan = mcp.call("weight_linear_ridge_plan", {
            "features": f["features"], "targets": f["targets"],
            "sample_weights": f["sample_weights"], "base_weights": f["base_weights"],
            "lambda": f["lambda_"]})
        error = float(np.max(np.abs(np.asarray(plan["weights_f64"]) - f["expected_weights"])))
        assert error <= 1e-10, ("native/NumPy parameter mismatch", error)
        assert plan["training_targets_used"] and plan["gradient_steps"] == 0
        assert not plan["source_weights_verified"] and not plan["production_eligible"]
        parent = np.array(f["base_weights"] + [f["frozen_belief_weights"]], dtype=np.float32)
        original = encode_weight(parent)
        source = work / "head-f32-affine.safetensors"
        source.write_bytes(original)
        source_sha = sha(original)
        inputs = np.asarray(f["features"], dtype=np.float32).tolist()
        before = mcp.call("weight_linear_forward", {"source": {"kind": "path",
            "path": str(source), "expected_sha256": source_sha, "tensor_name": "weight"},
            "inputs": inputs, "bias": None})
        # The fourth output is the raw frozen belief logit. Its native baseline
        # output is used as a preservation target; no posterior is fed to inference.
        target = np.c_[np.asarray(f["targets"], dtype=np.float32),
                       np.asarray(before["outputs"], dtype=np.float32)[:, 3]].tolist()
        params = {"patch": {"path": str(source), "expected_sha256": source_sha,
                  "tensor_name": "weight", "edits": plan["f32_element_edits"]},
            "inputs": inputs, "bias": None,
            "objective": {"kind": "squared_error", "targets": target},
            "minimum_gain": 0.0,
            "constraints": [{"kind": "preserve", "column": 3, "max_absolute_change": 0.0}]}
        accepted = mcp.call("weight_guarded_linear_patch", params)
        assert accepted["outcome"] == "accepted_on_supplied_rows"
        assert source.read_bytes() == original
        params["constraints"].append({"kind": "preserve", "column": 0, "max_absolute_change": 0.0})
        rejected = mcp.call("weight_guarded_linear_patch", params)
        assert rejected["outcome"] == "rejected_and_restored"
        assert rejected["gain"] > 0 and rejected["candidate_constraint_violations"] == [1]
        assert accepted["candidate"]["sha256"] == rejected["candidate"]["sha256"]
        assert Path(rejected["restoration"]["artifact_path"]).read_bytes() == original
        assert source.read_bytes() == original
        # Whole-row bytes are preserved, not only a few matching predictions.
        candidate_raw = Path(accepted["candidate"]["artifact_path"]).read_bytes()
        assert candidate_raw[-49*4:] == original[-49*4:]
    finally:
        mcp.close()
    verify_binary(pinned, binary_sha, binary_stat)
    (work / "receipts.json").write_text(json.dumps({"plan": plan, "accepted": accepted,
        "forced_constraint_rejection": rejected}, indent=2, allow_nan=False) + "\n")
    summary = {"schema": "hepta.real-continuation-head.native-qualification.v1",
        "fixture_sha256": FIXTURE_SHA, "source_model_sha256": f["source_model_sha256"],
        "source_commit": f["source_commit"], "binary_sha256": binary_sha,
        "executed_binary_unchanged": True,
        "driver_sha256": sha(Path(__file__).read_bytes()), "original_train_rows": 64,
        "helper_sha256": sha(Path(__file__).with_name("run_current100k_native.py").read_bytes()),
        "features_with_explicit_bias": 49, "edited_heads": f["heads"],
        "native_f64_vs_numpy_weights_max_absolute": error,
        "planner_diagnostics": plan["diagnostics"], "changed_f32_elements": plan["f32_edit_count"],
        "base_f32_rounding_max_absolute": plan["base_f32_rounding_max_absolute"],
        "candidate_f32_rounding_max_absolute": plan["candidate_f32_rounding_max_absolute"],
        "native_plan_wall_seconds": plan["native_operation_wall_seconds"],
        "native_guard_wall_seconds": [accepted["native_operation_wall_seconds"], rejected["native_operation_wall_seconds"]],
        "accepted_on_supplied_train_rows": accepted["accepted"],
        "unweighted_four_output_mse_before": -accepted["primary_before"],
        "unweighted_four_output_mse_after": -accepted["primary_after"],
        "unweighted_mse_scope": "3 continuation targets plus unchanged raw belief-logit target; different from per-head weighted proximal fitting objective",
        "frozen_belief_row_bytes_preserved": True, "source_bytes_unchanged": True,
        "forced_constraint_failure_rejected_and_bytes_restored": True,
        "forced_failure_is_natural_model_failure": False,
        "lowered_parent_sha256": source_sha, "lowered_candidate_sha256": accepted["candidate"]["sha256"],
        "driver_wall_seconds": time.perf_counter()-started, "independent_holdout_verified": False,
        "production_eligible": False, "new_end_to_end_utility_evidence": False,
        "scope": "actual published F64 head numerical fixture explicitly rounded to F32; no full CTMC graph, new episodes, live update or task-utility claim",
        "cost_excludes": ["original training", "feature construction", "teacher construction", "candidate selection", "compilation", "LLM usage", "energy"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary, allow_nan=False))


if __name__ == "__main__":
    main()
