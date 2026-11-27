#!/usr/bin/env python3
"""Independent read-only audit of retained operator-constructed B2 CPU probabilities.

Reads original fixed JSON bytes. Neither source attestation nor an independent
evaluator is claimed. DENY_ALL; never authorizes training or model adoption.
"""
from __future__ import annotations
import json
import hashlib
import math
from collections import Counter
from pathlib import Path

RESULT_SHA256 = "937a87f1da2e502f954be0870cd3a64ce06df0245938fc984b8b2a5ed0d95731"
MANIFEST_SHA256 = "0f12ac4aa7fd32989ba62983ed82367b83fe6a3f51868e4c1b8f567a9decf12a"
EXPECTED_SEEDS = (11, 17, 23, 29)
EXPECTED_FAMILIES = frozenset(("even", "comparison", "divisibility",
                              "set_membership", "prime"))
EXPECTED_PARENT = "9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c"

def require(test: bool, message: str) -> None:
    if not test:
        raise ValueError(message)

def close(got: float, expected: float, label: str) -> None:
    require(isinstance(got, (int, float)) and math.isfinite(got)
            and abs(got - expected) < 2e-6, label)

def load_original(directory: Path) -> tuple[dict, dict]:
    objects = []
    for filename, digest in (
        ("POSTTRAIN_B2_MANIFEST.json", MANIFEST_SHA256),
        ("POSTTRAIN_B2_RESULT.json", RESULT_SHA256),
    ):
        source = (directory / filename).read_bytes()
        require(hashlib.sha256(source).hexdigest() == digest,
                f"{filename}: original byte digest mismatch")
        objects.append(json.loads(source))
    return objects[0], objects[1]

