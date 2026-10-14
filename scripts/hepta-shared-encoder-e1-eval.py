#!/usr/bin/env python3
"""Paired chronology-aware *descriptive* shared-Encoder shadow evaluator.

Does not authenticate model execution, NDU signatures, label chronology, or
future prediction sealing. Never selects a winner or authorizes promotion.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import re
import sys

SCHEMA = "hepta.shared-encoder-paired-shadow-e1.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SPLITS = {"train", "calibration", "test", "future", "ood", "old"}
MAX_JSONL_ROWS = 32_768
MAX_JSONL_LINE_CHARS = 262_144


def require(condition, message):
    if not condition:
        raise ValueError(message)


def iso_utc(value):
    require(type(value) is str and value.endswith("Z"), "UTC timestamps must end in Z")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0,
            "timestamp not UTC")
    return stamp


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            require(len(line) <= MAX_JSONL_LINE_CHARS, "oversized JSONL line")
            if not line.strip():
                continue
            try:
                def pairs_unique(pairs):
                    result = {}
                    for key, val in pairs:
                        require(key not in result, "duplicate JSON object key")
                        result[key] = val
                    return result
                obj = json.loads(
                    line, object_pairs_hook=pairs_unique,
                    parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid JSONL at line {number}: {exc}") from exc
            require(type(obj) is dict, "JSONL row must be object")
            rows.append(obj)
            require(len(rows) <= MAX_JSONL_ROWS, "too many JSONL rows")
    require(bool(rows), "empty JSONL")
    return rows


def validate_dataset(rows, scope, task, cutoff, evaluated_at):
    require(type(scope) is str and bool(scope) and type(task) is str and bool(task),
            "scope/task required")
    require(cutoff < evaluated_at, "training cutoff must precede evaluation")
    by_id = {}
    groups = defaultdict(set)
    selected = []
    for row in rows:
        require(type(row) is dict, "dataset row must be object")
        for field in (
            "case_id", "scope_id", "task_id", "split", "group_id",
            "event_time", "label_available_at", "label"
        ):
            require(field in row, "dataset field missing: " + field)
        require(type(row["case_id"]) is str and bool(row["case_id"])
                and row["case_id"] not in by_id, "duplicate/empty dataset case")
        by_id[row["case_id"]] = row
        require(type(row["scope_id"]) is str and bool(row["scope_id"])
                and type(row["task_id"]) is str and bool(row["task_id"]),
                "invalid dataset scope/task")
        require(type(row["split"]) is str and row["split"] in SPLITS, "unknown dataset split")
        require(type(row["group_id"]) is str and bool(row["group_id"]), "group identity missing")
        require(type(row["label"]) is int and row["label"] in (0, 1), "binary label required")
        event = iso_utc(row["event_time"])
        label = iso_utc(row["label_available_at"])
        require(event < label, "labels must follow events")
        groups[(row["scope_id"], row["task_id"], row["group_id"])].add(row["split"])
        if row["scope_id"] == scope and row["task_id"] == task:
            if row["split"] in {"train", "calibration", "test"}:
                require(event < cutoff and label <= cutoff,
                        "pre-cutoff training/calibration/test label leaked past freeze")
            elif row["split"] in {"future", "ood", "old"}:
                require(event > cutoff, "held-out event not strictly after training cutoff")
                require(label <= evaluated_at, "held-out label not yet released for retrospective evaluation")
                selected.append(row)
    for splits in groups.values():
        require(len(splits) == 1, "cross-split group contamination")
    require(any(row["split"] == "future" for row in selected), "no future cohort")
    return selected


def validate_arm(rows, cohort, scope, task, cutoff):
    allowed = {row["case_id"]: row for row in cohort}
    result = {}
    for row in rows:
        case_id = row.get("case_id")
        require(type(case_id) is str and case_id in allowed and case_id not in result,
                "missing, extra or duplicate prediction case")
        expect = allowed[case_id]
        require(row.get("scope_id") == scope and row.get("task_id") == task,
                "scope/task prediction drift")
        require(row.get("split") == expect["split"], "prediction split drift")
        require(row.get("abstain") is False,
                "abstention not supported by this scoring profile")
        prob = row.get("probability_positive")
        require(type(prob) in (int, float) and 0 <= prob <= 1 and math.isfinite(prob),
                "invalid probability")
        for key in ("encoder_digest", "head_digest", "weights_digest"):
            require(type(row.get(key)) is str and bool(HEX64.fullmatch(row[key])),
                    "missing or invalid model digest: " + key)
        require(type(row.get("model_revision")) is str
                and bool(HEX40.fullmatch(row["model_revision"])),
                "unpinned model revision")
        require(type(row.get("runtime_generation")) is int
                and row["runtime_generation"] > 0, "missing runtime generation")
        require(type(row.get("execution_receipt_id")) is str
                and bool(row["execution_receipt_id"]),
                "missing declared execution receipt reference")
        commit = iso_utc(row.get("prediction_committed_at"))
        event = iso_utc(expect["event_time"])
        label = iso_utc(expect["label_available_at"])
        require(cutoff <= commit and event <= commit < label,
                "prediction timestamp not after event and before available label")
        require(type(row.get("latency_micros")) is int
                and row["latency_micros"] >= 0, "invalid claimed latency")
        resident = row.get("resident_bytes")
        transient = row.get("transient_bytes")
        if resident is None or transient is None:
            require(resident is None and transient is None,
                    "partial memory telemetry cannot be treated as measured")
            require(row.get("resource_observation") == "HEAD_ONLY_LATENCY_NO_RSS",
                    "missing provenance for unmeasured memory telemetry")
        else:
            require(type(resident) is int and resident >= 0
                    and type(transient) is int and transient >= 0,
                    "invalid claimed memory telemetry")
        result[case_id] = row
    require(set(result) == set(allowed), "prediction cohort incomplete")
    require(len({
        (x["model_revision"], x["encoder_digest"], x["head_digest"],
         x["weights_digest"], x["runtime_generation"])
        for x in result.values()
    }) == 1, "model/Head/generation drift within frozen evaluation arm")
    return result


def brier(label, p):
    return (p - label) ** 2


def score(rows, predictions):
    n = len(rows)
    return {
        "n": n,
        "brier": sum(
            brier(r["label"], predictions[r["case_id"]]["probability_positive"])
            for r in rows
        ) / n,
        "accuracy": sum(
            (predictions[r["case_id"]]["probability_positive"] >= 0.5) == bool(r["label"])
            for r in rows
        ) / n,
        "mean_latency_micros": sum(
            predictions[r["case_id"]]["latency_micros"] for r in rows
        ) / n,
        "max_resident_bytes_reported": (
            max(predictions[r["case_id"]]["resident_bytes"] for r in rows)
            if all(predictions[r["case_id"]]["resident_bytes"] is not None
                   for r in rows) else None
        ),
        "max_transient_bytes_reported": (
            max(predictions[r["case_id"]]["transient_bytes"] for r in rows)
            if all(predictions[r["case_id"]]["transient_bytes"] is not None
                   for r in rows) else None
        ),
        "resource_memory_measurement_complete": all(
            predictions[r["case_id"]]["resident_bytes"] is not None
            and predictions[r["case_id"]]["transient_bytes"] is not None
            for r in rows
        ),
        "resource_claims_independently_authenticated": False,
    }


def grouped_bootstrap(rows, base, candidate, rounds=500, seed=20261014):
    require(type(rounds) is int and 100 <= rounds <= 10000,
            "bootstrap repetitions out of range")
    groups = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(row)
    require(len(groups) >= 2, "at least two independent future groups required")
    rng = random.Random(seed)
    keys = sorted(groups)
    observed = sum(
        brier(r["label"], base[r["case_id"]]["probability_positive"])
        - brier(r["label"], candidate[r["case_id"]]["probability_positive"])
        for r in rows
    ) / len(rows)
    trials = []
    for _ in range(rounds):
        chosen = [r for k in (rng.choice(keys) for _ in keys) for r in groups[k]]
        trials.append(sum(
            brier(r["label"], base[r["case_id"]]["probability_positive"])
            - brier(r["label"], candidate[r["case_id"]]["probability_positive"])
            for r in chosen
        ) / len(chosen))
    trials.sort()
    return {
        "paired_brier_improvement": observed,
        "bootstrap_ci_lower": trials[int(.025 * (rounds - 1))],
        "bootstrap_ci_upper": trials[int(.975 * (rounds - 1))],
        "bootstrap_groups": len(keys),
        "bootstrap_repetitions": rounds,
        "bootstraps_are_descriptive_not_independently_authenticated": True,
    }


def compare(dataset, baseline, candidate, *, scope, task, cutoff, rounds=500):
    cutoff = iso_utc(cutoff)
    evaluated_at = datetime.now(timezone.utc)
    cohort = validate_dataset(dataset, scope, task, cutoff, evaluated_at)
    base = validate_arm(baseline, cohort, scope, task, cutoff)
    cand = validate_arm(candidate, cohort, scope, task, cutoff)
    by_split = {}
    for split in ("future", "ood", "old"):
        rows = [row for row in cohort if row["split"] == split]
        if rows:
            by_split[split] = {
                "no_change": score(rows, base), "candidate": score(rows, cand)
            }
    future = [row for row in cohort if row["split"] == "future"]
    paired = grouped_bootstrap(future, base, cand, rounds=rounds)
    return {
        "schema": SCHEMA,
        "status": "RETROSPECTIVE_SHADOW_EVIDENCE_INCOMPLETE",
        "authority": "DENY_ALL",
        "production_promotion_permitted": False,
        "winner_selected": False,
        "signed_execution_receipts_verified": False,
        "prediction_precommit_independently_verified": False,
        "label_release_time_independently_verified": False,
        "independent_ndu_verified": False,
        "target_host_resource_verified": False,
        "description": "Candidate minus no-change Brier improvement; never a promotion decision.",
        "scope_id": scope, "task_id": task,
        "training_cutoff_utc": cutoff.isoformat(),
        "splits": by_split,
        "future_paired": paired,
        "negative_transfer_old_tasks": (
            by_split["old"]["candidate"]["brier"]
            - by_split["old"]["no_change"]["brier"]
            if "old" in by_split else None
        ),
        "warning": "Timestamps, weights and receipt IDs are not independently authenticated.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for item in (
        "dataset", "no-change", "candidate", "scope", "task", "train-cutoff", "out"
    ):
        parser.add_argument("--" + item, required=True)
    parser.add_argument("--bootstrap-rounds", type=int, default=500)
    args = parser.parse_args(argv)
    try:
        result = compare(
            read_jsonl(args.dataset), read_jsonl(args.no_change),
            read_jsonl(args.candidate), scope=args.scope, task=args.task,
            cutoff=args.train_cutoff, rounds=args.bootstrap_rounds,
        )
        with Path(args.out).open("x", encoding="utf-8") as handle:
            json.dump(result, handle, sort_keys=True, indent=2)
            handle.write("\n")
    except (ValueError, OSError) as exc:
        print(f"E1 shadow evaluation failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote retrospective-only analysis to {args.out}; no model selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
