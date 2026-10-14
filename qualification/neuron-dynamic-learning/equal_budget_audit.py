"""Read-only paired Laya / shared-Stem equal-budget evidence audit.

All inputs are externally observed, immutable-evidence *claims*. This module
checks comparability and estimates task statistics; it does not authenticate
receipts, mint success labels, run model weights, or grant production use.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import random

SPLITS = ("test", "future1", "future2", "future3")
MAX_CASES = 4096
MAX_ARMS = 12
MIN_PER_WINDOW = 8
BOOTSTRAPS = 1000


class AuditError(ValueError):
    """Unsupported, leaked or incomparable experiment evidence."""


def _sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise AuditError("UTC event time required")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
            raise ValueError("non-UTC")
        return instant
    except ValueError as exc:
        raise AuditError("invalid UTC source/observation time") from exc


def _probability(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1:
        raise AuditError("finite non-degenerate binary probability required")
    return float(value)


def _positive(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise AuditError("strictly positive measured cost required")
    return float(value)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def validate_panel(panel: dict) -> dict:
    """Validate fixed comparable task windows and complete per-case paired rows."""
    if not isinstance(panel, dict) or set(panel) != {
        "schema", "plan_digest", "frozen_before_utc", "scope_id", "host_profile_digest",
        "baseline_arm", "arms", "lifecycle_cost_units", "cases",
    } or panel["schema"] != "hepta.stem.equal-budget-paired.v1":
        raise AuditError("unknown or incomplete preregistered panel")
    if not _sha(panel["plan_digest"]) or not _sha(panel["host_profile_digest"]):
        raise AuditError("missing plan or matched host identity")
    freeze_time = _utc(panel["frozen_before_utc"])
    if not isinstance(panel["scope_id"], str) or not panel["scope_id"]:
        raise AuditError("scope identity required")
    arms = panel["arms"]
    if not isinstance(arms, list) or not 2 <= len(arms) <= MAX_ARMS:
        raise AuditError("two or more independently identified arms required")
    ids = []
    for arm in arms:
        if (not isinstance(arm, dict) or set(arm) != {"arm_id", "model_digest", "policy_digest"}
                or not isinstance(arm["arm_id"], str) or not arm["arm_id"]
                or any(not _sha(arm[k]) for k in ("model_digest", "policy_digest"))):
            raise AuditError("unbound comparison arm")
        ids.append(arm["arm_id"])
    if len(set(ids)) != len(ids) or panel["baseline_arm"] not in ids:
        raise AuditError("repeated arm or absent exact baseline")
    lifecycle_costs = panel["lifecycle_cost_units"]
    required_lifecycle = {"training", "evaluation", "migration", "storage", "source_read"}
    if not isinstance(lifecycle_costs, dict) or set(lifecycle_costs) != set(ids):
        raise AuditError("lifecycle costs must cover every registered arm")
    for arm in ids:
        detail = lifecycle_costs[arm]
        if not isinstance(detail, dict) or set(detail) != required_lifecycle:
            raise AuditError("incomplete matched total-cost breakdown")
        for value in detail.values():
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise AuditError("invalid measured lifecycle cost")
    cases = panel["cases"]
    if not isinstance(cases, list) or not 4 * MIN_PER_WINDOW <= len(cases) <= MAX_CASES:
        raise AuditError("missing four independently observed windows")
    by_window = {split: [] for split in SPLITS}
    seen_cases, group_split, source_split = set(), {}, {}
    for row in cases:
        if not isinstance(row, dict) or set(row) != {
            "case_id", "group_id", "split", "observed_utc", "scope_id", "source_digest",
            "outcome_receipt_digest", "truth", "predictions",
        }:
            raise AuditError("incomplete owner-originated case evidence")
        cid, group, split = row["case_id"], row["group_id"], row["split"]
        if (not isinstance(cid, str) or not cid or cid in seen_cases
                or not isinstance(group, str) or not group or split not in SPLITS
                or row["scope_id"] != panel["scope_id"]
                or any(not _sha(row[k]) for k in ("source_digest", "outcome_receipt_digest"))
                or type(row["truth"]) is not int or row["truth"] not in (0, 1)):
            raise AuditError("duplicate, unscoped, unsigned or improperly labelled case")
        seen_cases.add(cid)
        when = _utc(row["observed_utc"])
        if when <= freeze_time:
            raise AuditError("all evaluated episodes must follow plan freeze")
        for key, seen in ((group, group_split), (row["source_digest"], source_split)):
            if seen.setdefault(key, split) != split:
                raise AuditError("group or exact source leaked across future windows")
        preds = row["predictions"]
        if not isinstance(preds, list) or len(preds) != len(ids):
            raise AuditError("all arms must predict the same complete task panel")
        observed_arms = set()
        for p in preds:
            if not isinstance(p, dict) or set(p) != {
                "arm_id", "probability", "prediction_receipt_digest", "observed_cost_units",
                "measured_latency_micros", "trained_parameter_count",
            } or p["arm_id"] not in ids or p["arm_id"] in observed_arms:
                raise AuditError("missing or duplicate paired arm result")
            observed_arms.add(p["arm_id"])
            _probability(p["probability"])
            _positive(p["observed_cost_units"])
            if (not _sha(p["prediction_receipt_digest"])
                    or type(p["measured_latency_micros"]) is not int
                    or p["measured_latency_micros"] <= 0
                    or type(p["trained_parameter_count"]) is not int
                    or p["trained_parameter_count"] < 0):
                raise AuditError("unmeasured resource or unsigned model prediction")
        by_window[split].append((row, when))
    for name, rows in by_window.items():
        if len(rows) < MIN_PER_WINDOW or len({x["group_id"] for x, _ in rows}) < 2:
            raise AuditError(f"insufficient independent samples in {name}")
    for older, newer in zip(SPLITS, SPLITS[1:]):
        if max(t for _, t in by_window[older]) >= min(t for _, t in by_window[newer]):
            raise AuditError("future windows are not strictly time ordered")
    return {"ids": ids, "by_window": by_window,
            "dataset_digest": hashlib.sha256(_canonical(panel)).hexdigest(),
            "independent_groups": len(group_split)}


def _brier(p: float, y: int) -> float:
    return (p - y) ** 2


def _bootstrap_lcb(group_differences: dict, *, seed: int) -> float:
    """Cluster-level paired 5th percentile, not an observation-unit CI."""
    keys = sorted(group_differences)
    if len(keys) < 8:
        raise AuditError("at least eight independent future groups required for CI")
    rng = random.Random(seed)
    draws = []
    for _ in range(BOOTSTRAPS):
        sampled = [group_differences[keys[rng.randrange(len(keys))]] for _ in keys]
        draws.append(sum(sampled) / len(sampled))
    draws.sort()
    return draws[int(0.05 * BOOTSTRAPS)]


def evaluate_panel(panel: dict) -> dict:
    checked = validate_panel(panel)
    ids, baseline = checked["ids"], panel["baseline_arm"]
    scored = []
    group_values = defaultdict(lambda: defaultdict(list))
    windows = {}
    for split in SPLITS:
        rows = [r for r, _ in checked["by_window"][split]]
        sums = {arm: {"brier": 0.0, "cost": 0.0, "latency": []} for arm in ids}
        for r in rows:
            by_arm = {p["arm_id"]: p for p in r["predictions"]}
            y = r["truth"]
            b = _brier(_probability(by_arm[baseline]["probability"]), y)
            for arm in ids:
                p = by_arm[arm]
                loss = _brier(_probability(p["probability"]), y)
                sums[arm]["brier"] += loss
                sums[arm]["cost"] += float(p["observed_cost_units"])
                sums[arm]["latency"].append(p["measured_latency_micros"])
                if arm != baseline and split.startswith("future"):
                    group_values[arm][(split, r["group_id"])].append(b - loss)
        windows[split] = {
            arm: {"cases": len(rows), "brier": sums[arm]["brier"] / len(rows),
                  "cost_units": sums[arm]["cost"],
                  "p95_latency_micros": sorted(sums[arm]["latency"])[math.ceil(0.95 * len(rows)) - 1]}
            for arm in ids
        }
    for arm in ids:
        if arm == baseline:
            continue
        gains = {key: sum(values) / len(values) for key, values in group_values[arm].items()}
        future_cost_arm = sum(windows[sp][arm]["cost_units"] for sp in SPLITS[1:])
        future_cost_base = sum(windows[sp][baseline]["cost_units"] for sp in SPLITS[1:])
        # Count training, evaluation, storage, migration and source reread as well.
        cost_arm = future_cost_arm + sum(float(x) for x in panel["lifecycle_cost_units"][arm].values())
        cost_base = future_cost_base + sum(float(x) for x in panel["lifecycle_cost_units"][baseline].values())
        cost_ratio = cost_arm / cost_base
        per_future_gain = {
            sp: windows[sp][baseline]["brier"] - windows[sp][arm]["brier"]
            for sp in SPLITS[1:]
        }
        lcb = _bootstrap_lcb(gains, seed=int(checked["dataset_digest"][:12], 16))
        scored.append({"arm_id": arm, "future_group_gain_lcb95": lcb,
                       "matched_lifecycle_cost_ratio": cost_ratio,
                       "per_future_window_brier_gain": per_future_gain,
                       "passes_statistical_cost_screen": (
                           lcb > 0 and cost_ratio <= 1.0
                           and all(gain > 0 for gain in per_future_gain.values())
                       ),
                       "independent_source_attestation": False,
                       "model_execution_independently_verified": False,
                       "selection_authority": "DENY_ALL"})
    return {"schema": "hepta.stem.equal-budget-report.v1", "baseline_arm": baseline,
            "evidence_type": "self_reported_pairing_statistic_not_independent_outcome",
            "dataset_digest": checked["dataset_digest"],
            "independent_groups": checked["independent_groups"],
            "windows": windows, "comparisons": scored,
            "production_promotion": "DENY_ALL"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_panel(json.loads(args.panel.read_text(encoding="utf-8"))),
                     sort_keys=True, ensure_ascii=False))
