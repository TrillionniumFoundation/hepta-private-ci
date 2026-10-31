"""Read-only integrity of inactive D1 fitting enrichment, not an efficacy test."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from .bank_integrity_audit import digest, object_hash, local_hash, optimizer_hash
from .primary_audit_support import require


def check_row(row, old, receipt):
    require(row["partition"] == "fit" and 0 <= row["trajectory"] < 8 and
            row["inherited_parent_row_sha256"] == object_hash(old) and row["fitting_labels_inherited"] is True,
            "D1 inherited row identity differs")
    preserved = ("seed", "trajectory", "step", "partition", "state_sha256", "optimizer_sha256",
                 "schedule_sha256", "current_value", "before_output_sha256", "action_values",
                 "branches", "trajectory_action")
    require(all(row[key] == old[key] for key in preserved), "D1 changed an inherited fitting state, label or action")
    state = np.asarray(row["state"], dtype=float)
    require(state.shape == (30,) and np.isfinite(state).all() and
            row["state"][:7] + row["state"][12:] == old["state"], "D1 altered inherited H25 diagnostics")
    require((receipt["seed"], receipt["trajectory"], receipt["step"]) ==
            (row["seed"], row["trajectory"], row["step"]), "D1 directional receipt identity differs")
    original = {k: v for k, v in receipt.items() if k != "trajectory"}
    require(object_hash(original) == row["directional_receipt_sha256"] and
            receipt["features"] == row["state"][7:12] and receipt["state_grad_rng_invariant"] is True and
            receipt["parameter_sha256"] == row["state_sha256"] and
            receipt["optimizer_sha256"] == row["optimizer_sha256"], "D1 directional measurement binding differs")
    require("predictions" not in row and "prediction_controller_sha256" not in row,
            "Inactive D1 fitting enrichment has a fitted predictor")


def run(root, parent, study):
    summaries, total = [], {}
    require(not list(root.glob("audit-*")) and not (root/"PREDICTOR_FREEZE.json").exists(),
            "H7 passed, so D1 fresh audit and predictor fitting must remain inactive")
    gate = json.loads((parent/"H7_GATE_RESULT.json").read_text())
    require(gate["all_development_audit_gates_pass"] is True, "D1 inactivity premise differs")
    for seed in (17, 29, 43):
        folder, p = root/f"fit-{seed}", parent/f"fit-{seed}"
        bank, done, old = [json.loads(path.read_text()) for path in
                           (folder/"BANK.json", folder/"COMPLETE.json", p/"BANK.json")]
        receipts = json.loads((folder/"DIRECTIONAL_RECEIPTS.json").read_text())
        require(done["bank_sha256"] == digest(folder/"BANK.json") and done["rows"] == len(bank["records"]) == 288,
                "D1 complete fitting bank identity differs")
        require(bank["source_files"] == done["source_files"] and len(bank["source_files"]) == 31 and
                all(digest(study.parent/name) == identity for name, identity in bank["source_files"].items()),
                "D1 committed scientific source differs")
        require(bank["parent_fit_bank_sha256"] == digest(p/"BANK.json") and bank["phase"] == "fit" and
                bank["recipe"] == old["recipe"] and bank["fixed_action"] == old["fixed_action"] and bank["seed"] == seed,
                "D1 parent fitting treatment differs")
        require(bank["H7_audit_labels_used_for_fitting"] is False and bank["audit_observer_loaded"] is False and
                bank["test_retention_scored"] is False and bank["parent_gate_file_sha256"] is None and
                bank["parent_gate_inputs_sha256"] == {} and bank["parent_fit_label_rows"] == 288,
                "D1 fitting information boundary differs")
        require((folder/"PREDICTIONS_BEFORE_OUTCOMES.jsonl").read_bytes() == b"" and
                not list(folder.glob("*-values.npz")) and len(receipts) == bank["additional_directional_measurements"] == 288
                and digest(folder/"DIRECTIONAL_RECEIPTS.json") == bank["directional_receipts_sha256"],
                "D1 inherited-label and directional-receipt inventory differs")
        rows = {(row["trajectory"], row["step"]): row for row in bank["records"]}
        parents = {(row["trajectory"], row["step"]): row for row in old["records"]}
        measured = {(row["trajectory"], row["step"]): row for row in receipts}
        expected = {(trajectory, step) for trajectory in range(8) for step in range(0, 288, 8)}
        require(set(rows) == set(parents) == set(measured) == expected, "D1 complete fitting trajectory grid differs")
        for key in sorted(expected):
            row, previous = rows[key], rows.get((key[0], key[1]-8))
            check_row(row, parents[key], measured[key])
            if previous is not None:
                branch = previous["branches"][previous["trajectory_action"]]
                require(row["state_sha256"] == branch["model_sha256"] and
                        row["optimizer_sha256"] == branch["optimizer_sha256"] and
                        row["before_output_sha256"] == branch["output_sha256"] and
                        row["current_value"] == previous["action_values"][previous["trajectory_action"]],
                        "D1 selected path continuation differs")
        for trajectory in range(8):
            record = torch.load(folder/f"trajectory-{trajectory}-terminal.pt", map_location="cpu", weights_only=True)
            last = rows[trajectory, 280]
            branch = last["branches"][last["trajectory_action"]]
            require(local_hash(record["parameters"]) == record["local_sha256"] == branch["model_sha256"] and
                    optimizer_hash(record["optimizer"]) == record["optimizer_sha256"] == branch["optimizer_sha256"],
                    "D1 terminal complete state differs from inherited continuation")
        unit = {"next_gradient_forward_calls": 1, "next_gradient_backward_calls": 1, "teacher_forward_calls": 1,
                "response_probe_forward_calls": 4, "response_probe_reverse_calls": 2,
                "clean_probe_forward_calls": 1, "clean_probe_reverse_calls": 1,
                "next_gradient_forward_examples": 64, "next_gradient_backward_examples": 64,
                "teacher_forward_examples": 64, "response_probe_forward_examples": 512,
                "response_probe_reverse_examples": 1024, "clean_probe_forward_examples": 128,
                "clean_probe_reverse_examples": 128}
        require(all(receipt["resources"] == unit for receipt in receipts), "D1 measured additional per-boundary work differs")
        extra = {key: value*288 for key, value in unit.items()}
        resources = bank["resources"]
        expected_counts = {"candidate_gradient_forward_calls": 2304, "candidate_backward_calls": 2304,
            "candidate_gradient_examples": 147456, "frozen_teacher_forward_calls": 2304,
            "frozen_teacher_examples": 147456, "teacher_forced_H25_probe_calls": 1440,
            "teacher_forced_H25_probe_examples": 184320, "current_and_branch_hard_value_forward_calls": 1152,
            "current_and_branch_hard_value_examples": 147456, "rich_margin_forward_calls": 1152,
            "rich_margin_examples": 147456, "hard_value_and_margin_observer_digit_calls": 4608,
            "hard_value_and_margin_observer_digit_examples": 589824,
            "fixed_refinements_per_forward_example": 1+(bank["fixed_action"] != 0),
            "audit_observer_calls": 0, "test_retention_forward_calls": 0,
            "additional_directional_observation_work": extra, "inherited_parent_fitting_resources": old["resources"]}
        require(all(resources[key] == value for key, value in expected_counts.items()) and
                bank["chosen_path_or_branch_gradient_calls"] == 2304 and
                bank["chosen_path_or_branch_gradient_examples"] == 147456, "D1 base/additional cost accounting differs")
        for key, value in extra.items():
            total[key] = total.get(key, 0)+value
        summaries.append({"seed": seed, "rows": 288, "bank_sha256": digest(folder/"BANK.json"),
                          "directional_receipts_sha256": digest(folder/"DIRECTIONAL_RECEIPTS.json"),
                          "recorded_wall_ns": bank["wall_ns"]})
    return {"schema": "hepta.field-bridge.v2.inactive-directional-fit-integrity.1", "passed": True,
        "active": False, "fresh_audit_trajectories": 0, "predictors_fitted": 0, "primary_treatment": False,
        "reason": "All original H7 development gates passed; the D1 activation condition is false.",
        "seeds": summaries, "inherited_fit_snapshots": 864, "source_files_per_bank": 31,
        "additional_chosen_path_gradient_calls": 6912, "additional_chosen_path_gradient_examples": 442368,
        "additional_directional_measurement_work": total, "parent_H7_gate_sha256": digest(parent/"H7_GATE_RESULT.json"),
        "script_sha256": digest(Path(__file__)),
        "limitations": ["Read-only integrity of inherited labels, receipt bindings, selected-path hashes and counts.",
                        "No new directional gradient replay, independently held-out prediction test or efficacy conclusion.",
                        "Recorded extra work remains in the research cost ledger even though D1 was not activated."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.run, args.parent, args.study)
    with args.out.open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "active", "inherited_fit_snapshots", "fresh_audit_trajectories")}))
