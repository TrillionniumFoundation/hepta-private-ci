"""Descriptive, read-only accounting over frozen original42/C1 JSON evidence."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import time


EXPECTED = {
    "curves": "9e2ff18ec234185ac68c581c775e8ac93c15d62a68605c4897c0fc1098da2d94",
    "baseline_v1": "368494d90c42339c5b8d8e7afbed7592c4cb2ef52d52a4611a3e89d7fea59052",
    "baseline_v2": "c90afba67ce09871e49c2a117cec3403a2b7fdec6528e600402557d6a7863094",
    "hcsn_summary": "58aa588c9c1323000316624e923644be90a264522dcc998c780c25da0f4b64af",
    "core_table": "ebf943e36a3da47352a70d46d41e9ad73d5e97d7778908fd4933bda699455dfe",
}
ARMS = ["gru", "cfc", "snn_plif", "event_time_lif", "ssm_s4d", "attention", "hcsn"]
SEEDS = [101, 211, 307]
LRS = [0.001, 0.003]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    raw = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def close(left, right, label, tolerance=1e-12):
    require(math.isfinite(left) and math.isfinite(right) and abs(left - right) <= tolerance,
            f"{label}: {left!r} != {right!r}")


def matrix_metrics(matrix):
    require(len(matrix) == 11 and all(len(row) == 11 for row in matrix), "CM shape")
    require(all(type(x) is int and x >= 0 for row in matrix for x in row), "CM counts")
    rows = [sum(row) for row in matrix]
    columns = [sum(matrix[i][j] for i in range(11)) for j in range(11)]
    total = sum(rows)
    require(total > 0, "empty CM")
    f1 = [2 * matrix[i][i] / (rows[i] + columns[i]) if rows[i] + columns[i] else 0.0
          for i in range(11)]
    present = [i for i in range(11) if rows[i]]
    return rows, {
        "accuracy": sum(matrix[i][i] for i in range(11)) / total,
        "macro_f1_11_classes": statistics.mean(f1),
        "macro_f1_present_classes": statistics.mean(f1[i] for i in present),
        "balanced_accuracy_present_classes": statistics.mean(matrix[i][i] / rows[i] for i in present),
    }


def best_point(points, budget=None, complete_only=False):
    eligible = [p for p in points if (budget is None or p["wall_seconds"] <= budget)
                and (not complete_only or p["kind"] == "complete_epoch")]
    # Input order is strictly increasing in wall time. max retains the first tie.
    return max(eligible, key=lambda p: p["quality"], default=None)


def first_crossing(points, target):
    return next((p for p in points if p["kind"] == "complete_epoch" and p["quality"] >= target), None)


def select_lr(candidates):
    eligible = [row for row in candidates if row["three_seed_mean"] is not None]
    return min(eligible, key=lambda row: (-row["three_seed_mean"], row["learning_rate"]), default=None)


def validate_inputs(data, baseline1, baseline2, hcsn, core_table):
    require(len(data["fits"]) == 49 and len(data["observations"]) == 2969, "input roster counts")
    require(data["confirmation_access"] is False and data["energy_joules"] is None, "scope")
    require(core_table == baseline2["core_fixed_LR_table"], "CORE_TABLE differs from v2")
    bindings = {("original", x["name"]): x["report_sha256"] for x in baseline1["original_baseline_records"]}
    bindings.update({("C1", x["name"]): x["child_report_sha256"] for x in baseline2["C1_records"]})
    bindings.update({("original", x["name"]): x["result_sha256"] for x in hcsn["rows"]})
    fits = {(f["phase"], f["name"]): f for f in data["fits"]}
    require(len(fits) == len(bindings) == 49 and set(fits) == set(bindings), "49 report roster binding")
    originals = {name: f for (phase, name), f in fits.items() if phase == "original"}
    expected_roster = {(a, s, lr) for a in ARMS for s in SEEDS for lr in LRS}
    require({(f["arm"], f["seed"], f["plan"]["learning_rate"]) for f in originals.values()} == expected_roster,
            "original seven-core/two-LR/three-seed roster")
    for key, f in fits.items():
        require(f["report_sha256"] == bindings[key] == f["outer"]["result_sha256"], f"report SHA {key}")
        require(f["source_unchanged"] is True and f["common_weights_unchanged"] is True, f"source gate {key}")
        require(f["actual_original_hard_wall_seconds"] >= 1800, f"actual resource grant {key}")
        if f["phase"] == "C1":
            parent = originals[f["name"]]
            require(f["parent_report_sha256"] == parent["report_sha256"], f"parent SHA {key}")
            close(f["outer"]["parent_outer_wall_seconds"], parent["outer"]["whole_process_wall_seconds"], "parent wall")
            require(f["plan"]["parent_plan"] == parent["plan"], "C1 inherited plan")
    by_phase = {key: [] for key in fits}
    supports = None
    errors = {k: 0.0 for k in ["accuracy", "macro_f1_11_classes", "macro_f1_present_classes", "balanced_accuracy_present_classes"]}
    for o in data["observations"]:
        key = (o["phase"], o["name"])
        f = fits[key]
        require(o["report_sha256"] == f["report_sha256"] and o["report_bytes"] == f["report_bytes"], "observation source")
        require((o["arm"], o["seed"]) == (f["arm"], f["seed"]), "observation identity")
        m = o["development"]
        rows, computed = matrix_metrics(m["confusion_matrix"])
        require(sum(rows) == m["events"] == 31952, "D event count")
        if supports is None:
            supports = rows
        require(rows == supports, "D class support changed")
        for metric, value in computed.items():
            close(value, m[metric], f"CM {key} epoch {o['epoch']} {metric}")
            errors[metric] = max(errors[metric], abs(value - m[metric]))
        by_phase[key].append(o)
    points = {}
    c1_intervals = []
    for key, observations in by_phase.items():
        f = fits[key]
        parent = originals[f["name"]]
        parent_wall = parent["outer"]["whole_process_wall_seconds"]
        outer_wall = f["outer"]["whole_process_wall_seconds"]
        previous_wall = -1.0
        previous_cpu = -1.0
        result = []
        for o in observations:
            if f["phase"] == "original":
                wall = o["process_wall_seconds"]
                cpu = o["process_cpu_seconds"]
                upper = cpu
                require(0 <= wall <= outer_wall, "original clock beyond outer receipt")
            else:
                wall = o["cumulative_process_wall_seconds"]
                late = wall - parent_wall
                early = o["phase_process_wall_seconds"]
                require(0 <= early <= late <= outer_wall, "C1 original clock interval")
                cpu = o["cumulative_cpu_lower_bound_seconds"]
                upper = o["cumulative_cpu_upper_bound_seconds"]
                require(upper is None and o["cumulative_full_process_cpu_seconds"] is None, "C1 invented exact CPU")
                close(cpu, f["parent_cpu_lower_bound_seconds"] + o["phase_full_process_cpu_seconds"], "C1 CPU lower bound")
                c1_intervals.append({"name": f["name"], "epoch": o["epoch"], "early": early, "late": late, "outer": outer_wall})
            require(math.isfinite(wall) and wall > previous_wall, "nonmonotone wall clock")
            previous_wall = wall
            if cpu is not None:
                require(math.isfinite(cpu) and cpu >= previous_cpu >= -1, "nonmonotone CPU prefix")
                previous_cpu = cpu
            result.append({"phase": f["phase"], "epoch": o["epoch"], "kind": o["kind"],
                           "wall_seconds": wall, "CPU_lower_seconds": cpu, "CPU_upper_seconds": upper,
                           "quality": o["development"]["macro_f1_11_classes"]})
        complete = [o["epoch"] for o in observations if o["kind"] == "complete_epoch"]
        first_epoch = 1 if key[0] == "original" else len([o for o in by_phase[("original", key[1])]
                                                         if o["kind"] == "complete_epoch"]) + 1
        require(complete == list(range(first_epoch, first_epoch + len(complete))), "epoch continuity")
        require(sum(o["kind"] == "development_before" for o in observations) == (key[0] == "original"), "before evaluation count")
        points[key] = result
    require(len(c1_intervals) == 351, "C1 epoch count")
    return fits, points, {"report_SHA_bindings": 49, "confusion_matrices": 2969, "complete_epoch_evaluations": 2927,
                          "before_evaluations": 42, "D_class_counts": supports, "CM_metric_max_absolute_errors": errors,
                          "C1_original_clock_intervals": 351, "C1_max_sample_gap_seconds": max(x["late"] - x["early"] for x in c1_intervals)}


def build_view(fits, points, include_c1, cuts, target):
    chains = []
    for (phase, name), original in fits.items():
        if phase != "original":
            continue
        child = fits.get(("C1", name)) if include_c1 else None
        chain_points = points[("original", name)] + (points[("C1", name)] if child else [])
        require(all(a["wall_seconds"] < b["wall_seconds"] for a, b in zip(chain_points, chain_points[1:])), "chain clocks")
        selected_fit = child or original
        best = best_point(chain_points, complete_only=True)
        require(best is not None and best["epoch"] == selected_fit["best_epoch"], f"strict best epoch {name}")
        if selected_fit["selected_development"] is not None:
            close(best["quality"], selected_fit["selected_development"]["macro_f1_11_classes"], f"best metric {name}")
        full_wall = original["outer"]["whole_process_wall_seconds"] + (child["outer"]["whole_process_wall_seconds"] if child else 0)
        chains.append({"name": name, "arm": original["arm"], "seed": original["seed"],
                       "learning_rate": original["plan"]["learning_rate"], "has_C1": child is not None,
                       "diagnostic_passed": original["diagnostic_passed"],
                       "final_training_adequacy": selected_fit["training_adequacy_established"],
                       "final_stop_reason": selected_fit["stop_reason"], "full_chain_outer_wall_seconds": full_wall,
                       "max_attempt_RSS_bytes": max(original["peak_rss_bytes"], child["peak_rss_bytes"] if child else 0),
                       "points": chain_points, "best_complete_epoch": best,
                       "first_observed_target_crossing": first_crossing(chain_points, target)})
    tables = {}
    for budget in [*cuts, None]:
        rows = []
        for arm in ARMS:
            arm_chains = [c for c in chains if c["arm"] == arm]
            candidates = []
            for lr in LRS:
                members = []
                for seed in SEEDS:
                    c = next(c for c in arm_chains if c["learning_rate"] == lr and c["seed"] == seed)
                    p = best_point(c["points"], budget, complete_only=budget is None)
                    members.append({"name": c["name"], "seed": seed, "observation": p,
                                    "diagnostic_passed": c["diagnostic_passed"],
                                    "final_training_adequacy": c["final_training_adequacy"],
                                    "charged_wall_seconds": c["full_chain_outer_wall_seconds"] if budget is None else min(c["full_chain_outer_wall_seconds"], budget)})
                qs = [m["observation"]["quality"] for m in members if m["observation"] is not None]
                candidates.append({"learning_rate": lr, "observed_seed_count": len(qs),
                                   "three_seed_mean": statistics.mean(qs) if len(qs) == 3 else None,
                                   "sample_standard_deviation": statistics.stdev(qs) if len(qs) == 3 else None,
                                   "members": members})
            selected = select_lr(candidates)
            row = {"arm": arm, "budget_seconds": budget, "candidates": candidates,
                   "selected_common_learning_rate": selected["learning_rate"] if selected else None,
                   "selected_three_seed_mean": selected["three_seed_mean"] if selected else None,
                   "selected_sample_standard_deviation": selected["sample_standard_deviation"] if selected else None,
                   "all_six_charged_wall_sum_seconds": sum(m["charged_wall_seconds"] for lr in candidates for m in lr["members"]),
                   "all_six_complete_attempt_max_RSS_bytes": max(c["max_attempt_RSS_bytes"] for c in arm_chains),
                   "all_six_final_adequate_count": sum(c["final_training_adequacy"] for c in arm_chains),
                   "all_six_diagnostic_failed_names": [c["name"] for c in arm_chains if not c["diagnostic_passed"]]}
            if budget is None and selected:
                chosen = [c for c in arm_chains if c["learning_rate"] == selected["learning_rate"]]
                crosses = [c["first_observed_target_crossing"] for c in chosen]
                row["selected_adequate_count"] = sum(c["final_training_adequacy"] for c in chosen)
                row["target_crossings"] = [{"name": c["name"], "crossing": c["first_observed_target_crossing"],
                                            "right_censor_outer_wall_seconds": c["full_chain_outer_wall_seconds"]
                                            if c["first_observed_target_crossing"] is None else None} for c in chosen]
                row["median_first_observed_target_seconds_if_all_cross"] = statistics.median(p["wall_seconds"] for p in crosses) if all(crosses) else None
            rows.append(row)
        tables["final" if budget is None else str(budget)] = rows
    return {"tables": tables, "chains": [{k: v for k, v in c.items() if k != "points"} for c in chains]}


def crosscheck_final(result, baseline2, hcsn):
    final = {r["arm"]: r for r in result["views"]["original42_plus_separate_C1"]["tables"]["final"]}
    old_clock_differences = []
    for ref in baseline2["core_fixed_LR_table"]:
        row = final[ref["arm"]]
        require(row["selected_common_learning_rate"] == ref["common_learning_rate"], "baseline selected LR")
        close(row["selected_three_seed_mean"], ref["D_three_seed_mean"]["macro_f1_11_classes"], "baseline mean")
        close(row["selected_sample_standard_deviation"], ref["D_macro_f1_sample_standard_deviation"], "baseline SD")
        close(row["all_six_charged_wall_sum_seconds"], ref["all_six_original_plus_C1_process_wall_sum_seconds"], "baseline cost", 1e-8)
        require(row["selected_adequate_count"] == ref["selected_LR_adequate_chains"], "baseline adequacy")
        for crossing in row["target_crossings"]:
            old = next(x for x in ref["individual_seeds"] if x["name"] == crossing["name"])["first_observed_0p30_active_wall_seconds"]
            new = crossing["crossing"]["wall_seconds"] if crossing["crossing"] else None
            require((old is None) == (new is None), "old target censoring differs")
            old_clock_differences.append({"name": crossing["name"], "old_table_seconds": old,
                                          "uniform_epoch_seconds": new,
                                          "old_minus_epoch_seconds": old - new if old is not None else None})
    h = final["hcsn"]
    for candidate in h["candidates"]:
        ref = next(x for x in hcsn["by_learning_rate"] if x["learning_rate"] == candidate["learning_rate"])
        close(candidate["three_seed_mean"], ref["three_seed_mean_best_observed_D_macro_f1"], "HCSN mean")
        close(candidate["sample_standard_deviation"], ref["sample_standard_deviation"], "HCSN SD")
    close(h["all_six_charged_wall_sum_seconds"], hcsn["hcsn_sum_outer_wall_seconds"], "HCSN full cost", 1e-8)
    require(h["all_six_final_adequate_count"] == 0, "HCSN censored adequacy")
    result["validation"]["baseline_original_table_clock_comparison"] = old_clock_differences
    result["validation"]["seven_core_final_LR_mean_SD_cost_reconciled"] = True


def main():
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser()
    for name in ["curves", "plan", "baseline-v1", "baseline-v2", "hcsn-summary", "core-table", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    input_names = ["curves", "plan", "baseline_v1", "baseline_v2", "hcsn_summary", "core_table"]
    identities = {name: identity(getattr(args, name)) for name in input_names}
    # Bind the full archived evidence identities, independently of exported report metadata.
    for name, digest in EXPECTED.items():
        require(identities[name]["sha256"] == digest, f"input SHA {name}")
    documents = {name: json.loads(getattr(args, name).read_text()) for name in input_names}
    data, plan = documents["curves"], documents["plan"]
    require(plan["input_curves_sha256"] == identities["curves"]["sha256"], "plan source binding")
    fits, points, validation = validate_inputs(data, documents["baseline_v1"], documents["baseline_v2"], documents["hcsn_summary"], documents["core_table"])
    result = {"schema": "hcsn-descriptive-resource-analysis-v1", "plan_scope": plan["scope"],
              "input_identities": identities, "source_identity": identity(Path(__file__)),
              "plan": plan, "validation": validation, "scientific_admission": "HOLD",
              "confirmation_access": False, "energy_joules": None, "model_execution": False,
              "CPU_axis_used_for_budget_selection": False, "whole_training_qualification": False,
              "views": {name: build_view(fits, points, include_c1, plan["fixed_budget_seconds"], plan["target_D_macro_f1"])
                        for name, include_c1 in [("original42_only", False), ("original42_plus_separate_C1", True)]},
              "controller_costs_overlap_attempts": {name: data[name] for name in ["original_controller", "C1_controller"]}}
    crosscheck_final(result, documents["baseline_v2"], documents["hcsn_summary"])
    compact = {"schema": "hcsn-recorded-resource-points-v1", "curves_sha256": identities["curves"]["sha256"],
               "columns": ["epoch", "kind", "wall_seconds", "CPU_lower_seconds", "CPU_upper_seconds", "quality"],
               "by_phase_and_name": {phase + "/" + name: [[p[k] for k in ["epoch", "kind", "wall_seconds", "CPU_lower_seconds", "CPU_upper_seconds", "quality"]] for p in rows]
                                     for (phase, name), rows in points.items()}}
    (args.output / "POINTS.json").write_text(json.dumps(compact, separators=(",", ":")) + "\n")
    result["compact_points"] = identity(args.output / "POINTS.json")
    require(all(identity(getattr(args, n)) == identities[n] for n in input_names), "analysis mutated input")
    result["analysis_main_entry_wall_seconds"] = time.perf_counter() - start_wall
    result["analysis_process_CPU_sample_seconds"] = time.process_time() - start_cpu
    result["validation"]["all_input_bytes_unchanged"] = True
    result["validation"]["passed"] = True
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": True, "result": identity(args.output / "RESULT.json"), "validation": validation}, separators=(",", ":")))


if __name__ == "__main__":
    main()
