"""Descriptive accounting after all frozen test evaluations; never selects weights."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean, median


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stats(values):
    return {"n": len(values), "mean": mean(values), "median": median(values),
            "min": min(values), "max": max(values)} if values else {"n": 0}


def main(root):
    root = Path(root)
    protocol_path = root / "FORMAL_PROTOCOL_v2.json"
    protocol = json.loads(protocol_path.read_text())
    seal_path = root / "GLOBAL_CANDIDATE_SEAL.json"
    seal = json.loads(seal_path.read_text())
    test_path = root / "formal_v2_test/RESULT.json"
    evaluation = json.loads(test_path.read_text())
    if evaluation["seal_sha256"] != sha(seal_path) or evaluation["protocol_sha256"] != sha(protocol_path):
        raise ValueError("Evaluation identity differs")
    test = {r["name"]: r for r in evaluation["rows"]}
    if len(test) != len(seal["rows"]) or set(test) != {r["name"] for r in seal["rows"]}:
        raise ValueError("Incomplete or duplicate evaluation roster")
    rows = []
    for bound in seal["rows"]:
        path = root / "formal_v2_training" / bound["name"] / "RESULT.json"
        if sha(path) != bound["result_sha256"]:
            raise ValueError("Training result changed")
        training = json.loads(path.read_text())
        result = test[bound["name"]]
        if result["status"] == "EVALUATED":
            if sha(root / "formal_v2_test" / (bound["name"] + ".npz")) != result["predictions_sha256"]:
                raise ValueError("Frozen prediction bytes changed")
        rows.append({"name": bound["name"], "train": training, "test": result})
    valid = [r for r in rows if r["test"]["status"] == "EVALUATED"]
    main_rows = [r for r in valid if r["train"]["case"]["group"] == "main_factorial"]
    selection = {"all": dict(Counter(r["train"]["selected_step"] for r in valid)),
                 "main": dict(Counter(r["train"]["selected_step"] for r in main_rows)),
                 "counts_at_final_budget_do_not_prove_convergence": True}
    parameters = []
    for width in (8, 16, 32, 64):
        for connection in ("fixed", "learned"):
            subset = [r for r in main_rows if r["train"]["case"]["width"] == width
                      and r["train"]["case"]["connection"] == connection]
            train = [r["train"] for r in subset]
            parameters.append({"width": width, "recurrent_connection": connection,
                "allocated": sorted({r["parameters"]["allocated"] for r in train}),
                "trainable": sorted({r["parameters"]["trainable"] for r in train}),
                "recurrent_allocated": sorted({r["parameters"]["recurrent_allocated"] for r in train}),
                "recurrent_mask_active": sorted({r["parameters"]["recurrent_mask_active"] for r in train}),
                "selected_changed_elements": stats([r["selected_updated_parameter_elements"] for r in train]),
                "last_changed_elements": stats([r["last_updated_parameter_elements"] for r in train]),
                "selected_recurrent_changed_elements": stats([r["parameter_deltas"]["recurrent.weight"]["selected_changed_elements"] for r in train]),
                "state_tensor_bytes_batch_8": sorted({r["state_tensor_bytes"] for r in train}),
                "state_bytes_per_episode": sorted({r["state_tensor_bytes"] // r["state_batch"] for r in train})})
    controls = []
    for width in (8, 16, 32, 64):
        for bank in ("value_risk", "tanh"):
            subset = [r for r in main_rows if r["train"]["case"]["width"] == width
                      and r["train"]["case"]["bank"] == bank
                      and r["train"]["case"]["message"] == "full"
                      and r["train"]["case"]["connection"] == "learned"]
            controls.append({"width": width, "bank": bank, "n_initialization_seeds": len(subset),
                "raw_old_penalty_accuracy": stats([r["test"]["baselines"]["raw_old_penalty"]["accuracy"] for r in subset]),
                "raw_same_penalty_accuracy": stats([r["test"]["baselines"]["raw_same_penalty"]["accuracy"] for r in subset]),
                "initial_standardized_accuracy": stats([r["test"]["baselines"]["standardized"]["accuracy"] for r in subset]),
                "selected_accuracy": stats([r["test"]["selected"]["accuracy"] for r in subset]),
                "selected_pre_late_accuracy": stats([r["test"]["selected"]["pre_late_accuracy"] for r in subset]),
                "selected_cross_entropy": stats([r["test"]["selected"]["cross_entropy"] for r in subset]),
                "selected_steps": [r["train"]["selected_step"] for r in subset],
                "train_total_wall_s": stats([r["train"]["cost"]["total_case_wall_s"] for r in subset]),
                "test_total_wall_s": stats([r["test"]["cost"]["total_wall_s"] for r in subset]),
                "end_to_end_case_plus_independent_test_wall_s": stats([r["train"]["cost"]["total_case_wall_s"] + r["test"]["cost"]["total_wall_s"] for r in subset]),
                "count_reaching_preregistered_test_accuracy": sum(r["test"]["test_quality_reached"] for r in subset)})
    messages = []
    for bank in ("value_risk", "tanh"):
        for channel in ("boundary", "flow", "full"):
            subset = [r for r in main_rows if r["train"]["case"]["bank"] == bank
                      and r["train"]["case"]["message"] == channel]
            messages.append({"bank": bank, "message": channel,
                             "accuracy": stats([r["test"]["selected"]["accuracy"] for r in subset])})
    cost = defaultdict(float)
    for row in valid:
        for name, value in row["test"]["cost"].items():
            cost[name] += value
    # Recurrent learned/fixed is a gradient flag only; initial baselines are duplicate.
    unique_initials = [r for r in main_rows if r["train"]["case"]["connection"] == "learned"]
    diagnostic = {"unique_initial_feature_conditions": len(unique_initials),
        "raw_same_to_standardized_accuracy_gain": stats([r["test"]["baselines"]["standardized"]["accuracy"] -
             r["test"]["baselines"]["raw_same_penalty"]["accuracy"] for r in unique_initials]),
        "raw_old_to_standardized_accuracy_gain": stats([r["test"]["baselines"]["standardized"]["accuracy"] -
             r["test"]["baselines"]["raw_old_penalty"]["accuracy"] for r in unique_initials]),
        "standardized_accuracy": stats([r["test"]["baselines"]["standardized"]["accuracy"] for r in unique_initials]),
        "old_penalty_accuracy": stats([r["test"]["baselines"]["raw_old_penalty"]["accuracy"] for r in unique_initials]),
        "variance_below_old_penalty_fraction": stats([r["train"]["initial_feature_statistics"]["fraction_variance_below_old_penalty_0p02"] for r in unique_initials]),
        "initial_feature_positive_spectrum_condition": stats([r["train"]["initial_feature_statistics"]["condition_positive_spectrum"] for r in unique_initials])}
    output = {"status": "COMPLETED_DESCRIPTIVE_ACCOUNTING", "analysis_source_sha256": sha(__file__),
              "protocol_sha256": sha(protocol_path), "seal_sha256": sha(seal_path), "evaluation_sha256": sha(test_path),
              "analysis_was_not_used_for_training_selection": True, "all_rows": len(rows), "evaluated": len(valid),
              "selection_steps": selection, "parameters_and_state": parameters, "full_message_learned_controls": controls,
              "message_marginals": messages, "independent_test_cost_totals": dict(cost),
              "unique_initial_feature_scaling_controls": diagnostic,
              "limitations": ["Synthetic task, shared held-out set and data seed, only three initialization seeds.",
                "Marginal and paired statistics are descriptive; overlapping cases are not independent replications.",
                "Fixed connections freeze recurrent weights; input, field-control, and readout parameters can still train.",
                "The fixed recurrent mask is topology; this experiment does not learn mask structure.",
                "Shared baseline feature passes and simultaneous diagnostic heads prevent a standalone ridge-versus-BP end-to-end speed claim.",
                "Same update and CPU cap does not imply equal parameter count across widths or optimization convergence.",
                "Feature-bank tanh is an equal-dimensional readout control inside SmallHCSN, not a conventional standalone RNN.",
                "Deployment/adoption and real-user transfer are not performed in this synthetic study."]}
    path = root / "ANALYSIS.json"
    if path.exists():
        raise FileExistsError("Analysis already materialized")
    path.write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"analysis_sha256": sha(path), "rows": len(rows), "evaluated": len(valid),
                      "selection_steps": selection}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    main(parser.parse_args().root)
