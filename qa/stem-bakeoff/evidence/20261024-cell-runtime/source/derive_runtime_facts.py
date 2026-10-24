"""Extract fixed 770D engineering observations; no fitting, scoring or resampling."""

import argparse
import hashlib
import json
from pathlib import Path


PINS = {
    "bundle/manifest.json": "266af205b6053df3c3968d2de52ff6ede8d8ebc6add3909fa7bc081cd52a6fdc",
    "bundle/bundle.json": "3bdcd2d9846acbb30f4a45337e79e79c675a5ceb2ea36c41549c281fbcb59606",
    "training/report.json": "4863df412e16b0e46c155e1faa7b98fbb8f03f21c6d7a0bee1e066b2df0c79ee",
    "serving/report.json": "15d4c5e235308c033b3413ce4e5ee225432ed5c684367a71573f472eb3624880",
    "queue/report.json": "257fde65433dd18a19747a9ff014b40e5a906606640cd807bdb3ef5758984f9d",
    "stages/bundle-preparation-attempt-1.json": "4de075d83dd0c95ca0f09de6811e514dfa3c8a4c4c6859c8ad9c0b2a3aae8f2a",
    "stages/training-attempt-1.json": "9fcf1efd3d10e98e51cf56f22e00c91453eae03709dc43f6552e8c9a9e6096e4",
    "stages/serving-attempt-1.json": "4c33da68fcaaf5f70a288dbaeef1f2484f4b7dc3f3b2948722713f2ebd3074ff",
    "stages/queue-attempt-1.json": "60a67f255d43af9ee92c7542349647e459610b2502b52c61cccc710a3d0479cc",
}


