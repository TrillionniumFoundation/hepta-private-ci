"""Read-only diagnosis of every completed-to-stopped V7b paired transition."""

import argparse
import json
from pathlib import Path

import numpy as np

from v7_audit_records import canonical, file_hash, read, require


def describe(original_grid, corrected_grid, comparison, output):
    original_grid, corrected_grid, comparison, output = map(Path,
        (original_grid, corrected_grid, comparison, output))
    comparison_report = read(comparison/"comparison.json")
    require(comparison_report["status"] == "PASS" and comparison_report["compared_slots"] == 864,
        "complete paired audit required")
    paired_path = comparison/"all864-comparisons.json.gz"
    require(file_hash(paired_path) == comparison_report["all_slot_comparisons_sha256"], "exact all864 comparison rows")
    rows = [r for r in read(paired_path, True) if r["original_status"] == "completed" and r["corrected_status"] != "completed"]
    entries = []
    for row in rows:
        relative = Path(f"config{row['configuration_index']:02d}")/row["fit_id"]/row["policy"]
        with np.load(original_grid/relative/"compact.npz", allow_pickle=False) as data:
            original_actions = data["actions"]
        with np.load(corrected_grid/relative/"compact.npz", allow_pickle=False) as data:
            corrected_actions = data["actions"]
        count = len(corrected_actions)
        changed = np.flatnonzero(np.any(original_actions[:count] != corrected_actions, axis=1))
        require(len(changed) > 0, "recorded numerical prefix difference required for this diagnosis")
        first = int(changed[0])
        delta = original_actions[first]-corrected_actions[first]
        coordinate = int(np.argmax(np.abs(delta)))
        entry = {"configuration_index": row["configuration_index"], "fit_id": row["fit_id"], "policy": row["policy"],
            "original_status": row["original_status"], "corrected_status": row["corrected_status"],
            "original_completed_steps": row["original_completed_steps"], "corrected_completed_steps": count,
            "first_different_action_index_zero_based": first,
            "first_action_maximum_absolute_difference": float(np.max(np.abs(delta))),
            "first_action_maximum_difference_flat_coordinate": coordinate,
            "first_original_coordinate_value": float(original_actions[first, coordinate]),
            "first_corrected_coordinate_value": float(corrected_actions[first, coordinate]),
            "common_prefix_maximum_action_absolute_difference": float(np.max(np.abs(original_actions[:count]-corrected_actions))),
            "records": []}
        for name, grid in (("original", original_grid), ("corrected", corrected_grid)):
            path = grid/relative/"policy-record.json.gz"
            record = read(path, True)
            block = next(step for step in record["steps"] if step["at_step"] == count)
            plan, repair = block["plan"], block.get("repair")
            item = {"version": name, "policy_record_file_sha256": file_hash(path),
                "compact_file_sha256": file_hash(grid/relative/"compact.npz"),
                "status": record["status"], "error": record["error"], "block_origin_step": count,
                "block_committed_steps": block["committed_steps"], "plan_status": plan["status"],
                "plan_rounds": []}
            for round_ in plan["rounds"]:
                qp = round_["qp"]
                item["plan_rounds"].append({"iteration": round_["iteration"], "accepted": round_["accepted"],
                    "reason": round_.get("reason"), "qp": {key: qp.get(key) for key in ("status", "reason", "attempts",
                        "maximum_constraint_violation", "stationarity", "complementary_slackness",
                        "phase_one_status", "verified_box_infeasibility_lower_bound")}})
            if repair:
                step = repair["step_records"][-1]
                anchors = np.asarray(repair["original_old_anchors"])
                item["repair"] = {key: repair.get(key) for key in ("status", "certified", "failed_at_step",
                    "prospective_safe_steps", "certified_optimizer_steps", "committed_optimizer_steps", "threshold_slack")}
                item["last_repair_step"] = {key: step.get(key) for key in ("step", "status", "reason", "parameter_hold_within_box")}
                item["last_repair_step"].update(trials=[{"kind": trial["kind"], "length": trial["length"],
                    "within_threshold": trial["within_threshold"],
                    "maximum_old_panel_excess": float(np.max(np.asarray(trial["old_losses"])-anchors))}
                    for trial in step["trials"]], feasible_trials=sum(trial["within_threshold"] for trial in step["trials"]))
            entry["records"].append(item)
        entries.append(entry)
    report = {"schema": "hepta.cell-field-read-only-stop-regression-diagnosis.v7b", "status": "COMPLETE",
        "comparison_sha256": file_hash(comparison/"comparison.json"), "diagnostic_source_sha256": file_hash(__file__),
        "registered_completed_to_stopped_transitions": len(rows), "examined": len(entries),
        "qp_certificate_tolerances": {"stationarity_maximum": 1e-10, "primal_violation_maximum": 1e-10,
            "complementary_slackness_maximum": 1e-8},
        "unchanged_qp_source_sha256": read(corrected_grid/"executed_source.json")["cell_field_qp_v7.py"],
        "unchanged_repair_source_sha256": read(corrected_grid/"executed_source.json")["cell_field_repair_v7.py"],
        "entries": entries,
        "interpretation": "The stored records show explicit bounded numerical-solver/repair stops after tiny action-prefix differences, with no execution exception or committed action-box violation. This is consistent with numerical path sensitivity under the unchanged certificates. It does not prove global infeasibility or isolate every rounding cause through a new perturbation experiment.",
        "optimizer_or_control_calls": 0, "thresholds_or_budgets_changed": False,
        "primary_outputs_changed": False, "scientific_acceptance": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(report)+b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-grid", "corrected-grid", "comparison", "output"):
        parser.add_argument("--"+name, required=True)
    report = describe(**vars(parser.parse_args()))
    print(json.dumps({"examined": report["examined"], "optimizer_or_control_calls": 0}))
