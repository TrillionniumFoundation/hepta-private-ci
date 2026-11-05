#!/usr/bin/env python3
"""Read-only, independent arithmetic audit of already exposed diagnostic records.

No world generation, model/teacher execution, fitting, parameter change, gate
change, or new scientific confirmation. Stored hidden vectors are inputs to a
linear accounting check only; their neural provenance is not reexecuted here.
"""
import argparse
import datetime
import gzip
import hashlib
import json
import math
import time
from pathlib import Path


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def identity(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def close(a, b, tol=2e-13):
    assert math.isfinite(a) and math.isfinite(b) and abs(a-b) <= tol, (a, b)


def main(base):
    cpu_start, wall_start = time.process_time(), time.monotonic()
    post = base / "posthoc"
    protocol = read(post / "PROTOCOL_FROZEN.json")
    result = read(post / "execution_r1/run/RESULTS.json")
    main_protocol = read(base / "PROTOCOL_FROZEN.json")
    for files in (protocol["input_files"], protocol["source_files"], main_protocol["source_files"]):
        for name, expected in files.items():
            assert identity(base/name) == expected, name
    assert identity(post / "PROTOCOL_FROZEN.json")["sha256"] == result["protocol_sha256"]
    assert identity(base / "PROTOCOL_FROZEN.json")["sha256"] == result["main_protocol_sha256"]
    assert protocol["confirmatory"] is False and result["qualification_unchanged_false"] is True
    models = {a: read(base / f"execution_r1/run/models/fit_23_{a}.json.gz") for a in ("C", "E")}
    delta = [[models["E"]["network"]["w2"][a][j] - models["C"]["network"]["w2"][a][j] for j in range(48)] + [models["E"]["network"]["b2"][a]-models["C"]["network"]["b2"][a]] for a in range(3)]
    def coefficients(action):
        return delta[action-1] if action in (1, 2, 3) else [0.] * 49
    grouped = {s: [] for s in ("validation", "test")}
    frozen = {s: read(base / f"execution_r1/run/{s}_23_ood_RESULTS.json.gz") for s in grouped}
    checked_states, max_linear, max_global = 0, 0., 0.
    category_names = ("own_target_violation", "own_positive_evaluator_negative", "other")
    for item in result["inventory"]:
        path = post / "execution_r1/run" / item["path"]
        assert identity(path)["sha256"] == item["sha256"]
        data = read(path)
        original = frozen[item["split"]]["records"][item["index"]]
        assert data["world_id"] == item["world_id"] == original["world_id"]
        sums = {k: {"state_count": 0, "evaluator_E_expected_visit_count": 0., "evaluator_advantage_contribution": 0.} for k in category_names}
        global_sums = {"own": 0., "truth": 0.}
        first_sum = 0.
        for state in data["changed_state_records"]:
            checked_states += 1
            assert hashlib.sha256(json.dumps(state["state"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest() == state["state_sha256"]
            a, c = state["E_action"], state["C_action"]
            assert a != c
            for arm in ("C", "E"):
                scores = state[arm+"_head_scores"]
                assert max((i for i in range(6) if state["legal"][i]), key=lambda i: scores[i]) == state[arm+"_action"]
            own_adv = state["own_Q_following_C"][a] - state["own_Q_following_C"][c]
            truth_adv = state["evaluator_Q_following_C"][a] - state["evaluator_Q_following_C"][c]
            close(own_adv, state["own_one_step_C_advantage_of_E_action"])
            close(truth_adv, state["evaluator_one_step_C_advantage_of_E_action"])
            close(own_adv, state["anchored_own_target"][a] - state["anchored_own_target"][c])
            category = "own_target_violation" if own_adv < -1e-12 else "own_positive_evaluator_negative" if own_adv > 1e-12 and truth_adv < -1e-12 else "other"
            assert category == state["exclusive_diagnostic_category"]
            assert state["violates_own_incumbent_policy_improvement"] == (own_adv < -1e-12)
            assert state["own_positive_preference_reversed_by_evaluator"] == (own_adv > 1e-12 and truth_adv < -1e-12)
            own_reach, truth_reach = state["own_E_unnormalized_reach"], state["evaluator_E_unnormalized_reach"]
            assert own_reach >= 0 and truth_reach >= 0
            sums[category]["state_count"] += 1
            sums[category]["evaluator_E_expected_visit_count"] += truth_reach
            sums[category]["evaluator_advantage_contribution"] += truth_reach*truth_adv
            global_sums["own"] += own_reach*own_adv
            global_sums["truth"] += truth_reach*truth_adv
            first_sum += state["first_common_prefix_evaluator_reach"]*state["evaluator_full_suffix_E_minus_C"]
            coef = [x-y for x, y in zip(coefficients(a), coefficients(c))]
            terms = [x*y for x, y in zip(coef, state["hidden_with_bias"])]
            for x, y in zip(terms, state["linear_head_margin_contributions"]):
                close(x, y)
            expected_shift = state["E_head_scores"][a]-state["E_head_scores"][c] - (state["C_head_scores"][a]-state["C_head_scores"][c])
            close(expected_shift, state["actual_head_margin_shift"])
            close(math.fsum(terms), expected_shift)
            max_linear = max(max_linear, abs(math.fsum(terms)-expected_shift))
            top = sorted(range(49), key=lambda i: -abs(terms[i]))[:len(state["top_absolute_linear_coordinates"])]
            assert top == [x["index"] for x in state["top_absolute_linear_coordinates"]]
            for record in state["top_absolute_linear_coordinates"]:
                index = record["index"]
                close(record["changed_margin_coefficient"], coef[index])
                close(record["hidden_value"], state["hidden_with_bias"][index])
                close(record["contribution"], terms[index])
        for category in category_names:
            for metric in sums[category]:
                close(sums[category][metric], data["exclusive_categories"][category][metric])
        for law in ("own", "truth"):
            change = data["initial_values"][law]["E"]-data["initial_values"][law]["C"]
            perf = data["performance_difference"][law]
            close(change, perf["initial_E_minus_C"])
            close(change, global_sums[law])
            close(global_sums[law], perf["sum_E_reach_times_C_advantage"])
            close(perf["terminal_mass"], 1.)
            max_global = max(max_global, abs(change-global_sums[law]))
        close(first_sum, data["first_divergence_partition"]["full_suffix_weighted_sum"])
        close(first_sum, data["performance_difference"]["truth"]["initial_E_minus_C"])
        for arm in ("C", "E"):
            close(data["initial_values"]["truth"][arm], original["arms"][arm]["utility"], tol=0.)
        grouped[item["split"]].append(data)
    summary = {}
    for split, rows in grouped.items():
        expected = result["summary"][split]
        assert len(rows) == expected["world_count"] == (16 if split == "validation" else 32)
        assert sum(len(r["changed_state_records"]) for r in rows) == expected["changed_state_records"]
        for law, key in (("own", "mean_own_E_minus_C"), ("truth", "mean_evaluator_E_minus_C")):
            close(sum(r["performance_difference"][law]["initial_E_minus_C"] for r in rows)/len(rows), expected[key])
        for category in category_names:
            for metric in expected["categories"][category]:
                close(sum(r["exclusive_categories"][category][metric] for r in rows)/len(rows), expected["categories"][category][metric])
        close(sum(expected["categories"][k]["evaluator_advantage_contribution"] for k in category_names), expected["mean_evaluator_E_minus_C"])
        summary[split] = expected
    frozen_deltas = [r["arms"]["E"]["utility"]-r["arms"]["C"]["utility"] for r in frozen["test"]["records"]]
    assert min(range(32), key=lambda i: (frozen_deltas[i], i)) == result["example"]["test_index"] == 6
    close(frozen_deltas[6], result["example"]["evaluator_E_minus_C"], tol=0.)
    phases = ("preparation", "semantic_checks", "protocol_freeze", "execution_r1", "independent_verification", "posthoc/freeze_receipt", "posthoc/execution_r1", "reporting_summary")
    receipts = {phase: read(base/phase/"PROCESS_RECEIPT.json") for phase in phases}
    assert all(r["exit_code"] == 0 and not r["controller_timeout"] for r in receipts.values())
    assert datetime.datetime.fromisoformat(protocol["frozen_utc"]) < datetime.datetime.fromisoformat(receipts["posthoc/execution_r1"]["started_utc"])
    main_result = read(base / "execution_r1/run/RESULTS.json")
    assert main_result["weight_efficacy_qualified"] is False
    return {"status": "PURE_POSTHOC_RECORD_AUDIT_PASS_NO_NEW_CONFIRMATION", "protocol_sha256": result["protocol_sha256"], "results_sha256": identity(post/"execution_r1/run/RESULTS.json")["sha256"], "complete_worlds": len(result["inventory"]), "changed_state_records": checked_states, "linear_contributions_from_stored_weights_and_hidden_checked": True, "performance_and_first_prefix_identities_recomputed_from_records": True, "maximum_reviewer_linear_residual": max_linear, "maximum_reviewer_global_residual": max_global, "summary": summary, "example_rule_verified": True, "example": result["example"], "whole_process_phase_CPU_seconds": {k:v["child_total_cpu_seconds"] for k,v in receipts.items()}, "sum_measured_eight_child_phases_CPU_seconds": sum(r["child_total_cpu_seconds"] for r in receipts.values()), "main_weight_efficacy_qualified": False, "new_model_or_teacher_execution": False, "reviewer_self_cpu_seconds": time.process_time()-cpu_start, "reviewer_wall_seconds": time.monotonic()-wall_start}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = main(args.base)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps({k: result[k] for k in ("status", "complete_worlds", "changed_state_records", "sum_measured_eight_child_phases_CPU_seconds")}))
