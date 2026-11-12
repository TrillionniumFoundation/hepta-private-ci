#!/usr/bin/env python3
"""Reproducible qualification-only HPCA matrix; Python standard library only."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics

from credit import run_credit
from replay import run_replay, POLICIES
from schedules import (CALIBRATION_SEEDS, TEST_SEEDS, FAMILIES,
                       SLOTS, run_schedule, tune_rates)


def average(values):
    return statistics.fmean(values)


def paired_difference(left, right, seed):
    """Paired exploratory bootstrap; not a confirmatory error guarantee."""
    if len(left) != len(right) or len(left) == 0:
        raise ValueError("paired seed arrays required")
    delta = [a - b for a, b in zip(left, right)]
    rng = random.Random(800000 + seed)
    boot = sorted(
        average([delta[rng.randrange(len(delta))]
                 for _ in range(len(delta))])
        for _ in range(2000)
    )
    return {
        "mean_delta": round(average(delta), 8),
        "paired_seed_count": len(delta),
        "exploratory_bootstrap_95pct": [
            round(boot[50], 8), round(boot[1949], 8)
        ],
    }


def source_manifest():
    root = Path(__file__).parent
    sha = hashlib.sha256()
    files = ("credit.py", "schedules.py", "replay.py", "run.py")
    for filename in files:
        payload = (root / filename).read_bytes()
        sha.update(filename.encode("utf-8"))
        sha.update(len(payload).to_bytes(8, "big"))
        sha.update(payload)
    return sha.hexdigest()


def run_suite(seeds=TEST_SEEDS):
    if not seeds or any(s not in TEST_SEEDS for s in seeds):
        raise ValueError("test seeds must be a nonempty registered subset")

    learning_rates = {policy: tune_rates(policy) for policy in SLOTS}
    schedules = {
        policy: [run_schedule(seed, policy, learning_rates[policy])
                 for seed in seeds]
        for policy in SLOTS
    }
    credits = {
        route: [run_credit(seed, routing=route) for seed in seeds]
        for route in ("routed", "context_gradient", "random",
                      "shuffled", "broadcast")
    }
    delayed = {}
    for delay, density in ((0, 1.0), (8, 1.0), (8, 0.15)):
        for trace in ("event_id", "latest"):
            label = f"d{delay}_density{density:g}_{trace}"
            delayed[label] = [
                run_credit(seed, routing="routed", trace=trace,
                           delay=delay, feedback_density=density)
                for seed in seeds
            ]
    replays = {
        policy: [run_replay(seed, policy=policy) for seed in seeds]
        for policy in POLICIES
    }

    def series(rows, key):
        return [row[key] for row in rows]

    return {
        "schema": "HEPTA-HPCA-MICRO-V1",
        "authority": "QUALIFICATION_ONLY_NOT_REAL_MODEL_EVIDENCE",
        "source_manifest_sha256": source_manifest(),
        "calibration_seeds": list(CALIBRATION_SEEDS),
        "heldout_test_seeds": list(seeds),
        "schedule": {
            "per_arm_update_budget": 256,
            "tuned_rates": learning_rates,
            "mean_mse": {
                name: round(average(series(rows, "mean_mse")), 8)
                for name, rows in schedules.items()
            },
            "family_mean_mse": {
                name: {
                    f: round(average([row["family_mse"][f] for row in rows]), 8)
                    for f in FAMILIES
                } for name, rows in schedules.items()
            },
            "heterogeneous_minus_uniform_mse": paired_difference(
                series(schedules["heterogeneous"], "mean_mse"),
                series(schedules["uniform"], "mean_mse"), 1),
        },
        "credit": {
            "heldout_accuracy": {
                route: round(average(series(rows, "heldout_accuracy")), 8)
                for route, rows in credits.items()
            },
            "mean_parameter_updates": {
                route: round(average(series(rows, "parameter_updates")), 3)
                for route, rows in credits.items()
            },
            "versus_routed_accuracy": {
                route: paired_difference(
                    series(rows, "heldout_accuracy"),
                    series(credits["routed"], "heldout_accuracy"), 10 + i)
                for i, (route, rows) in enumerate(credits.items())
                if route != "routed"
            },
        },
        "delay": {
            label: {
                "mean_accuracy": round(
                    average(series(rows, "heldout_accuracy")), 8),
                "mean_observed_feedback": round(
                    average(series(rows, "feedback_count")), 3),
            } for label, rows in delayed.items()
        },
        "replay": {
            "old_task_retention": {
                name: round(average(series(rows, "old_retention")), 8)
                for name, rows in replays.items()
            },
            "new_task_accuracy": {
                name: round(average(series(rows, "new_accuracy")), 8)
                for name, rows in replays.items()
            },
            "mean_parameter_updates": {
                name: average(series(rows, "parameter_updates"))
                for name, rows in replays.items()
            },
            "mean_selection_reads": {
                name: average(series(rows, "selection_reads"))
                for name, rows in replays.items()
            },
            "vs_uniform_old_retention": {
                name: paired_difference(
                    series(rows, "old_retention"),
                    series(replays["uniform"], "old_retention"), 20 + i)
                for i, (name, rows) in enumerate(replays.items())
                if name != "uniform"
            },
        },
        "decision": "HOLD_NO_GO",
        "open_gates": [
            "independent real task outcome and reward observations",
            "same-source Cell/owner/encoder/data/evaluator/ABI identity",
            "resource-matched native forward/backward, I/O, storage, energy and latency",
            "separate final test, multiple comparison and training repeat controls",
            "true semantic and procedure outcomes, cross-modal complement and retention",
            "revoke/rollback/unlearning canary and independent operator admission",
            "real Agentd stage owner through NoUpdate/Adopt and different next task",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="RESULT.json")
    parser.add_argument("--seed-limit", type=int, default=len(TEST_SEEDS))
    args = parser.parse_args()
    if not 1 <= args.seed_limit <= len(TEST_SEEDS):
        parser.error("seed-limit must be in [1,16]")
    result = run_suite(TEST_SEEDS[:args.seed_limit])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2,
                              allow_nan=False) + "\n", encoding="utf-8")
    print(f"HPCA candidate-only run; seeds={args.seed_limit}; {out}")


if __name__ == "__main__":
    main()
