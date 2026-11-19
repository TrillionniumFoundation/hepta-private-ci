#!/usr/bin/env python3
"""Read-only paired probability audit of exposed HPCA CPU LoRA outputs.

No training, owner authority, independent evaluator, or production decisions.
Paired seeds—not the repeated prompts—are the experimental units.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

ARCHIVE_SHA256 = "caf20e60f0e0dc09b78b9c5433727dd028a2b6627c945d8dee7b54c238a66615"
SECTIONS = ("B_exposed_eval", "C_operator_constructed", "calibration")
ARMS = ("uniform", "heterogeneous")


def read_archive(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("unrecognized archived execution bytes")
    return json.loads(raw)


def _score(score):
    rows = score["rows"]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("missing or duplicated evaluation row")
    for row in rows:
        p = row["p_yes"]
        if type(p) not in (float, int) or not math.isfinite(p) or not 0 < p < 1:
            raise ValueError("probability outside open unit interval")
        if row["truth"] not in ("yes", "no") or row["prediction"] not in ("yes", "no"):
            raise ValueError("invalid binary label")
        if row["prediction"] != ("yes" if p >= 0.5 else "no"):
            raise ValueError("prediction inconsistent with stored probability")
        if type(row["correct"]) is not bool or row["correct"] != (row["truth"] == row["prediction"]):
            raise ValueError("correctness field inconsistent with labels")
        if len(row["prompt_sha256"]) != 64:
            raise ValueError("missing prompt identity")
    accuracy = sum(row["correct"] for row in rows) / len(rows)
    if not math.isclose(accuracy, score["accuracy"], abs_tol=1e-12):
        raise ValueError("accuracy disagrees with stored rows")
    nll = statistics.fmean(-math.log(row["p_yes"]) if row["truth"] == "yes"
                           else -math.log1p(-row["p_yes"]) for row in rows)
    brier = statistics.fmean((row["p_yes"] - (row["truth"] == "yes")) ** 2 for row in rows)
    return {"accuracy": accuracy, "log_loss": nll, "brier": brier}


def _identity(rows):
    return [(r["id"], r["truth"], r["prompt_sha256"]) for r in rows]


def _sign_flip_two_sided(deltas):
    """Descriptive sign enumeration; NOT a confirmatory randomization test."""
    observed = abs(statistics.fmean(deltas))
    draws = [abs(statistics.fmean(s * d for s, d in zip(signs, deltas)))
             for signs in itertools.product((-1, 1), repeat=len(deltas))]
    return sum(v + 1e-14 >= observed for v in draws) / len(draws)


def analyse(report):
    if (report.get("schema") != "HPCA-REAL-CPU-LORA-CLOCK-V1"
            or report.get("decision") != "HOLD_NO_GO"
            or report.get("authority") != "CANDIDATE_ONLY_DENY_ALL_HOLD_NO_GO"):
        raise ValueError("wrong source schema or qualification boundary")
    seeds = report["seeds"]
    if len(seeds) != 4 or len(set(seeds)) != 4:
        raise ValueError("not the four archived independent training seeds")
    runs = report["runs"]
    if len(runs) != len(seeds) * len(ARMS) or sorted((r["seed"], r["arm"]) for r in runs) != sorted(
            (seed, arm) for seed in seeds for arm in ARMS):
        raise ValueError("missing, duplicated or extra paired arm")
    indexed = {(r["seed"], r["arm"]): r for r in runs}
    output = {"schema": "HPCA-REAL-CPU-PROBABILITY-AUDIT-V1",
              "raw_archive_sha256": ARCHIVE_SHA256,
              "source": "already_exposed_nonindependent_model_predictions",
              "qualification": "HOLD_NO_GO", "authority": "DENY_ALL",
              "experimental_unit": "paired_training_seed_not_individual_prompt",
              "posthoc_exploratory": True,
              "sections": {}}
    for section in SECTIONS:
        parent = report["parent_scores"][section]
        parent_metrics = _score(parent)
        identity = _identity(parent["rows"])
        per_seed = []
        for seed in seeds:
            pair = {arm: indexed[seed, arm] for arm in ARMS}
            if (pair["uniform"]["all_source_events"] != pair["heterogeneous"]["all_source_events"]
                    or pair["uniform"]["actual_updated_parameter_elements"] != pair["heterogeneous"]["actual_updated_parameter_elements"]):
                raise ValueError("training source or update-budget mismatch")
            metrics = {}
            for arm in ARMS:
                score = pair[arm]["scores"][section]
                if _identity(score["rows"]) != identity:
                    raise ValueError("cross-arm/evaluator row identity drift")
                metrics[arm] = _score(score)
            differences = {key: metrics["heterogeneous"][key] - metrics["uniform"][key]
                           for key in ("accuracy", "log_loss", "brier")}
            per_seed.append({"seed": seed, "heterogeneous_minus_uniform": differences,
                             "uniform": metrics["uniform"], "heterogeneous": metrics["heterogeneous"]})
        deltas = [r["heterogeneous_minus_uniform"]["log_loss"] for r in per_seed]
        output["sections"][section] = {
            "question_count": len(identity), "frozen_parent": parent_metrics,
            "per_seed": per_seed,
            "mean_heterogeneous_minus_uniform": {
                key: statistics.fmean(row["heterogeneous_minus_uniform"][key] for row in per_seed)
                for key in ("accuracy", "log_loss", "brier")},
            "exploratory_two_sided_sign_flip_p_log_loss": _sign_flip_two_sided(deltas),
            "note": "four paired seeds on disclosed reused prompts; exploratory only",
        }
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path(__file__).with_name("real_cpu_clock_v1_RESULT.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    outcome = analyse(read_archive(args.archive))
    args.out.write_text(json.dumps(outcome, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXPOSED-ONLY", outcome["qualification"], str(args.out))


if __name__ == "__main__":
    main()
