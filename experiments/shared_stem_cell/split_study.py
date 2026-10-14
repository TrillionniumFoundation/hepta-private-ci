"""Real bundled-digit split controls, with calibration-only offline recommendation.

No pretrained Encoder, future window, writer-disjoint claim or topology activation.
Reuse controls.split_trial; expose routing, inheritance and full per-arm work.
"""
import argparse
from importlib.resources import files
from pathlib import Path

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.controls import split_trial
from experiments.shared_stem_cell.control_evaluation import summarize, probability_rows
from experiments.shared_stem_cell.split_learning import TrainingPartition

SEEDS = (17, 29, 43)
ARMS = ("parent_no_change", "parent_continued", "inherited_split", "larger_unsplit",
        "inherited_unsplit", "more_data")


def cohort(pixels):
    """Content only. No labels; source identity stays in a single fold."""
    ids = [e.sha(row.to(torch.uint8).numpy().tobytes()) for row in pixels]
    split = lambda value: ("holdout" if value < 2 else "calibration" if value == 2
                            else "extra_train" if value == 3 else "train")
    return ids, [split(int(value[:8], 16) % 10) for value in ids]


def recommend(predictions, calibration_labels, costs, *, classes):
    """Descriptive accuracy/size rule. Accepts NO holdout outcomes or future value.

    Highest calibration accuracy, then smallest parameter count, then no-change
    and stable arm order. It makes an offline suggestion, never grants authority.
    This is not independent statistical acceptance or an NDU/FBSDE optimizer.
    """
    if set(predictions) != set(ARMS) or set(costs) != set(ARMS):
        raise e.InputError("complete registered split comparison required")
    scores = summarize(predictions, calibration_labels,
                       [f"calibration-row-{i}" for i in range(len(calibration_labels))], classes=classes)
    for arm in ARMS:
        e.integer(costs[arm]["parameters"], 1, 8_388_608, "candidate parameter count")
    winner = min(ARMS, key=lambda arm: (-scores["scores"][arm]["correct"],
                                      costs[arm]["parameters"], ARMS.index(arm)))
    return {"recommended_arm": winner, "calibration_scores": scores,
            "rule": "accuracy_then_parameter_count_then_fixed_order",
            "holdout_labels_used": False, "independent_acceptance": False,
            "production_accepted": False}


def study(output, *, steps=160):
    import sklearn
    from sklearn.datasets import load_digits
    e.integer(steps, 1, 1000, "split study steps")
    output.mkdir(parents=True, exist_ok=False)
    try:
        data = load_digits()
        pixels = torch.tensor(data.data, dtype=torch.float32)
        identities, splits = cohort(pixels)
        x = pixels / 16
        groups = {name: [i for i, split in enumerate(splits) if split == name]
                  for name in ("train", "extra_train", "calibration", "holdout")}
        if any(not values for values in groups.values()):
            raise e.InputError("all registered folds must be nonempty")
        plan = {"dataset": "sklearn bundled UCI handwritten digits", "sklearn": sklearn.__version__,
            "data_sha256": e.sha(files("sklearn.datasets.data").joinpath("digits.csv.gz").read_bytes()),
            "cohort": list(zip(identities, splits)), "fold_counts": {k: len(v) for k,v in groups.items()},
            "seeds": SEEDS, "steps": steps, "arms": ARMS, "features": "raw pixels /16, no Encoder",
            "router": "two centroids from train only, fixed 16 Lloyd iterations ceiling",
            "choice": "calibration accuracy, then parameter count, then fixed order",
            "writer_disjoint_verified": False, "future_window": False, "pretrained_used": False,
            "source_sha256": {name: e.sha((Path(__file__).parent/name).read_bytes()) for name in (
                "split_study.py", "split_learning.py", "controls.py", "execution.py", "control_evaluation.py")}}
        e.write_once(output / "plan.json", plan)  # cohort sealed before labels are read
        partition, router_cost = TrainingPartition.fit(x[groups["train"]])
        with e.measured() as routing_application:
            routed = partition.append_route(x)
        e.write_once(output / "routing.json", {"fit": router_cost, "application": routing_application,
            "routes": partition.assign(x).tolist(), "shared_by_all_arms": True})
        evaluate_ids = groups["calibration"] + groups["holdout"]
        calibration_count = len(groups["calibration"])
        train_y = torch.tensor(data.target[groups["train"]], dtype=torch.long)
        extra_y = torch.tensor(data.target[groups["extra_train"]], dtype=torch.long)
        calibration_y = [int(data.target[i]) for i in groups["calibration"]]
        pending = []
        # No test labels are accessed here. Freeze every seed's recommendation first.
        for seed in SEEDS:
            with e.measured() as total:
                result = split_trial(routed[groups["train"]], train_y, routed[evaluate_ids],
                    classes=10, steps=steps, seed=seed,
                    extra=(routed[groups["extra_train"]], extra_y), matched_inheritance=True)
            for arm in ARMS:
                probability_rows(result["predictions"][arm], len(evaluate_ids), 10)
            path = output / f"seed-{seed}.json"
            seal = e.write_once(path, {"row_ids": evaluate_ids, "result": result, "whole_trial": total})
            saved = e.decode(e.bound_file(path, seal, 64 * 1024**2))
            decision = recommend({arm: p[:calibration_count] for arm,p in saved["result"]["predictions"].items()},
                                 calibration_y, saved["result"]["costs"], classes=10)
            decision["prediction_sha256"] = seal
            decision_seal = e.write_once(output / f"decision-{seed}.json", decision)
            pending.append((seed, path, seal, decision_seal))
        targets = [int(data.target[i]) for i in groups["holdout"]]  # after all choices are sealed
        summaries = []
        for seed, path, seal, decision_seal in pending:
            saved = e.decode(e.bound_file(path, seal, 64 * 1024**2))["result"]
            decision = e.decode(e.bound_file(output/f"decision-{seed}.json", decision_seal))
            predictions = {arm: p[calibration_count:] for arm,p in saved["predictions"].items()}
            evaluation = summarize(predictions, targets, [identities[i] for i in groups["holdout"]],
                                   classes=10, control="parent_continued")
            inherited = summarize(predictions, targets, [identities[i] for i in groups["holdout"]],
                                  classes=10, control="inherited_unsplit")
            chosen = decision["recommended_arm"]
            summaries.append({"seed": seed, "predictions_sha256": seal, "decision_sha256": decision_seal,
                "recommended_arm": chosen, "recommended_holdout_accuracy": evaluation["scores"][chosen]["accuracy"],
                "holdout": evaluation, "paired_against_inherited_unsplit": inherited["paired"],
                "parameters": {k: v["parameters"] for k,v in saved["costs"].items()},
                "per_arm_training_work": saved["per_arm_training_work"],
                "per_arm_optimizer_phase_wall_ns": {k: v.get("wall_ns", 0) +
                    (0 if k == "larger_unsplit" else saved["common_parent_training"]["wall_ns"])
                    for k,v in saved["costs"].items()}})
        report = {"runs": summaries, "fold_counts": plan["fold_counts"],
            "router_cost_record": "routing.json (one shared fit/application, not free)",
            "training_timing_scope": "per-arm optimizer phases; whole trial includes setup/copies; router separately shared",
            "seed_runs_are_not_independent_task_sets": True, "net_future_utility_established": False,
            "production_accepted": False, "independent_evaluation": False, "encoder_calls": 0,
            "torch": torch.__version__, "threads": torch.get_num_threads()}
        e.write_once(output / "report.json", report)
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    study(args.output)
