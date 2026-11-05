#!/usr/bin/env python3
"""Verify retained public identities and arithmetic; does not execute weights."""

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    raw = (ROOT / name).read_bytes()
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate JSON field")
            out[key] = value
        return out
    def nonfinite(_):
        raise ValueError("nonfinite JSON value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def main():
    review = read("INDEPENDENT_PROBE_REVIEW.json")
    capture = read("capture_receipt.json")
    require(sha((ROOT / "public_snapshot.json").read_bytes()) == capture["public_snapshot_sha256"],
            "snapshot original-byte identity")
    for key, source in (("audit_source_sha256", "audit_live.py"),
                        ("sanitizer_source_sha256", "sanitize_export.py"),
                        ("driver_sha256", "capture_final.py")):
        require(sha((ROOT / source).read_bytes()) == capture[key], "capture source identity")
    snapshot = read("public_snapshot.json")
    require(snapshot["adapter"]["parameter_count"] == 2379 and snapshot["adapter"]["tensor_count"] == 6,
            "observed tensor dimensions")
    require(snapshot["adapter"]["all_finite"] and not snapshot["performance_qualified"],
            "static snapshot scope")
    protocols = {}
    total_cpu = 0.
    for name, source in (("first", "probe_adapter_heads_attempt1.py"),
                         ("diagnostic", "probe_adapter_heads_diagnostic.py")):
        record = review["attempts"][name]
        for filename, identity in record["files"].items():
            raw = (ROOT / "probes" / name / filename).read_bytes()
            require(len(raw) == identity["bytes"] and sha(raw) == identity["sha256"],
                    f"{name}/{filename} original-byte identity")
        protocol = read(f"probes/{name}/PROTOCOL_FROZEN.json")
        result = read(f"probes/{name}/RESULTS.json")
        supervisor = read(f"probes/{name}/SUPERVISOR_RECEIPT.json")
        require(sha((ROOT / source).read_bytes()) == supervisor["source_sha256"], "probe source identity")
        require(result["protocol_sha256"] == sha((ROOT / "probes" / name / "PROTOCOL_FROZEN.json").read_bytes()),
                "protocol execution identity")
        expected_stdout = (json.dumps({"status": result["status"],
            "result_sha256": sha((ROOT / "probes" / name / "RESULTS.json").read_bytes())}) + "\n").encode()
        require(sha(expected_stdout) == supervisor["stdout_sha256"], "retained result-to-stdout identity")
        require(supervisor["exit_code"] == 2 and result["status"] == record["status"], "failure retained")
        for field in ("production_mutated", "training_executed", "full_model_forward_executed",
                      "trader_value_qualified", "private_weights_or_rows_exported", "gpu_initialized"):
            require(result[field] is False, "unsupported execution or efficacy claim")
        require(protocol["seed"] == 20261105 and protocol["probes_per_layer"] == 16 and
                protocol["atol"] == protocol["rtol"] == 0.00002, "unchanged fixed probe")
        total_cpu += supervisor["child_user_cpu_seconds"] + supervisor["child_system_cpu_seconds"]
        protocols[name] = protocol
    for key in ("expected", "source_sha256", "class_ast_sha256", "seed", "probes_per_layer",
                "atol", "rtol", "matrix_atol", "matrix_rtol"):
        require(protocols["first"][key] == protocols["diagnostic"][key], "diagnostic changed frozen comparison")
    result = read("probes/diagnostic/RESULTS.json")
    require(result["live_binding_stable"] and result["memory_only_restore_verified"], "diagnostic completion")
    layers = result["layers"]
    require([row["name"] for row in layers] == ["scorer.1", "scorer.3", "act_head.2"], "complete layer set")
    for row in layers:
        require(row["all_changes_within_declared_mask"] and row["base_weight_bias_unchanged"] and
                row["parent_restore_output_bytes_exact"], "mask or restoration check")
        for side in ("parent", "child"):
            check = row["probes"][side]
            require(check["effective_matrix_reference_pass"], "effective matrix reference")
            if row["name"] == "scorer.1":
                require(check["allclose"] is False and check["failed_elements"] == 5 and
                        check["failed_elements_by_probe"] == [0] * 5 + [5] + [0] * 10,
                        "original fixed failure changed")
            else:
                require(check["allclose"] and check["failed_elements"] == 0, "other head fixed gate")
            require(check["roundoff_bound_is_outward_exact_certificate"] is False, "diagnostic overclaim")
    relative = math.sqrt(sum(row["effective_delta_l2_squared"] for row in layers) /
                         sum(row["parent_l2_squared"] for row in layers))
    require(relative == result["global_relative_l2_f64"], "three-head relative norm arithmetic")
    require(sum(row["effective_changed_f32_coordinates"] for row in layers) == 3968,
            "changed coordinate accounting")
    require(abs(total_cpu - 4.058811) < 1e-12, "complete child CPU accounting")
    private = read("PRIVATE_INPUT_SNAPSHOT_RECEIPT.json")
    require(sha((ROOT / "capture_private_inputs.py").read_bytes()) == private["source_sha256"],
            "private preservation source identity")
    require(private["live_binding_stable"] and not private["original_files_changed"] and
            not private["base_model_copied"] and not private["atomic_cross_file_snapshot"],
            "private preservation scope")
    require(private["files"]["candidate_adapter.safetensors"]["sha256"] ==
            protocols["first"]["expected"]["adapter_sha256"], "private candidate identity")
    print(json.dumps({"status": "PASS_RETAINED_PUBLIC_RECORDS_ONLY", "original_forward_gate": "FAIL_RETAINED",
                      "trader_value_qualified": False, "additional_model_executions": 0,
                      "complete_probe_child_cpu_seconds": total_cpu,
                      "three_head_relative_l2_f64": relative}, sort_keys=True))


if __name__ == "__main__":
    main()
