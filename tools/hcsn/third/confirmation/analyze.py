"""Audit all saved predictions and report the prespecified per-seed gates."""
import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from next.common import classification_metrics
from third.confirmation.contract import atomic_json, require_development, sha
from third.confirmation.data import unpack


def main():
    prerequisite = require_development()
    protocol = json.loads((HERE / "protocol.json").read_text())
    manifest = json.loads((HERE / "data_manifest.json").read_text())
    rows, shard_hashes = [], {}
    for seed in protocol["seeds"]:
        path = HERE / "shards" / f"seed{seed}.json"
        shard = json.loads(path.read_text())
        if not shard["complete"] or shard["prerequisite"] != prerequisite:
            raise RuntimeError("Missing or incomplete fixed seed shard")
        if shard["manifest_sha256"] != sha(HERE / "data_manifest.json"):
            raise RuntimeError("Shard cohort identity changed")
        rows.extend(shard["runs"])
        shard_hashes[str(path.relative_to(HERE))] = sha(path)
    expected = {(task, seed, variant) for task in protocol["tasks"]
                for seed in protocol["seeds"] for variant in protocol["variants"]}
    if len(rows) != len(expected) or {(r["task"], r["seed"], r["variant"]) for r in rows} != expected:
        raise RuntimeError("The fixed30-run matrix is not complete and unique")
    metric_error = 0.0
    for cohort in manifest["cohorts"]:
        if sha(HERE / cohort["file"]) != cohort["sha256"]:
            raise RuntimeError("Dataset file changed")
        data = unpack(HERE / cohort["file"])
        group = [r for r in rows if (r["task"], r["seed"]) == (cohort["task"], cohort["seed"])]
        paired = [r for r in group if r["variant"] != "memory_mass"]
        if len({r["initial_parameters_sha256"] for r in paired}) != 1:
            raise RuntimeError("Paired arms did not start identically")
        for row in group:
            if row["data_sha256"] != cohort["sha256"] or row["data_fingerprints"] != cohort["fingerprints"]:
                raise RuntimeError("Training/evaluation data identity differs across arms")
            for field in ("checkpoint", "predictions"):
                if sha(HERE / row[field + "_file"]) != row[field + "_sha256"]:
                    raise RuntimeError("Model or prediction artifact changed")
            with np.load(HERE / row["predictions_file"]) as predictions:
                for name in predictions.files:
                    metrics = classification_metrics(predictions[name], data[name]["y"])
                    metric_error = max(metric_error, max(abs(v - row["metrics"][name][key]) for key, v in metrics.items()))
    if metric_error > 1e-12:
        raise RuntimeError("Saved-prediction metrics failed independent recomputation")
    numerical = all(d["all_finite"] and d["condition_bound_satisfied"] and
        d["maximum_relative_residual"] <= protocol["numerical"]["maximum_relative_residual"] and
        d["maximum_condition_times_solver_epsilon"] <= protocol["numerical"]["maximum_condition_times_solver_epsilon"]
        for row in rows for d in row["solve_diagnostics"].values())
    ability, per_seed, contrasts, challenges = {}, [], [], []
    for variant in protocol["variants"]:
        for row in rows:
            if row["variant"] != variant:
                continue
            threshold = protocol["primary_ability_gate"][row["task"]]
            for length in protocol["primary_lengths"]:
                accuracy = row["metrics"]["clean" + str(length)]["accuracy"]
                per_seed.append(dict(task=row["task"], variant=variant, seed=row["seed"],
                                     length=length, accuracy=accuracy, threshold=threshold, passed=accuracy >= threshold))
        ability[variant] = all(r["passed"] for r in per_seed if r["variant"] == variant)
    for task in protocol["tasks"]:
        for length in protocol["primary_lengths"]:
            values = {}
            for variant in protocol["variants"]:
                values[variant] = [next(r for r in rows if (r["task"], r["seed"], r["variant"]) ==
                                   (task, seed, variant))["metrics"]["clean" + str(length)]["accuracy"]
                                   for seed in protocol["seeds"]]
            difference = np.asarray(values["full_mass"]) - np.asarray(values["c1_mass"])
            mean, se = float(difference.mean()), float(difference.std(ddof=1) / np.sqrt(len(difference)))
            half = float(t.ppf(1 - .05 / (2 * 6), len(difference) - 1) * se)
            ordinary = float(t.ppf(.975, len(difference) - 1) * se)
            contrasts.append(dict(task=task, length=length, accuracies_by_seed=values,
                paired_differences=difference.tolist(), mean=mean,
                conditional_seed_ci95=[mean - ordinary, mean + ordinary],
                bonferroni_family95=[mean - half, mean + half]))
        for row in rows:
            if row["task"] == task:
                challenges.append(dict(task=task, seed=row["seed"], variant=row["variant"],
                    metrics={name: row["metrics"][name] for name in ("clean512", "async128", "gaussian128", "missing128")}))
    result = dict(complete=True, prerequisite=prerequisite, checked_runs=len(rows),
        shard_sha256=shard_hashes, manifest_sha256=sha(HERE / "data_manifest.json"),
        maximum_recomputed_metric_error=metric_error, all_numerical_checks_passed=numerical,
        candidate_ability_gate_passed=ability["full_mass"] and numerical,
        per_variant_ability=ability, per_seed_primary=per_seed,
        primary_shape_contrasts=contrasts, separate_challenges=challenges,
        run_resources=[{k: r[k] for k in ("task", "seed", "variant", "width", "parameters", "resources")} for r in rows],
        total_formal_run_cpu_seconds=sum(r["total_run_cpu_seconds"] for r in rows),
        total_formal_run_wall_seconds=sum(r["total_run_wall_seconds"] for r in rows),
        all_six_shape_intervals_above_zero=all(c["bonferroni_family95"][0] > 0 for c in contrasts),
        shape_comparisons_separate_from_ability=True, full_backbone_authorized=False,
        scope="Thirty formal runs, separate from48 development runs; all five seeds and primary lengths retained. "
              "A capability pass does not establish financial-specific, hardware, energy or backbone superiority.")
    atomic_json(HERE / "analysis.json", result)
    print(json.dumps(dict(runs=len(rows), numerical=numerical, abilities=ability,
                         candidate_ability_gate=result["candidate_ability_gate_passed"])), flush=True)


if __name__ == "__main__":
    main()
