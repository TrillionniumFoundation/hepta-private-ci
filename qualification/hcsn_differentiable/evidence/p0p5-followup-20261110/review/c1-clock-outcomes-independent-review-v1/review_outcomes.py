"""Independently recompute C1 clock intervals and the fixed-LR baseline table.

Input is retained small audit artifacts and original terminal outer receipts.
No checkpoint, model, optimizer or active native process is touched.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
SMALL = ROOT / "baseline36-c1-review-small-originals-v1"
OUT = Path(__file__).resolve().parent
INPUTS = {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    raw = Path(path).read_bytes()
    digest = {"bytes": len(raw), "sha256": sha(raw)}
    assert str(path) not in INPUTS or INPUTS[str(path)] == digest
    INPUTS[str(path)] = digest
    return raw


def obj(path):
    return json.loads(read(path))


def close(left, right):
    # Clock ordering checks below are strict; this tolerance applies only to
    # recomputing sums/metrics with potentially different floating sum order.
    assert math.isfinite(left) and math.isfinite(right)
    assert abs(left-right) <= 1e-9


def save(name, value):
    with (OUT / name).open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-v1-result", type=Path)
    parser.add_argument("--full-v2-result", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    manifest = obj(SMALL / "MANIFEST.json")
    for name, expected in manifest["files"].items():
        raw = read(SMALL / name)
        assert {"bytes": len(raw), "sha256": sha(raw)} == expected
    plan = obj(ROOT / "campaign-v2-plan.json")
    assert INPUTS[str(ROOT / "campaign-v2-plan.json")]["sha256"] == "e13f97aafdaf66548f016f2dcc3a38dd7e641a2ea83d52b8bea89f4c7e0cf114"
    native_c1 = obj(ROOT / "native-c1-completed-20261110-v1/RESULT.json")
    assert INPUTS[str(ROOT / "native-c1-completed-20261110-v1/RESULT.json")]["sha256"] == "f09e2d72f9c8c49fc03c0669713faba46cd634fb26185f33f2ae962c0350c894"
    child_outer = {row["name"]: row for row in native_c1["attempts"]}
    assert len(child_outer) == 7
    commands = [json.loads(line) for line in read(SMALL / "v2/output/original-commands-context.jsonl").splitlines()]
    outer = {row["name"]: row for row in commands if row["status"] == "completed" and not row["name"].startswith("hcsn-")}
    originals = {value["name"]: value for value in (obj(path) for path in sorted((SMALL / "v1/output").glob("original-*.json")))}
    children = {value["name"]: value for value in (obj(path) for path in sorted((SMALL / "v2/output").glob("C1-*.json")))}
    assert len(originals) == len(outer) == 36 and set(children) == set(child_outer)
    assert all(row["audit_status"] == "passed_completed_original_baseline" for row in originals.values())
    confusion_checks, common_label_counts = [], None
    for row in list(originals.values())+list(children.values()):
        metrics = row["independent_selected_development"]
        matrix = metrics["confusion_matrix"]
        assert len(matrix) == 11 and all(len(values) == 11 for values in matrix)
        assert all(type(v) is int and v >= 0 for values in matrix for v in values)
        supports = [sum(values) for values in matrix]
        assert sum(supports) == metrics["events"] == 31952
        assert common_label_counts is None or common_label_counts == supports
        common_label_counts = supports
        macro = sum(2*matrix[i][i]/(supports[i]+sum(matrix[j][i] for j in range(11))) for i in range(11))/11
        accuracy = sum(matrix[i][i] for i in range(11))/31952
        close(macro, metrics["macro_f1_11_classes"])
        close(accuracy, metrics["accuracy"])
        confusion_checks.append({"name": row["name"], "macro_f1": macro, "accuracy": accuracy})
    intervals, curves, states = [], [], []
    for name, child in children.items():
        original = originals[name]
        parent_cost = outer[name]["whole_process_wall_seconds"]
        phase_cost = child_outer[name]["whole_process_wall_seconds"]
        assert child["parent_report_sha256"] == original["report_sha256"] == outer[name]["result_sha256"]
        assert child["child_report_sha256"] == child_outer[name]["result_sha256"]
        assert child["audit_status"] == "passed_completed_C1_chain_artifacts"
        adapter, chain = child["clock_sampling_adapter"], child["phase_chain"]
        assert not adapter["raw_report_modified"] and not adapter["existing_helper_tolerance_changed"]
        assert adapter["helper_receives_deep_copy_with_late_phase_clock"]
        points = chain["observed_points"]
        continued = [point for point in points if point["phase"] == "C1"]
        assert len(points) == 100+len(continued) and len(continued) == len(adapter["intervals"])
        gaps = []
        for point, interval in zip(continued, adapter["intervals"]):
            early = interval["raw_phase_early_seconds"]
            cumulative = interval["original_cumulative_seconds_unchanged"]
            late = cumulative-parent_cost
            assert all(math.isfinite(v) for v in (early, cumulative, late, phase_cost))
            assert 0 <= early <= late <= phase_cost
            assert late == interval["derived_phase_late_seconds"]
            assert late-early == interval["sample_gap_seconds"]
            assert interval["child_complete_outer_wall_seconds"] == phase_cost
            assert point["epoch"] == interval["epoch"] and point["cumulative_process_wall_seconds"] == cumulative
            assert point["cumulative_cpu_upper_seconds"] is None
            gaps.append(late-early)
        assert chain["charged_chain_outer_wall_seconds"] == parent_cost+phase_cost
        assert chain["actual_parent_outer_wall_ceiling_seconds"] == outer[name]["hard_wall_seconds"]
        best, best_epoch, anchor, stale, first_stop = -1.0, None, -1.0, 0, None
        for epoch, point in enumerate(points, 1):
            assert point["epoch"] == epoch and math.isfinite(point["quality"])
            score = point["quality"]
            if score > best:
                best, best_epoch = score, epoch
            if score > anchor+plan["plateau_delta"]:
                anchor, stale = score, 0
            else:
                stale += 1
            if epoch >= plan["min_epochs"] and stale >= plan["patience"] and first_stop is None:
                first_stop = epoch
        assert first_stop == len(points) and best_epoch == chain["combined_state"]["best_epoch"]
        close(best, child["independent_selected_development"]["macro_f1_11_classes"])
        assert chain["derived_chain_adequacy"] and child["inherited_memorization_passed"]
        assert child["new_diagnostic_updates"] == 0 and not child["resume_start_state_directly_observed"]
        assert child["fresh_forward"]["max_logit_absolute_difference"] == 0
        assert child["fresh_forward"]["performed"] and not child["fresh_forward"]["gradients"]
        first = next((point for point in points if point["quality"] >= plan["quality_threshold"]), None)
        assert first == chain["first_observed_quality_crossing"]
        assert [cut["budget"] for cut in chain["wall_budget_cuts"]] == [300,900,1800]
        for cut in chain["wall_budget_cuts"]:
            eligible = [point for point in points if point["cumulative_process_wall_seconds"] <= cut["budget"]]
            expected = max(eligible, key=lambda point: point["quality"]) if eligible else None
            assert expected == cut["best_observed"] and cut["no_interpolation"]
        intervals.append({"name": name, "continued_epochs": len(continued), "intervals_checked": len(gaps),
                          "minimum_sample_gap_seconds": min(gaps), "maximum_sample_gap_seconds": max(gaps),
                          "strict_order_and_outer_end_bound": True})
        curves.append({"name": name, "first_crossing_from_epoch_points": first,
                       "wall_cuts_from_original_later_cumulative": chain["wall_budget_cuts"]})
        states.append({"name": name, "cumulative_epochs": len(points), "best_epoch": best_epoch,
                       "first_plateau_epoch": first_stop, "child_outer_seconds": phase_cost,
                       "complete_parent_outer_seconds": parent_cost})

    combined = dict(originals)
    combined.update(children)
    table = obj(SMALL / "v2/output/CORE_TABLE.json")
    assert len(table) == 6
    table_checks = []
    for row in table:
        arm = row["arm"]
        roster = [f"{arm}-s{seed}-lr{lr:g}" for seed in plan["seeds"] for lr in plan["learning_rates"]]
        means = {lr: sum(combined[f"{arm}-s{seed}-lr{lr:g}"]["independent_selected_development"]["macro_f1_11_classes"] for seed in plan["seeds"])/3 for lr in plan["learning_rates"]}
        selected = max(plan["learning_rates"], key=lambda lr: means[lr])
        assert selected == row["common_learning_rate"]
        assert [seed["seed"] for seed in row["individual_seeds"]] == sorted(plan["seeds"])
        f1 = []
        for seed in row["individual_seeds"]:
            raw = combined[seed["name"]]
            assert seed["D_metrics"] == raw["independent_selected_development"]
            assert seed["quality"] == seed["D_metrics"]["macro_f1_11_classes"]
            assert seed["learning_rate"] == selected and seed["name"] in roster
            expected_cost = outer[seed["name"]]["whole_process_wall_seconds"] + (child_outer[seed["name"]]["whole_process_wall_seconds"] if seed["name"] in child_outer else 0)
            close(seed["charged_complete_process_wall_seconds"], expected_cost)
            assert seed["actual_original_outer_wall_ceiling_seconds"] == outer[seed["name"]]["hard_wall_seconds"]
            f1.append(seed["quality"])
        for metric, average in row["D_three_seed_mean"].items():
            close(average, sum(seed["D_metrics"][metric] for seed in row["individual_seeds"])/3)
        close(row["D_macro_f1_sample_standard_deviation"], statistics.stdev(f1))
        assert row["D_macro_f1_seed_min"] == min(f1) and row["D_macro_f1_seed_max"] == max(f1)
        cost = sum(outer[name]["whole_process_wall_seconds"] for name in roster)
        cost += sum(item["whole_process_wall_seconds"] for name,item in child_outer.items() if name in roster)
        close(cost, row["all_six_original_plus_C1_process_wall_sum_seconds"])
        close(row["selected_LR_complete_process_wall_sum_seconds"], sum(seed["charged_complete_process_wall_seconds"] for seed in row["individual_seeds"]))
        table_checks.append({"arm": arm, "LR_means_from_all_six": means, "selected_common_LR": selected,
                             "all_six_plus_C1_active_process_wall_seconds": cost,
                             "selected_LR_adequate_chains": row["selected_LR_adequate_chains"],
                             "D_mean_macro_f1": row["D_three_seed_mean"]["macro_f1_11_classes"]})
    summary = obj(SMALL / "v2/output/SUMMARY.json")
    original_count = sum(row["independent_adequacy"]["independently_recomputed"] for row in originals.values())
    combined_count = sum(True if name in children else row["independent_adequacy"]["independently_recomputed"] for name,row in originals.items())
    assert original_count == summary["original_baseline_heuristic_adequacy_passes"] == 26
    assert combined_count == summary["combined_baseline_chain_heuristic_adequacy_passes"] == 33
    assert summary["memorization_failures_retained"] == [name for name,row in originals.items() if not row["memorization_passed"]] or set(summary["memorization_failures_retained"]) == {name for name,row in originals.items() if not row["memorization_passed"]}
    assert summary["passed"] and not summary["full42_final_audit"] and summary["scientific_admission"] == "HOLD"
    first_receipt, second_receipt = [obj(SMALL/f"v{i}/launch/receipt.json") for i in (1,2)]
    assert first_receipt["returncode"] == 1 and first_receipt["status"] == "failed"
    assert second_receipt["returncode"] == 0 and second_receipt["status"] == "completed"
    assert second_receipt["result_sha256"] == summary["result_sha256"]
    large = []
    for version,path in ((1,args.full_v1_result),(2,args.full_v2_result)):
        if path is None:
            continue
        full = obj(path)
        expected = (first_receipt if version == 1 else second_receipt)["result_sha256"]
        assert INPUTS[str(path)]["sha256"] == expected
        if version == 2:
            assert full["core_fixed_LR_table"] == table and full["C1_records"] == [children[row["name"]] for row in full["C1_records"]]
            assert full["identity_checks"]["pinned_inputs_unchanged"] and full["identity_checks"]["source_unchanged"]
        large.append({"version": version, "path": str(path), **INPUTS[str(path)]})
    assert all({"bytes": Path(p).stat().st_size, "sha256": sha(Path(p).read_bytes())} == identity for p,identity in INPUTS.items())
    result = {"schema": "independent-C1-actual-clock-and-selection-review-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "passed_scoped_recomputation": True, "small_manifest_members_checked": len(manifest["files"]),
              "clock_interval_checks": intervals, "C1_epoch_curve_checks": curves, "C1_stopping_checks": states,
              "confusion_matrix_metric_checks": confusion_checks, "common_D_label_counts": common_label_counts,
              "fixed_LR_table_checks": table_checks, "original_heuristic_passes": original_count,
              "combined_heuristic_passes": combined_count, "memorization_failures_retained": summary["memorization_failures_retained"],
              "prior_failed_review_cost": {key:first_receipt[key] for key in ("whole_review_process_wall_seconds","waited_review_child_cpu_seconds")},
              "new_supplement_review_cost": {key:second_receipt[key] for key in ("whole_review_process_wall_seconds","waited_review_child_cpu_seconds")},
              "review_cost_scope": "Two distinct native review child costs; launcher/packaging/bootstrap have separate scopes and are not added again here.",
              "full_results_read": large, "inputs": INPUTS, "inputs_unchanged": True,
              "model_or_logit_forward_repeated": False, "native_checkpoint_read": False,
              "training_performed": False, "HCSN_final_result_reviewed": False, "scientific_admission": "HOLD",
              "first_crossing_presentation_limitation": "CORE_TABLE uses original report.process_time_to_quality_seconds for uncontinued fits, but per-epoch row clocks for a C1 chain's parent crossing. Both are observed clocks; do not call the whole column uniformly recomputed from one epoch field. All seven C1 row curves/cuts were independently recomputed here; uncontinued-fit crossing timestamps were not rederived from raw parent reports in this review.",
              "fresh_logits_scope": "Native reviewer reports seven exact no-grad logits comparisons; this pass rechecks bound metadata and tables, not the large logits themselves.",
              "review_wall_sample_before_serialization_seconds": time.monotonic()-started,
              "review_cpu_sample_before_serialization_seconds": time.process_time()}
    save("RESULT.json", result)
    save("SUMMARY.json", {key:result[key] for key in ("schema","passed_scoped_recomputation","small_manifest_members_checked","clock_interval_checks","fixed_LR_table_checks","original_heuristic_passes","combined_heuristic_passes","scientific_admission")})
    print(json.dumps({"result_bytes": (OUT/"RESULT.json").stat().st_size, "result_sha256": sha((OUT/"RESULT.json").read_bytes()),
                      "C1_intervals": sum(row["intervals_checked"] for row in intervals), "table_checks": table_checks}, indent=2))


if __name__ == "__main__":
    main()
