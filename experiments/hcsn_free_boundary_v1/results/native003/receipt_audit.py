"""Read-only reaggregation of completed native003 and posthoc audit receipts.

No model/head inference, fitting, source edits, or new scientific runs. Only the
two REVIEW.json reports are written, with this audit script's own digest.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from collections import Counter

import numpy as np


ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "experiments/hcsn_free_boundary_v1"
MAIN = PACKAGE / "results/native003"
POST = PACKAGE / "results/native003_adversarial001"


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def same(a, b):
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)


def main():
    checks = []

    def check(name, value):
        checks.append({"check": name, "passed": bool(value)})

    summary = read(MAIN / "SUMMARY.json")
    frozen = read(MAIN / "FREEZE.json")
    original = read(PACKAGE / "FREEZE.json")
    for label, freeze in [("main", frozen), ("original", original)]:
        mismatch = [name for name, digest in freeze["files"].items()
                    if sha(ROOT / name) != digest]
        check(label + "_source_freeze_hashes", not mismatch)
    lock = read(MAIN / "TRAINING_LOCK.json")
    check("training_lock_file_hashes", all(sha(MAIN / name) == value
          for name, value in lock["files"].items()))
    identity = read(MAIN / "FRESH_INPUT_IDENTITY.json")
    check("fresh_identity_training_lock", identity["training_lock_sha256"] == sha(MAIN / "TRAINING_LOCK.json"))
    check("fresh_identity_protocol", identity["protocol_sha256"] == sha(PACKAGE / "NATIVE003_PROTOCOL.json"))
    manifest = read(PACKAGE / "data/native003/fresh_mnist.json")
    old = read(PACKAGE / "data/study001/mnist.json")
    fresh_ids = manifest["splits"]["test"]
    check("fresh128_unique", len(set(fresh_ids["episode_ids"])) == 128
          and len(set(fresh_ids["image_source_ids"])) == 128)
    disjoint = {}
    for split in ["train", "val", "test"]:
        disjoint[split] = {
            key: len(set(fresh_ids[key]) & set(old["splits"][split][key]))
            for key in ["episode_ids", "image_source_ids"]
        }
    check("fresh_ids_disjoint_all_original_splits", not any(
          n for row in disjoint.values() for n in row.values()))
    check("fresh_data_hash", sha(PACKAGE / "data/native003/fresh_mnist.npz") == manifest["sha256"]
          == identity["fresh_dataset_sha256"])
    check("fresh_manifest_hash", sha(PACKAGE / "data/native003/fresh_mnist.json") == identity["fresh_manifest_sha256"])
    check("fresh_transform_copied_from_original", manifest["transforms"] == old["transforms"]
          and manifest["new_statistics_fitted"] is False)
    trace_receipts = read(MAIN / "traces/TRACE_RECEIPTS.json")
    for split in ["train", "val"]:
        check(split + "_trace_hash", sha(MAIN / f"traces/{split}.npz") == trace_receipts[split]["trace_sha256"])
        with np.load(MAIN / f"traces/{split}.npz", allow_pickle=False) as a:
            check(split + "_correctness_matches_saved_predictions", np.array_equal(
                  a["correct"], a["predictions"] == a["labels"][:, None]))
    normalization = read(MAIN / "traces/NORMALIZATION.json")
    with np.load(MAIN / "traces/train.npz", allow_pickle=False) as a:
        obs = a["observed"]
        bank = np.concatenate([np.concatenate([obs, np.full((*obs.shape[:-1], 1), price,
                                     dtype=np.float32)], axis=-1)
                               for price in normalization["public_prices"]]).reshape(-1, 6).astype(np.float64)
        check("normalization_mean_train_only_recomputed", np.array_equal(
              bank.mean(0).astype(np.float32), np.array(normalization["mean"], dtype=np.float32)))
        check("normalization_std_train_only_recomputed", np.array_equal(
              np.maximum(bank.std(0), 1e-4).astype(np.float32), np.array(normalization["std"], dtype=np.float32)))

    totals = Counter()
    native_cpu = 0.0
    all_results = sorted((MAIN / "evaluation").rglob("RESULT.json")) + sorted((MAIN / "recovery").rglob("RESULT.json"))
    for path in all_results:
        row = read(path)
        n = len(row["events"])
        totals["native_episode_records_including_recovery"] += 1
        totals["actual_neural_steps_including_recovery"] += row["actual_model_steps"]
        check(str(path.relative_to(MAIN)) + ":steps", n == row["actual_model_steps"] == row["actual_head_steps"] == row["actual_reads"])
        check(str(path.relative_to(MAIN)) + ":read_utility", same(row["utility"], row["correct"] - row["read_price"] * row["actual_reads"]))
        for event in row["events"]:
            native = event["native"]
            totals["native_owner_ticks"] += 1
            totals["q24_zero_ties"] += event["score_q24"] == 0
            totals["float_q24_disagreements"] += event["float_action"] != event["q24_action"]
            check("native_action:" + str(path.relative_to(MAIN)) + ":" + str(event["prefix"]),
                  native["effective_action"] == event["q24_action"] == native["readout"]["action"]
                  and (event["score_q24"] > 0) == (event["q24_action"] == "keep")
                  and native["owner_authority"] == "DENY_ALL"
                  and sum(value != 0 for value in native["activation_q24"]) <= 1)
        if row["terminal_probe"] is not None:
            probe = row["terminal_probe"]
            totals["deliberate_terminal_rejection_probes"] += 1
            check("terminal_probe:" + str(path.relative_to(MAIN)), probe["passed"]
                  and probe["before"] == probe["after"]
                  and probe["rejection"]["error"] == "Terminal episode; no native tick executed")
        for proc in row["native_process_costs"]:
            totals["native_processes"] += 1
            totals["native_process_nonzero_exit"] += proc["exit_code"] != 0
            totals["native_reported_errors"] += proc["counters"]["native_errors"]
            totals["total_native_kernel_calls"] += proc["counters"]["total_native_kernel_calls"]
            totals["total_native_ndu_calls"] += proc["counters"]["total_native_ndu_calls"]
            native_cpu += proc["child_cpu_seconds"]
    check("all_native_errors_are_terminal_probes", totals["native_reported_errors"] == totals["deliberate_terminal_rejection_probes"])
    check("all_native_processes_exit_zero", totals["native_process_nonzero_exit"] == 0)
    check("zero_float_q24_action_disagreements", totals["float_q24_disagreements"] == 0)
    check("no_zero_q24_ties_in_main", totals["q24_zero_ties"] == 0)
    reference_paths = list((MAIN / "evaluation").glob("price_*/references/*/fresh*.json"))
    for path in reference_paths:
        row = read(path)
        check("reference_actual_step_ledger:" + str(path.relative_to(MAIN)),
              len(row["steps"]) == row["actual_model_steps"] == row["actual_reads"])
        totals["actual_reference_steps"] += row["actual_model_steps"]
    totals["reference_episode_records"] = len(reference_paths)

    price_effect = Counter()
    example = None
    for i in range(128):
        low = read(MAIN / f"evaluation/price_0p005/value_maxout/fresh{i:05d}/RESULT.json")
        high = read(MAIN / f"evaluation/price_0p050/value_maxout/fresh{i:05d}/RESULT.json")
        a, b = low["events"][0], high["events"][0]
        equal = (a["features"][:5] == b["features"][:5]
                 and a["prediction"] == b["prediction"]
                 and a["native"]["checkpoint_before"] == b["native"]["checkpoint_before"]
                 and a["native"]["profile_sha256"] == b["native"]["profile_sha256"])
        check("first_step_matched_nonprice_state:" + str(i), equal)
        price_effect["matched_first_step_pairs"] += equal
        price_effect["changed_actual_native_action"] += a["native"]["effective_action"] != b["native"]["effective_action"]
        price_effect["changed_actual_model_step_count"] += low["actual_model_steps"] != high["actual_model_steps"]
        if example is None:
            example = {"episode": low["episode"], "same_nonprice_features": a["features"][:5],
                       "native_profile_sha256": a["native"]["profile_sha256"],
                       "checkpoint_before": a["native"]["checkpoint_before"],
                       "low_price_score": a["score"], "high_price_score": b["score"],
                       "low_price_action": a["native"]["effective_action"],
                       "high_price_action": b["native"]["effective_action"],
                       "low_price_reads": low["actual_reads"], "high_price_reads": high["actual_reads"]}

    costs = summary["costs"]
    train_exec = read(MAIN / "TRAINING_EXECUTION.json")
    eval_exec = read(MAIN / "EVALUATION_EXECUTION.json")
    check("worker_exit_zero", train_exec["returncode"] == eval_exec["returncode"] == 0)
    check("native_child_nested_cost_reaggregated", same(native_cpu, costs["native_child_cpu_nested_breakdown_seconds"]))
    parent_cpu = sum(result["parent_cpu_seconds"] for cohort in summary["cohorts"] for result in cohort["results"].values())
    parent_cpu += sum(result["parent_cpu_seconds"] for result in summary["recovery"].values())
    check("shared_eval_residual_no_double_count", same(eval_exec["child_cpu_seconds"] - native_cpu - parent_cpu,
          costs["shared_evaluator_cpu_seconds"]))
    check("incremental_cpu_no_descendant_double_count", same(
          costs["incremental_native003_cpu_seconds"], train_exec["child_cpu_seconds"] + eval_exec["child_cpu_seconds"]
          + costs["data_generation_complete_child_cpu_seconds"] + costs["orchestrator_self_cpu_seconds_through_accounting_cutoff"]))
    grid = read(MAIN / "COST_SCENARIOS.json")["rows"]
    for i, row in enumerate(grid):
        cpu = row["measured_inference_cpu_per_episode"] + sum(row[key] for key in (
            "backbone_training_cpu_amortized", "head_full_search_cpu_amortized",
            "recovery_verification_cpu_amortized", "shared_setup_cpu_amortized",
            "traces_and_shared_training_cpu_amortized"))
        check("cost_scenario_utility:" + str(i), same(row["scenario_utility"],
              row["accuracy"] - row["read_price"] * row["mean_reads"] - row["utility_units_per_cpu_second"] * cpu))
    summary_hash = sha(MAIN / "SUMMARY.json")
    result = {"schema": "native003-readonly-receipt-audit.v1", "method": "Rehash frozen inputs and saved selection artifacts; recompute train-only normalization from saved TRAIN traces; compare source/episode IDs; read all actual native/reference result and wait4 receipts; reaggregate guards, action parity, terminal probes, utility and CPU grids. No inference or fitting.",
              "audit_script_sha256": sha(__file__), "main_summary_sha256": summary_hash,
              "original_freeze_files_checked": len(original["files"]), "native003_freeze_files_checked": len(frozen["files"]),
              "training_lock_files_checked": len(lock["files"]), "fresh_overlap_counts": disjoint,
              "counts": dict(totals), "native_child_cpu_reaggregated_seconds": native_cpu,
              "first_step_public_price_intervention": {"counts": dict(price_effect), "example": example,
                  "scope": "Existing matched initial-state receipts only. This proves actual price-responsive execution for this trained head; it does not isolate each latent input channel or establish utility superiority."},
              "cost_scenario_rows_checked": len(grid),
              "recovery": {name: {"actual_recovery_count": row["recovery_count"],
                   "trajectory_matches": row["matches_uninterrupted_including_context_digests"],
                   "new_python_interpreter": row["new_python_interpreter"],
                   "claim": "exercised same-interpreter object/native-process restart" if row["recovery_count"] else "not exercised: first-step STOP"}
                   for name, row in summary["recovery"].items()},
              "checks_performed": len(checks), "failed_checks": [c for c in checks if not c["passed"]]}
    result["status"] = "passed" if not result["failed_checks"] else "failed"
    (MAIN / "REVIEW.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    checks = []
    post_summary = read(POST / "SUMMARY.json")
    post_lock = read(POST / "SELECTION_LOCK.json")
    selection = read(POST / "SELECTION.json")
    fixed = read(POST / "FIXED1_SUMMARY.json")
    post_exec = read(POST / "EXECUTION.json")
    check("old_main_summary_unchanged", summary_hash == post_lock["main_summary_sha256"] == post_summary["main_summary_sha256"])
    check("posthoc_code_hash", post_lock["audit_source_sha256"] == sha(PACKAGE / "native003_adversarial.py") == sha(POST / "SOURCE_SNAPSHOT.py"))
    check("posthoc_selection_lock_hash", post_lock["selection_sha256"] == sha(POST / "SELECTION.json"))
    check("source_val_trace_hash", selection["source_val_trace_sha256"] == sha(MAIN / "traces/val.npz"))
    with np.load(MAIN / "traces/val.npz", allow_pickle=False) as a:
        correctness = a["correct"].astype(np.float64)
        for price_text, chosen in selection["choices"].items():
            price = float(price_text)
            candidates = [(float((correctness[:, k - 1] - price * k).mean()), k)
                          for k in selection["candidate_prefixes"]]
            independently_chosen = min(candidates, key=lambda pair: (-pair[0], pair[1]))[1]
            check("val_only_prefix_recomputed:" + price_text, chosen == independently_chosen)
    check("fixed1_complete_worker_exited_zero", post_exec["returncode"] == 0)
    check("fixed1_actual128steps", fixed["actual_model_step_calls"] == len(fixed["rows"]) == 128
          and all(row["actual_model_steps"] == row["actual_reads"] == 1 and row["head_steps"] == 0
                  and row["native_owner_used"] is False for row in fixed["rows"]))
    equivalents = 0
    for cohort in summary["cohorts"]:
        for a, b in zip(cohort["results"]["ordinary_mlp"]["ledger"], fixed["rows"]):
            equal = a["episode"] == b["episode"] and a["prediction"] == b["prediction"] and a["correct"] == b["correct"] and a["actual_reads"] == b["actual_reads"]
            check("fixed1_actual_prediction_equivalence:" + str(cohort["read_price"]) + ":" + a["episode"], equal)
            equivalents += equal
    for row in post_summary["scenario_rows"]:
        check("posthoc_cpu_scenario:" + str((row["read_price"], row["scenario_episodes"], row["utility_units_per_cpu_second"])),
              same(row["ordinary_scenario_utility"], row["ordinary_read_only_utility"] - row["utility_units_per_cpu_second"] * row["ordinary_cpu_charge_per_episode"]))
    check("posthoc_incremental_cpu", same(post_summary["costs"]["incremental_audit_cpu_seconds"],
          post_exec["complete_child_cpu_seconds"] + post_summary["costs"]["audit_orchestrator_cumulative_self_cpu_seconds"]))
    check("original_primary_review_passed", result["status"] == "passed")
    post_result = {"schema": "native003-posthoc-readonly-receipt-audit.v1", "audit_script_sha256": sha(__file__),
                   "method": "Read-only VAL selection reproduction; new fixed1 execution receipt inspection; pairwise comparison with main STOP1 predictions; main/source/selection hash locks; complete wait4 CPU arithmetic. No model inference or fitting.",
                   "summary_sha256": sha(POST / "SUMMARY.json"), "main_summary_unchanged_sha256": summary_hash,
                   "classification": post_summary["classification"], "fixed1_equivalent_prediction_cases": equivalents,
                   "validation_selected_prefixes": selection["choices"], "actual_new_fixed1_steps": fixed["actual_model_step_calls"],
                   "scenario_rows_checked": len(post_summary["scenario_rows"]),
                   "value_strict_wins_over_ordinary_scenarios": sum(row["value_minus_ordinary_scenario_utility"] > 1e-12 for row in post_summary["scenario_rows"]),
                   "value_minus_ordinary_macro_utility": post_summary["value_minus_ordinary_macro_utility"],
                   "checks_performed": len(checks), "failed_checks": [c for c in checks if not c["passed"]]}
    post_result["status"] = "passed" if not post_result["failed_checks"] else "failed"
    (POST / "REVIEW.json").write_text(json.dumps(post_result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"native003": result, "adversarial": post_result}, indent=2))
    if result["failed_checks"] or post_result["failed_checks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
