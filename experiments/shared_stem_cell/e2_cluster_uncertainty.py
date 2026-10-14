"""Read-only, group-paired uncertainty audit over an independently replayed E2 sweep.

The unit resampled is an original holdout source group with its entire seed
trajectory, never a seed×item observation. Results are exploratory and MUST NOT
select a Head or claim source-group independence, future NDU or production use.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
import math
from pathlib import Path

import numpy as np

from experiments.shared_stem_cell.e2_budget_review import review_sweep
from experiments.shared_stem_cell.preflight_review import checked_bytes, require
from experiments.shared_stem_cell.wire import decode, sha, write_once

SCHEMA = "hepta.stem.e2-paired-source-uncertainty.v1"
BUDGETS = (2048, 8192, 16384, 65536, 262144)
SEEDS = (11, 23, 47)
CONTRASTS = tuple(combinations(BUDGETS, 2))
REPLICATES = 10000
BOOTSTRAP_SEED = 20261014


def case_correctness(rows: list[dict], labels: dict[str, int]) -> dict[tuple[int, int, str], int]:
    """Make one trained correctness value for each budget/seed/holdout case."""
    result = {}
    for row in rows:
        if row["split"] != "holdout" or row["role"] != "trained":
            continue
        key = (row["ceiling"], row["seed"], row["case_id"])
        require(key not in result and row["case_id"] in labels,
                "duplicate or unknown held-out E2 case")
        p = row["probabilities"]
        require(type(p) is list and len(p) == 4
                and all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in p)
                and abs(math.fsum(p)-1) <= 1e-5, "nonprobabilistic E2 outcome")
        result[key] = int(max(range(4), key=p.__getitem__) == labels[row["case_id"]])
    require(set(result) == {(budget, seed, case_id) for budget in BUDGETS
                            for seed in SEEDS for case_id in labels},
            "E2 budget/seed/holdout census is incomplete")
    return result


def source_paired_statistics(correct: dict, group_by_case: dict[str, str], *, replicates=REPLICATES):
    require(type(replicates) is int and 1000 <= replicates <= 10000,
            "bounded preregistered resampling repetitions required")
    require(type(group_by_case) is dict and 2 <= len(group_by_case) <= 16384
            and len(set(group_by_case)) == len(group_by_case)
            and all(type(g) is str and g for g in group_by_case.values()),
            "missing bounded original source-group identity")
    expected = {(budget, seed, case_id) for budget in BUDGETS
                for seed in SEEDS for case_id in group_by_case}
    require(set(correct) == expected and all(type(v) is int and v in (0, 1)
                                            for v in correct.values()),
            "incomplete E2 correctness census")
    cluster_ids = sorted(set(group_by_case.values()))
    require(len(cluster_ids) >= 2, "insufficient source-group labels")
    output = []
    alpha = .05 / len(CONTRASTS)
    for left, right in CONTRASTS:
        grouped = defaultdict(list)
        for case_id, group in group_by_case.items():
            # Keep the SAME source example across all seeds in each resample.
            deltas = [correct[(right, seed, case_id)] - correct[(left, seed, case_id)]
                      for seed in SEEDS]
            grouped[group].append(sum(deltas) / len(deltas))
        values = np.asarray([np.mean(grouped[g]) for g in cluster_ids], dtype=np.float64)
        rng = np.random.default_rng(BOOTSTRAP_SEED + left * 31 + right)
        # Fixed-memory repeated resampling; never count seeds as independent rows.
        simulations = np.empty(replicates, dtype=np.float64)
        for i in range(replicates):
            simulations[i] = values[rng.integers(0, len(values), size=len(values))].mean()
        low, high = np.quantile(simulations, [alpha / 2, 1 - alpha / 2])
        l95, u95 = np.quantile(simulations, [.025, .975])
        output.append({"from_budget": left, "to_budget": right,
                       "observed_gain_per_original_source_group": float(values.mean()),
                       "bootstrap_95_interval": [float(l95), float(u95)],
                       "bonferroni_familywise_95_interval": [float(low), float(high)],
                       "familywise_interval_excludes_zero_exploratory": bool(low > 0 or high < 0),
                       "source_group_labels_reported": len(values),
                       "seed_trajectories_per_original_case": len(SEEDS),
                       "independent_source_group_sampling_verified": False})
    return output


def audit(manifest_path: Path, producer: Path, report_sha256: str, sweep: Path):
    # This rereads the actual physics from all 60 safetensors checkpoints before
    # considering statistical claims; an adversary cannot just fabricate scores.
    physical = review_sweep(manifest_path, producer, report_sha256, sweep)
    require(physical["physical_head_checkpoint_count"] == 60
            and physical["independently_replayed_prediction_vectors"] == 1920,
            "incomplete real E2 physical evidence")
    plan = decode(checked_bytes(manifest_path))
    source = [decode(raw) for raw in checked_bytes(
        manifest_path.parent / plan["dataset"]["path"], plan["dataset"]["sha256"]).splitlines()]
    groups = {row["case_id"]: row["group"] for row in source if row["split"] == "holdout"}
    labels = {row["case_id"]: row["label"] for row in source if row["split"] == "holdout"}
    require(len(groups) == len(labels) == 32 and len(set(groups.values())) == 32,
            "original 32-row public holdout/group-label census drift")
    run = decode(checked_bytes(sweep / "run.json"))
    packet = decode(checked_bytes(sweep / "predictions.json", run["predictions_sha256"]))
    correct = case_correctness(packet["predictions"], labels)
    return {"schema": SCHEMA, "e2_run_sha256": sha(checked_bytes(sweep / "run.json")),
            "original_dataset_sha256": plan["dataset"]["sha256"],
            "physical_review_sha256": sha(checked_bytes(producer / "report.json", report_sha256)),
            "observed_original_holdout_cases": len(labels),
            "distinct_reported_source_group_labels": len(set(groups.values())),
            "independent_source_group_samples_verified": False,
            "seeds_correlated_within_source_group": list(SEEDS),
            "registered_budgets": list(BUDGETS),
            "registered_pairwise_comparisons": len(CONTRASTS),
            "bootstrap_replicates": REPLICATES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "paired_budget_diagnostics": source_paired_statistics(correct, groups),
            "source_groups_are_self_declared_not_independently_attested": True,
            "posthoc_holdout_diagnostics_not_a_selection_gate": True,
            "future_ndu_verified": False, "production_accepted": False,
            "research_winner_selected": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--sweep", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    x = parser.parse_args()
    x.output.parent.mkdir(parents=True, exist_ok=True)
    write_once(x.output, audit(x.manifest, x.producer, x.report_sha256, x.sweep))


if __name__ == "__main__":
    main()