def derive(root):
    data = {}
    for name, expected in PINS.items():
        raw = (Path(root)/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("fixed observation differs: " + name)
        data[name] = json.loads(raw)
    serving, training, queue, bundle = (data[name] for name in
        ("serving/report.json", "training/report.json", "queue/report.json", "bundle/bundle.json"))
    modes, scales = ("linear", "gated", "residual"), (64, 256, 1024)
    if (len(serving["conditions"]) != 27 or
            {(r["mode"], r["physical_cells"], r["batch_rows"]) for r in serving["conditions"]}
            != {(m, n, b) for m in modes for n in scales for b in (1, 16, 64)}
            or len(training["conditions"]) != 9 or
            {(r["mode"], r["physical_cells"]) for r in training["conditions"]}
            != {(m, n) for m in modes for n in scales}):
        raise ValueError("complete predeclared runtime conditions required")
    served = []
    for row in serving["conditions"]:
        if not all(row[k] for k in ("bitwise_physical_logical", "scalar_decisions_equal", "cached_equal")):
            raise ValueError("serving equality gate failed")
        if row["declared_tasks"] != 1 or row["logical_states"] != 9:
            raise ValueError("replicas cannot become independent tasks")
        actual = row["logical_accounting"]
        served.append({"mode": row["mode"], "physical_cells": row["physical_cells"],
            "batch_rows": row["batch_rows"], "logical_states": row["logical_states"], "task_count": 1,
            **{f"{kind}_{percentile}_ms": row[percentile+"_ns"][kind]/1e6
               for kind in ("physical", "logical") for percentile in ("p50", "p95")},
            "warm_p50_ratio": row["p50_ns"]["physical"]/row["p50_ns"]["logical"],
            "physical_setup_ms": row["setup"]["physical"]["wall_ns"]/1e6,
            "logical_setup_ms": row["setup"]["logical"]["wall_ns"]/1e6,
            "physical_parameter_bytes": row["physical_accounting"]["private_parameter_tensor_bytes"],
            "logical_parameter_bytes": actual["owned_parameter_tensor_bytes"],
            "logical_owned_tensor_bytes": actual["total_owned_tensor_bytes"],
            "calibration_serialized_bytes": actual["serialized_calibration_bytes"],
            "cache_tensor_bytes": actual["cache_tensor_bytes"], "mapping_tensor_bytes": actual["physical_mapping_tensor_bytes"],
            "max_scalar_logit_error": row["max_scalar_logit_error"],
            "max_scalar_probability_error": row["max_scalar_probability_error"],
            "physical_head_evaluations_per_call": row["physical_head_evaluations_per_call"],
            "logical_head_evaluations_per_call": row["all_head_evaluations_per_call"],
            "top3_head_evaluations": row["top3_head_evaluations"],
            "top3_served_predictions": row["top3_served_predictions"],
            "cache_hits": row["cache_hits"], "cache_misses": row["cache_misses"]})
    trained, initial_states, final_states = [], set(), set()
    for row in training["conditions"]:
        executions = row["executions"]
        if (executions["scalar"]["initial_parameter_digests"] != executions["batched"]["initial_parameter_digests"]
                or not row["checkpoint"]["recovery"]["all_cell_parameter_digests_verified"]):
            raise ValueError("matched initialization or complete checkpoint identity failed")
        initial_states.update(executions["batched"]["initial_parameter_digests"])
        final_states.update(executions["batched"]["trained_parameter_digests"])
        fit = {kind: execution["fit"]["wall_ns"]/1e9 for kind, execution in executions.items()}
        total = {kind: sum(execution[k]["wall_ns"] for k in ("setup", "fit", "snapshot_and_accounting"))/1e9
                 for kind, execution in executions.items()}
        accounting = executions["batched"]["accounting"]
        trained.append({"mode": row["mode"], "physical_cells": row["physical_cells"], "task_count": 1,
            "scalar_fit_s": fit["scalar"], "batched_fit_s": fit["batched"], "fit_ratio": fit["scalar"]/fit["batched"],
            "scalar_setup_fit_snapshot_s": total["scalar"], "batched_setup_fit_snapshot_s": total["batched"],
            "setup_fit_snapshot_ratio": total["scalar"]/total["batched"],
            "parameter_bytes": accounting["actual_parameter_bytes"], "optimizer_bytes": accounting["actual_moment_bytes"],
            "workspace_tensor_bound_bytes": accounting["transient_tensor_upper_bound_bytes"],
            "total_tensor_bound_bytes": accounting["total_tensor_upper_bound_bytes"],
            "max_parameter_error": row["maximum_absolute_parameter_difference"],
            "max_loss_errors": row["maximum_absolute_loss_difference"], "bitwise_equal": row["parameters_bitwise_equal"],
            "distinct_final_states": executions["batched"]["distinct_trained_private_states"],
            "cells_final_loss_above_initial": sum(a>b for a, b in zip(executions["batched"]["final_loss"],
                executions["batched"]["initial_loss"], strict=True)),
            "checkpoint_bytes": row["checkpoint"]["parameter_archive_bytes"],
            "checkpoint_manifest_sha256": row["checkpoint"]["manifest_sha256"],
            "parameter_states_verified": row["checkpoint"]["recovery"]["verified_parameter_states"]})
    activities = {}
    for name in ("bundle-preparation", "training", "serving", "queue"):
        outer = data[f"stages/{name}-attempt-1.json"]
        if outer["exit_code"] != 0:
            raise ValueError("main stage failed")
        activities[name] = {"wall_ns": outer["wall_ns"], "parent_cpu_ns": outer["parent_cpu_ns"],
                            "child_cpu_ns": outer["child_cpu_ns"]}
    return {"schema": "hepta.runtime-770-fixed-facts.v1", "source_pins": PINS,
        "derivation": "fixed observation arithmetic; no prediction, fit, quality scoring or resampling",
        "input": {"feature_identity": bundle["feature_identity"], "calibration_context_sha256": bundle["calibration_context_sha256"],
            "task_count": 1, "task_id": bundle["task_id"], "width": 770, "training_rows": 32,
            "training_groups": 32, "serving_rows": 64, "preserved_source_records": bundle["source_record_count"],
            "frozen_serving_heads": len(bundle["states"]), "new_encoder_calls": 0},
        "serving": {"conditions": served, "condition_count": 27, "repeats": 7,
            "process_lifetime_peak_rss_bytes": serving["process_lifetime_peak_rss_bytes"],
            "physical_logical_bitwise": True, "routing_quality_measured": False,
            "max_scalar_logit_error": max(r["max_scalar_logit_error"] for r in served),
            "max_scalar_probability_error": max(r["max_scalar_probability_error"] for r in served)},
        "training": {"conditions": trained, "condition_count": 9,
            "initial_distinct_digests_across_scales": len(initial_states), "final_distinct_digests_across_scales": len(final_states),
            "parameter_state_slots_across_conditions": sum(r["physical_cells"] for r in trained),
            "private_updates_both_methods": training["actual_total_private_optimizer_updates_both_methods"],
            "example_updates_both_methods": training["actual_total_example_updates_both_methods"],
            "final_parameter_archive_bytes": training["parameter_archives_total_bytes"],
            "shared_bank": training["feature_bank_construction"], "trainer_tensor_limit_bytes": 512*1024**2,
            "process_lifetime_peak_rss_bytes": training["process_lifetime_peak_rss_bytes"],
            "optimizer_moments_restored": False, "atol": 1e-10, "rtol": 1e-10},
        "queue": {"jobs": queue["training_jobs"], "private_updates": queue["actual_optimizer_updates"],
            "example_updates": queue["example_updates"], "concurrency": queue["concurrency"],
            "attempts": queue["queue"]["attempts_by_cell"],
            "real_job_recovered": queue["queue"]["real_job_recovery"]["same_job_reclaimed"],
            "old_token_rejected": queue["queue"]["real_job_recovery"]["old_token_rejected"],
            "generation_fenced": queue["lease_generation_control"]["old_generation_rejected"],
            "calibration_after_training": queue["calibration_after_training"], "memory": queue["memory"],
            "persisted_bytes_before_report": queue["persisted_file_bytes_before_report"],
            "resume_semantics": queue["resume_semantics"]},
        "measured_main_stages": activities,
        "measured_main_wall_ns": sum(a["wall_ns"] for a in activities.values()),
        "measured_main_cpu_ns": sum(a["parent_cpu_ns"]+a["child_cpu_ns"] for a in activities.values()),
        "main_cost_scope": "four complete outer process trees only; tests/publication/restore/packaging and editorial work separate",
        "scope": "one historical task; independent update states and repeated frozen serving states are separate axes",
        "quality_qualified": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = derive(args.phase_root)
    with Path(args.output).open("xb") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()+b"\n")