def audit(manifest: dict, result: dict) -> dict:
    require(manifest["scope"] ==
            "operator-constructed arithmetic only; not an independent evaluator",
            "evaluation custody is not external")
    require(manifest["phase"] == "FROZEN_BEFORE_EVALUATION", "not a frozen manifest")
    require(manifest["training_archive_sha256"] == EXPECTED_PARENT,
            "training archive drift")
    require(result["archive_sha256"] == EXPECTED_PARENT
            and result["source_parent_v2_sha"] == EXPECTED_PARENT,
            "parent drift")
    require(result["authority"] == "DENY_ALL" and result["decision"] == "HOLD_NO_GO"
            and result["qualifier"] == "ACTUAL_CPU_INFERENCE_UNATTESTED_OPERATOR_ONLY",
            "unexpected authority or qualification")
    require(result["seeds"] == list(EXPECTED_SEEDS), "seed roster drift")
    require(result["task_count"] == 60, "task count drift")
    tasks = manifest["tasks"]
    require(len(tasks) == 60, "manifest task count drift")
    task_ids = [task["id"] for task in tasks]
    require(len(set(task_ids)) == len(task_ids), "duplicate manifest task")
    task_by_id = {t["id"]: t for t in tasks}
    per_family = Counter(t["family"] for t in tasks)
    require(set(per_family) == EXPECTED_FAMILIES and
            all(per_family[f] == 12 for f in EXPECTED_FAMILIES),
            "family roster drift")
    for family in EXPECTED_FAMILIES:
        truths = Counter(t["truth"] for t in tasks if t["family"] == family)
        require(truths == {"yes": 6, "no": 6}, "not a balanced family")
    runs = result["runs"]
    slots = [(r["arm"], r["seed"]) for r in runs]
    expected = [("frozen_base", 0)] + [(arm, seed)
        for seed in EXPECTED_SEEDS for arm in ("interleaved", "bursty")]
    require(slots == expected, "run roster/order drift")
    all_predictions = Counter()
    run_lookup = {}
    for run in runs:
        arm, seed = run["arm"], run["seed"]
        rows = run["scores"]["rows"]
        require(len(rows) == 60
                and [row["id"] for row in rows] == task_ids,
                "row roster/order drift")
        require(run["wall_seconds"] > 0
                and run["process_cpu_seconds"] > 0
                and run["ru_maxrss_kib_process_peak"] > 0,
                "missing basic process cost")
        successes, brier_values, loss_values = [], [], []
        family_scores: dict[str, list[tuple[int, float]]] = {}
        for row in rows:
            t = task_by_id[row["id"]]
            require((row["family"], row["truth"]) ==
                    (t["family"], t["truth"]), "target/family mismatch")
            p = row["p_yes"]
            require(type(p) in (float, int) and 0 < p < 1,
                    "invalid normalized output probability")
            prediction = "yes" if p >= 0.5 else "no"
            require(row["prediction"] == prediction
                    and type(row["correct"]) is bool
                    and row["correct"] == (prediction == row["truth"]),
                    "prediction/accuracy mismatch")
            require(type(row["input_tokens"]) is int and row["input_tokens"] > 0,
                    "missing input tokens")
            brier = (p - (1 if row["truth"] == "yes" else 0)) ** 2
            loss = -math.log(p if row["truth"] == "yes" else 1-p)
            close(row["brier"], brier, "row Brier")
            close(row["log_loss"], loss, "row log loss")
            successes.append(int(row["correct"]))
            brier_values.append(brier)
            loss_values.append(loss)
            family_scores.setdefault(row["family"], []).append(
                (int(row["correct"]), brier))
            all_predictions[prediction] += 1
        metrics = run["scores"]
        close(metrics["accuracy"], sum(successes)/60, "mean accuracy")
        close(metrics["mean_brier"], sum(brier_values)/60, "mean Brier")
        close(metrics["mean_log_loss"], sum(loss_values)/60, "mean log loss")
        require(set(metrics["families"]) == EXPECTED_FAMILIES,
                "family score roster drift")
        for family, observed in metrics["families"].items():
            values = family_scores[family]
            close(observed["accuracy"], sum(v[0] for v in values)/12,
                  "family accuracy")
            close(observed["mean_brier"], sum(v[1] for v in values)/12,
                  "family Brier")
        run_lookup[(arm, seed)] = metrics
    matched = []
    for seed in EXPECTED_SEEDS:
        a, b = run_lookup[("interleaved", seed)], run_lookup[("bursty", seed)]
        delta = {
            "seed": seed, "accuracy": b["accuracy"]-a["accuracy"],
            "mean_brier": b["mean_brier"]-a["mean_brier"],
            "mean_log_loss": b["mean_log_loss"]-a["mean_log_loss"],
        }
        matched.append(delta)
    for calculated, declared in zip(matched, result["paired_bursty_minus_interleaved"]):
        require(declared["seed"] == calculated["seed"], "paired seed mismatch")
        for metric in ("accuracy", "mean_brier", "mean_log_loss"):
            close(declared[metric], calculated[metric], "paired "+metric)
            close(result["mean_paired_deltas"][metric],
                  sum(m[metric] for m in matched)/len(matched),
                  "reported mean paired "+metric)
    require(sum(all_predictions.values()) == 540, "incomplete model forwards")
    return {
        "scope": "original retained real CPU forward probabilities; operator-generated arithmetic B2 only",
        "qualification": "HOLD_NO_GO", "authority": "DENY_ALL",
        "nine_model_runs": len(runs),
        "unique_tasks": len(tasks), "observed_forwards": sum(all_predictions.values()),
        "prediction_counts": dict(sorted(all_predictions.items())),
        "per_run_accuracy": [r["scores"]["accuracy"] for r in runs],
        "seed_paired_bursty_minus_interleaved": matched,
        "full_nine_run_wall_seconds_sum": sum(r["wall_seconds"] for r in runs),
        "full_nine_run_process_cpu_seconds_sum": sum(
            r["process_cpu_seconds"] for r in runs),
        "peak_per_run_rss_kib_max": max(
            r["ru_maxrss_kib_process_peak"] for r in runs),
        "independent_evaluator": False, "production_effect": False,
        "statistical_claim": "none: operator-generated B2 and 4 paired seeds",
    }

if __name__ == "__main__":
    d = Path(__file__).resolve().parent
    print(json.dumps(audit(*load_original(d)), sort_keys=True, indent=2))
