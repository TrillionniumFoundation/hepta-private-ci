"""Construct labelled synthetic receipts to demonstrate the gate API, not efficacy."""

import json
from pathlib import Path

from .factorial import BASELINES, CELLS, COSTS, FAMILIES, REGIMES, canonical_digest, select_comparators, audit


def example():
    digest = canonical_digest
    p = {"schema": "ndu-factorial-v1", "evidence_kind": "synthetic",
         "registered_at": "2026-11-01T00:00:00Z", "weighting": "equal_cluster",
         "risk_profile_id": "nested-entropic-portfolio-v1", "dataset_digest": digest("synthetic-data"),
         "objective_digest": digest("fixed-external-score-and-cost-objective"),
         "evaluator_digest": digest("independent-synthetic-evaluator"),
         "measurement_digest": digest("disjoint-additive-cost-unit-definition"),
         "cost_unit": "synthetic-compute-unit", "cost_weight": .01, "net_margin": 0.01,
         "retention_margin": .02, "alpha": .05, "min_clusters": 20, "bootstrap_samples": 20000,
         "bootstrap_seed": 775, "failure_score": 0.0, "seeds": [11, 29],
         "deployment_counts": [100, 1000, 10000], "arms": list(CELLS) + list(BASELINES),
         "tasks": [], "profiles": {}}
    for split in ("train", "validation", "test"):
        for cohort in ("new", "retention"):
            for i in range(20):
                p["tasks"].append({"task_id": f"{split}/{cohort}/{i}", "split": split, "cohort": cohort,
                                   "cluster_id": f"{split}-{cohort}-{i}", "source_group": f"{split}-{cohort}-{i}",
                                   "family": FAMILIES[i % 5]})
    for regime in REGIMES:
        for arm in p["arms"]:
            core, controller = CELLS.get(arm, ("ordinary", arm))
            p["profiles"][f"{regime}:{arm}"] = {
                "data_digest": p["dataset_digest"], "initial_content_digest": digest(core),
                "model_digest": digest([regime, core]), "policy_digest": digest([regime, arm]),
                "risk_profile_id": p["risk_profile_id"], "objective_digest": p["objective_digest"],
                "deployable": True, "active_parameters": 1000, "core": core, "controller": controller,
                "budget": {"train_compute": 100, "train_examples": 1000, "search_trials": 4,
                           "episode_cost": 100, "wall_seconds": 10, "peak_bytes": 1048576},
                "training_actual": {"train_compute": 80, "train_examples": 1000, "search_trials": 4},
                "research_costs": {"training": 80, "search": 30, "evaluation": 10}}
    rows = []
    for task in p["tasks"]:
        if task["split"] == "train":
            continue
        for seed in p["seeds"]:
            for regime in REGIMES:
                for arm in p["arms"]:
                    key = f'{task["task_id"]}/{seed}/{regime}/{arm}'
                    profile = p["profiles"][f"{regime}:{arm}"]
                    day = "02" if task["split"] == "validation" else "04"
                    score = {"A": .4, "B": .5, "C": .45, "D": .7, "initial": .3,
                             "tuned_fixed": .53, "voi": .56, "mpc": .6}[arm]
                    if task["cohort"] == "retention":
                        score = .7
                    elif regime == "joint":
                        score += .1 if arm == "D" else .01
                    rows.append({"row_type": "episode_terminal", "run_id": key, "task_id": task["task_id"],
                                 "split": task["split"], "seed": seed, "regime": regime, "arm": arm,
                                 "cluster_id": task["cluster_id"], "status": "success", "external_score": score,
                                 "attempt_ids": [f"{key}/attempt/0"], "failed_attempts": 0,
                                 "costs": {c: 0.1 for c in COSTS}, "latency_seconds": 1.0, "peak_bytes": 1024,
                                 "started_at": f"2026-11-{day}T01:00:00Z", "finished_at": f"2026-11-{day}T01:00:01Z",
                                 "model_digest": profile["model_digest"], "policy_digest": profile["policy_digest"],
                                 "evaluator_digest": p["evaluator_digest"], "measurement_digest": p["measurement_digest"],
                                 "risk_profile_id": p["risk_profile_id"], "objective_digest": p["objective_digest"],
                                 "output_digest": digest(key)})
    val = [r for r in rows if r["split"] == "validation"]
    lock = select_comparators(p, val, "2026-11-03T00:00:00Z")
    return p, rows, lock


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    p, rows, lock = example()
    for name, data in (("protocol.json", p), ("episodes.json", rows), ("comparator-lock.json", lock),
                       ("synthetic-audit.json", audit(p, rows, lock))):
        (args.output / name).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
