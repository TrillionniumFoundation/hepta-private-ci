"""Whole-census analysis of the prespecified risk and success conjunction."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.statistics import (CrossedBootstrap, crossed_bootstrap,
    loss_tails, paired_comparison, summarize_utility)
from .evaluate import ALL_ARMS, METRICS, verify


def load_cubes(directory, protocol, protocol_sha):
    execution = json.loads((directory / "result.json").read_text())
    access = json.loads((directory / "access-registration.json").read_text())
    if (execution["status"] != "completed" or execution["protocol_sha256"] != protocol_sha
            or execution["source_identity"] != protocol["source_identity"]
            or access["protocol_sha256"] != protocol_sha
            or (access["role"], access["start"], access["count"]) != ("test", 512, 256)
            or access["source_identity"] != protocol["source_identity"]):
        raise ValueError("Complete same-protocol final evaluation is required")
    shape = (len(protocol["seeds"]), protocol["count"], len(protocol["views"]), protocol["scenarios"])
    result = {observer: {arm: {m: np.empty(shape) for m in METRICS} for arm in ALL_ARMS}
              for observer in ("primary", "secondary")}
    expected = {(r["seed"], r["arm"]): r for r in protocol["models"]}
    seen = set()
    for row in execution["models"]:
        key = row["seed"], row["arm"]
        if key in seen or key not in expected or row["sha256"] != expected[key]["sha256"]:
            raise ValueError("Duplicate, foreign or mismatched generator result")
        seen.add(key)
        if file_sha(Path(row["data_file"])) != row["data_sha256"]:
            raise ValueError("Evaluation data changed")
        index = protocol["seeds"].index(row["seed"])
        with np.load(row["data_file"], allow_pickle=False) as saved:
            if set(saved.files) != {f"{o}/{m}" for o in result for m in METRICS}:
                raise ValueError("Unexpected metric census")
            for observer in result:
                for metric in METRICS:
                    value = saved[f"{observer}/{metric}"]
                    if value.shape != shape[1:] or not np.isfinite(value).all():
                        raise ValueError("Incomplete/nonfinite evaluation cells")
                    if metric in ("success", "complete") and not np.isin(value, (0., 1.)).all():
                        raise ValueError("Success/completion must be measured binary events")
                    result[observer][row["arm"]][metric][index] = value
    if seen != set(expected):
        raise ValueError("A registered treatment/seed was omitted")
    return result


def source_only(plan):
    seeds = np.tile(np.arange(plan.seed_indices.shape[1], dtype=np.int64), (len(plan.seed_indices), 1))
    sources = plan.source_indices.copy()
    sha = hashlib.sha256(f"{seeds.shape}:{sources.shape}".encode() +
        seeds.astype("<i8").tobytes() + sources.astype("<i8").tobytes()).hexdigest()
    return CrossedBootstrap(seeds, sources, plan.random_seed, sha)


def analyze(protocol_path, output):
    protocol = json.loads(protocol_path.read_text())
    verify(protocol)
    directory = Path(protocol["output"])
    cubes = load_cubes(directory, protocol, file_sha(protocol_path))
    plan = crossed_bootstrap(len(protocol["seeds"]), protocol["count"],
        replicates=protocol["bootstrap"]["replicates"], seed=protocol["bootstrap"]["seed"])
    fixed = source_only(plan)
    observers = {}
    contrasts = (("risk_success", "mean"), ("risk_success", "risk"),
                 ("risk", "mean"), ("risk_success", "warm_mean"), ("mean", "warm_mean"))
    for observer, arms in cubes.items():
        cells, comparisons = {}, []
        for arm, metrics in arms.items():
            cells[arm] = {"raw_utility": summarize_utility(metrics["utility"], protocol["gamma"]),
                "mean_metrics": {k: float(v.mean()) for k, v in metrics.items()},
                "loss_tails": loss_tails(metrics["joint_loss"]),
                "success_per_seed": metrics["success"].mean(axis=(1, 2, 3)).tolist(),
                "by_view": {view: {"joint_CE": summarize_utility(metrics["utility"][:, :, i:i+1], protocol["gamma"])["joint_ce"],
                    "success": float(metrics["success"][:, :, i].mean()),
                    "completion": float(metrics["complete"][:, :, i].mean())}
                    for i, view in enumerate(protocol["views"])}}
        for candidate, reference in contrasts:
            primary = observer == "primary" and (candidate, reference) == ("risk_success", "mean")
            confidence = .975 if primary else .95
            a, b = arms[candidate], arms[reference]
            ce = paired_comparison(a["utility"], b["utility"], gamma=protocol["gamma"], confidence=confidence, bootstrap=plan)
            success = paired_comparison(a["success"], b["success"], estimand="success_rate", confidence=confidence, bootstrap=plan)
            entry = {"candidate": candidate, "reference": reference, "primary": primary,
                "raw_joint_CE": ce, "success_probability_difference": success}
            if primary:
                entry["fixed_five_seed_source_intervals"] = {
                    "CE": paired_comparison(a["utility"], b["utility"], gamma=protocol["gamma"], confidence=confidence, bootstrap=fixed),
                    "success": paired_comparison(a["success"], b["success"], estimand="success_rate", confidence=confidence, bootstrap=fixed),
                    "scope": "condition on these exact five trained models; resample only source pairs"}
                for name in ("CE", "success"):
                    entry["fixed_five_seed_source_intervals"][name]["bootstrap"]["resampling"] = "source-pair axis only; five fitted models fixed"
                    entry["fixed_five_seed_source_intervals"][name]["bootstrap"]["scope"] = "conditional on these five models, not a population of training seeds"
            comparisons.append(entry)
        observers[observer] = {"cells": cells, "comparisons": comparisons}
    main = observers["primary"]["comparisons"][0]
    ce_pass = main["raw_joint_CE"]["interval"][0] > 0
    success_pass = main["success_probability_difference"]["interval"][0] >= 0
    result = {"schema": "hepta.abc4.training-analysis.v1", "status": "completed",
        "protocol_sha256": file_sha(protocol_path), "execution_sha256": file_sha(directory / "result.json"),
        "source_pairs": protocol["count"], "distinct_source_images": 2 * protocol["count"],
        "training_seeds": protocol["seeds"], "scenarios": protocol["scenarios"], "views": protocol["views"],
        "new_optimizer_updates": protocol["new_training_steps_per_model"] * (len(ALL_ARMS) - 1) * len(protocol["seeds"]),
        "new_generator_models": (len(ALL_ARMS) - 1) * len(protocol["seeds"]),
        "fixed_reference_models": len(protocol["seeds"]),
        "selected_output_rows": len(protocol["models"]) * protocol["count"] * len(protocol["views"]) * protocol["scenarios"],
        "primary_CE_gate": ce_pass, "primary_zero_margin_success_gate": success_pass,
        "primary_conjunction_passed": bool(ce_pass and success_pass), "observers": observers,
        "empirical_population_constraint_certificate": False,
        "zero_margin_constraint_reference": "optimization uses warm mean; primary final comparison uses matched mean continuation",
        "bootstrap_limit": "nominal finite-five-seed percentile intervals; no guaranteed population coverage; no within-source replay inflation",
        "source_sharing": "same256pairs as separate control/cost experiment; no extra independent N",
        "previous_results_modified": False, "all_blockers_closed": False,
        "global_optimum_claimed": False, "raw_archival_required": False}
    write_json(output, result)
    print(json.dumps({"CE": main["raw_joint_CE"], "success": main["success_probability_difference"],
                      "conjunction_passed": result["primary_conjunction_passed"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.protocol, args.output)
