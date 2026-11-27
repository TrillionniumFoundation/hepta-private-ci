#!/usr/bin/env python3
"""Post-hoc probability audit of actual, publicly exposed HPCA V2 CPU LoRA runs.

Scores and digests are from an operator archive: no Owner/evaluator attestation.
Training seeds, not prompt rows, are the four paired units.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from real_probability_audit import _identity, _score, _sign_flip_two_sided

ARCHIVE_SHA256 = "9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c"
ARMS = ("interleaved", "bursty")
SEEDS = (11, 17, 23, 29)
SECTIONS = ("B_exposed_eval", "C_operator_constructed", "calibration")


def read_archive(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("raw V2 archive bytes do not match frozen source identity")
    return json.loads(raw)


def analyse(raw):
    if (raw.get("schema") != "HPCA-REAL-CPU-LORA-CLOCK-V2-MATCHED"
            or raw.get("decision") != "HOLD_NO_GO"
            or raw.get("authority") != "CANDIDATE_ONLY_DENY_ALL_HOLD_NO_GO"
            or raw.get("selection") != "NO_UPDATE_RECOMMENDED_NOT_OWNER_DECISION"
            or raw.get("seeds") != list(SEEDS)):
        raise ValueError("incorrect archive, seed roster or authority boundary")

    runs = raw["runs"]
    if (len(runs) != 8
            or sorted((run["seed"], run["arm"]) for run in runs)
            != [(seed, arm) for seed in SEEDS for arm in sorted(ARMS)]):
        raise ValueError("missing or duplicated paired seed/clock condition")
    paired = {(run["seed"], run["arm"]): run for run in runs}
    arm_orders = {}
    for seed in SEEDS:
        pair = {arm: paired[seed, arm] for arm in ARMS}
        order = tuple(pair[ARMS[0]]["arm_order"])
        if (order not in (ARMS, ARMS[::-1])
                or any(tuple(run["arm_order"]) != order for run in pair.values())):
            raise ValueError("clock order identity drift")
        arm_orders[order] = arm_orders.get(order, 0) + 1
        if any(not isinstance(run["plan_digest"], str) for run in pair.values()):
            raise ValueError("missing matched clock plan")
        if pair[ARMS[0]]["plan_digest"] != pair[ARMS[1]]["plan_digest"]:
            raise ValueError("clock plan identity mismatch")
        for arm, run in pair.items():
            if (run["steps"] != 12 or len(run["step_log"]) != 12
                    or run["actual_updated_parameter_elements"] != 829440
                    or run["adapter_parameters_total"] != 138240
                    or run["cold_reload_max_p_yes_difference"] != 0):
                raise ValueError("optimizer or cold model reload mismatch")
            for cost in ("process_cpu_seconds", "train_evaluate_save_reload_wall_seconds"):
                if (type(run[cost]) not in (int, float)
                        or not math.isfinite(run[cost]) or run[cost] < 0):
                    raise ValueError("invalid observed resource cost")
            if sum(step["input_tokens"] for step in run["step_log"]) != run["input_tokens_train"]:
                raise ValueError("training token accounting mismatch")
        for group in (0, 1):
            left, right = [
                [(row["source_id"], row["source_sha256"], row["input_tokens"])
                 for row in pair[arm]["step_log"] if row["group"] == group]
                for arm in ARMS
            ]
            if len(left) != 6 or left != right:
                raise ValueError("group-specific matched training exposure violated")
    if arm_orders.get(ARMS) != 2 or arm_orders.get(ARMS[::-1]) != 2:
        raise ValueError("AB/BA execution order not balanced")

    result = {
        "schema": "HPCA-V2-EXPOSED-PROBABILITY-POSTHOC-V1",
        "input_sha256": ARCHIVE_SHA256,
        "candidate": "HOLD_NO_GO",
        "authority": "DENY_ALL",
        "evaluation": "PRE_EXPOSED_AND_OPERATOR_CONSTRUCTED_NOT_INDEPENDENT",
        "experimental_unit": "four_paired_training_seeds",
        "confirmatory_inference": False,
        "hypothesis": "bursty_minus_interleaved",
        "source_binding": "SHA256_OF_ARCHIVED_BYTES_NOT_OWNER_ATTESTATION",
        "arm_orders": {"interleaved_then_bursty": 2, "bursty_then_interleaved": 2},
        "sections": {},
    }
    for section in SECTIONS:
        base = raw["parent_scores"][section]
        base_metric = _score(base)
        identity = _identity(base["rows"])
        per_seed = []
        for seed in SEEDS:
            metrics = {}
            for arm in ARMS:
                current = paired[seed, arm]["scores"][section]
                if _identity(current["rows"]) != identity:
                    raise ValueError("cross-seed or cross-arm evaluation identity drift")
                metrics[arm] = _score(current)
            diff = {key: metrics["bursty"][key] - metrics["interleaved"][key]
                    for key in ("accuracy", "log_loss", "brier")}
            per_seed.append({
                "seed": seed, "bursty_minus_interleaved": diff,
                "interleaved": metrics["interleaved"], "bursty": metrics["bursty"],
            })
        ll_deltas = [pair["bursty_minus_interleaved"]["log_loss"] for pair in per_seed]
        result["sections"][section] = {
            "questions": len(identity),
            "parent": base_metric,
            "per_seed": per_seed,
            "mean_bursty_minus_interleaved": {
                metric: statistics.fmean(pair["bursty_minus_interleaved"][metric]
                                         for pair in per_seed)
                for metric in ("accuracy", "log_loss", "brier")
            },
            "exploratory_two_sided_signflip_p_log_loss": _sign_flip_two_sided(ll_deltas),
            "claim": "post_hoc_only_not_equivalence_not_independent_efficacy",
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path,
                        default=Path(__file__).with_name("real_cpu_clock_v2_RESULT.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = analyse(read_archive(args.archive))
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True,
                                   allow_nan=False) + "\n", encoding="utf-8")
    print(result["candidate"], result["schema"], args.out)


if __name__ == "__main__":
    main()
