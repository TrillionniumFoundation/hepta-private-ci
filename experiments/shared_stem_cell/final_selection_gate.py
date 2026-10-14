"""Shadow-only E1–E6 stem comparison over external paired future-NDU outcomes.

Neither checksum-shaped references nor caller-supplied metrics prove signature,
model execution, source independence or observer integrity. No production authority.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random

SCHEMA = "hepta.stem.e1-e6-selection.v1"
EXPERIMENTS = ("E1", "E2", "E3", "E4", "E5", "E6")
STEMS = ("mmbert-small", "granite-97m-r2", "modernbert-base", "mmbert-base")
BUDGETS = (2048, 8192, 16384, 65536, 262144)
SCALES = (64, 256, 1024, 4096)
COVERAGE = {
    "E1": STEMS,
    "E2": tuple(str(x) for x in BUDGETS),
    "E3": ("joint", "shared_feature_local_state"),
    "E4": ("v1", "v2", "v3", "diagonal_ssm", "low_rank_mingru"),
    "E5": ("text_stem_organ", "embeddinggemma-2"),
    "E6": tuple(str(x) for x in SCALES),
}


class InvalidEvidence(ValueError):
    """Reject malformed/unpaired observations rather than synthesize a result."""


def _check(ok: bool, why: str) -> None:
    if not ok:
        raise InvalidEvidence(why)


def _sha(value: object, n: int = 64) -> bool:
    return isinstance(value, str) and len(value) == n and all(c in "0123456789abcdef" for c in value)


def _finite(value: object, low: float, high: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _utc(value: object) -> datetime:
    _check(isinstance(value, str), "timestamp must be RFC3339")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _check(moment.tzinfo is not None and moment.utcoffset() is not None, "timestamp lacks timezone")
        return moment
    except ValueError as exc:
        raise InvalidEvidence("invalid timestamp") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _quantile(sorted_values: list[float], q: float) -> float:
    position = (len(sorted_values) - 1) * q
    lo = math.floor(position)
    hi = math.ceil(position)
    return sorted_values[lo] + (position - lo) * (sorted_values[hi] - sorted_values[lo])


def _bound(arm: dict, frozen_at: datetime) -> dict:
    _check(type(arm) is dict and set(arm) == {
        "id", "stem_id", "model_revision", "stem_sha256", "tokenizer_sha256",
        "head_sha256", "head_parameters", "seed", "training_steps", "frozen_encoder",
        "cases", "quality", "scales"
    }, "invalid arm contract")
    _check(isinstance(arm["id"], str) and 1 <= len(arm["id"]) <= 128, "invalid arm id")
    _check(_sha(arm["model_revision"], 40) and all(_sha(arm[k]) for k in (
        "stem_sha256", "tokenizer_sha256", "head_sha256")), "model/tokenizer/head not pinned")
    _check(arm["frozen_encoder"] is True, "encoder must be frozen")
    _check(type(arm["head_parameters"]) is int and 0 <= arm["head_parameters"] <= 262144,
           "head capacity outside preregistered ceilings")
    _check(type(arm["seed"]) is int and type(arm["training_steps"]) is int
           and arm["training_steps"] >= 0, "training budget not bound")
    rows = arm["cases"]
    _check(type(rows) is list and 1 <= len(rows) <= 100000, "bounded cases required")
    cases = {}
    for r in rows:
        _check(type(r) is dict and set(r) == {
            "case_id", "group_id", "window", "input_sha256", "observed_at",
            "status", "external_ndu", "old_task", "negative_transfer"
        }, "incomplete outcome")
        key = r["case_id"]
        _check(isinstance(key, str) and 1 <= len(key) <= 128 and key not in cases,
               "duplicate/invalid case id")
        _check(isinstance(r["group_id"], str) and 1 <= len(r["group_id"]) <= 128,
               "invalid source group")
        _check(r["window"] in ("future_1", "future_2") and _sha(r["input_sha256"]),
               "case must bind exact future input")
        _check(_utc(r["observed_at"]) > frozen_at, "future observation predates freeze")
        _check(r["status"] in ("ok", "failed", "abstain") and
               _finite(r["external_ndu"], -1000, 1000), "invalid external NDU outcome")
        _check(type(r["old_task"]) is bool and type(r["negative_transfer"]) is bool,
               "invalid retention flag")
        _check(not r["negative_transfer"] or r["old_task"], "negative transfer must refer to old task")
        _check(r["status"] == "ok" or r["external_ndu"] <= 0,
               "failed/abstained output cannot claim positive utility")
        cases[key] = r
    metrics = arm["quality"]
    _check(type(metrics) is dict and set(metrics) == {
        "brier", "ece", "ood_false_acceptance_rate", "old_task_regression"
    } and all(_finite(v, 0, 1) for v in metrics.values()), "invalid independent quality metrics")
    scale_map = {}
    _check(type(arm["scales"]) is list and len(arm["scales"]) == 4, "four physical scales required")
    for s in arm["scales"]:
        _check(type(s) is dict and set(s) == {
            "cells", "p95_ms", "p99_ms", "peak_rss_bytes", "gpu_peak_bytes",
            "recovery_ms", "wal_fsync_count"
        }, "incomplete host scale")
        n = s["cells"]
        _check(type(n) is int and n in SCALES and n not in scale_map, "scale duplication/gap")
        _check(all(_finite(s[k], 0, 1e12) for k in ("p95_ms", "p99_ms", "recovery_ms"))
               and s["p99_ms"] >= s["p95_ms"], "invalid host latency")
        _check(all(type(s[k]) is int and 0 <= s[k] <= 2**63-1 for k in (
            "peak_rss_bytes", "gpu_peak_bytes", "wal_fsync_count")), "invalid host counters")
        scale_map[n] = s
    _check(set(scale_map) == set(SCALES), "missing physical scale")
    return cases


def audit(bundle: dict) -> dict:
    """Compute an exploratory familywise-corrected paired future NDU screen."""
    _check(type(bundle) is dict and set(bundle) == {
        "schema", "origin", "protocol_sha256", "dataset_sha256", "host_profile_sha256",
        "observer_receipt_sha256", "freeze_at", "baseline", "registered_arms",
        "training_steps", "seed", "bootstrap_replicates", "min_future_groups",
        "limits", "coverage", "arms"
    } and bundle["schema"] == SCHEMA, "exact v1 input required")
    _check(bundle["origin"] in ("fixture", "measured"), "invalid evidence origin")
    _check(all(_sha(bundle[k]) for k in (
        "protocol_sha256", "dataset_sha256", "host_profile_sha256", "observer_receipt_sha256")),
           "unbound protocol/data/observer/host")
    frozen = _utc(bundle["freeze_at"])
    _check(type(bundle["seed"]) is int and type(bundle["training_steps"]) is int
           and bundle["training_steps"] > 0, "seed/steps missing")
    count = bundle["bootstrap_replicates"]
    _check(type(count) is int and 1000 <= count <= 10000, "bootstrap count out of bounds")
    min_groups = bundle["min_future_groups"]
    _check(type(min_groups) is int and 30 <= min_groups <= 10000, "insufficient group policy")
    lim = bundle["limits"]
    _check(type(lim) is dict and set(lim) == {
        "max_negative_transfer_rate", "max_old_task_regression", "max_brier_increase",
        "max_ece_increase", "max_ood_false_acceptance_rate", "max_p99_ms",
        "max_peak_rss_bytes", "max_gpu_peak_bytes", "max_recovery_ms"
    } and all(_finite(lim[k], 0, 1) for k in (
        "max_negative_transfer_rate", "max_old_task_regression", "max_brier_increase",
        "max_ece_increase", "max_ood_false_acceptance_rate"))
           and all(_finite(lim[k], 0, 1e15) for k in (
               "max_p99_ms", "max_peak_rss_bytes", "max_gpu_peak_bytes", "max_recovery_ms")),
           "invalid preregistered hard floors")
    arms = bundle["arms"]
    reg = bundle["registered_arms"]
    _check(type(reg) is list and 2 <= len(reg) <= 64 and all(isinstance(v, str) for v in reg)
           and len(set(reg)) == len(reg), "bounded fixed arm registry required")
    _check(type(arms) is list and len(arms) == len(reg) and
           {a.get("id") for a in arms if type(a) is dict} == set(reg),
           "all preregistered arms must be observed")
    _check(bundle["baseline"] in reg, "no-change arm missing")
    _check(type(bundle["coverage"]) is dict and set(bundle["coverage"]) == set(EXPERIMENTS),
           "E1..E6 completeness required")
    coverage_ok = True
    for k, required in COVERAGE.items():
        ev = bundle["coverage"][k]
        _check(type(ev) is dict and set(ev) == {"artifact_sha256", "status", "arms"},
               "experiment evidence schema missing")
        _check(_sha(ev["artifact_sha256"]) and ev["status"] in ("measured", "pending") and
               type(ev["arms"]) is list and all(isinstance(x, str) for x in ev["arms"]),
               "experiment evidence is malformed")
        if ev["status"] != "measured" or not set(required).issubset(set(ev["arms"])):
            coverage_ok = False
    case_sets = {}
    arms_by_name = {}
    seen_stems = set()
    for arm in arms:
        cases = _bound(arm, frozen)
        case_sets[arm["id"]] = cases
        arms_by_name[arm["id"]] = arm
        if arm["id"] != bundle["baseline"]:
            seen_stems.add(arm["stem_id"])
            _check(arm["stem_id"] in STEMS and arm["head_parameters"] in BUDGETS,
                   "unregistered Stem/Head ceiling")
            _check(arm["seed"] == bundle["seed"] and
                   arm["training_steps"] == bundle["training_steps"], "unfair training budget")
    baseline = arms_by_name[bundle["baseline"]]
    base = case_sets[bundle["baseline"]]
    _check(baseline["stem_id"] == "no_change", "baseline cannot substitute a new model")
    signatures = {key: (r["group_id"], r["window"], r["input_sha256"], r["observed_at"],
                         r["old_task"]) for key, r in base.items()}
    for key, cases in case_sets.items():
        _check({i: (r["group_id"], r["window"], r["input_sha256"], r["observed_at"],
                    r["old_task"]) for i, r in cases.items()} == signatures,
               f"unpaired future cases or cohort for {key}")
    all_groups = {r["group_id"] for r in base.values()}
    per_window = {w: {r["group_id"] for r in base.values() if r["window"] == w}
                  for w in ("future_1", "future_2")}
    ordered_windows = [
        [_utc(r["observed_at"]) for r in base.values() if r["window"] == window]
        for window in ("future_1", "future_2")
    ]
    _check(all(ordered_windows) and max(ordered_windows[0]) < min(ordered_windows[1]),
           "future windows are missing or not chronological")
    groups_ok = len(all_groups) >= min_groups and all(len(v) >= min_groups for v in per_window.values())
    arms_complete = set(STEMS).issubset(seen_stems)
    m = len(reg) - 1  # all registered comparisons, not the observed apparent winners
    alpha = .05 / (2 * m)  # familywise: registered candidates x two future windows
    result = {}
    for arm in arms:
        if arm["id"] == bundle["baseline"]:
            continue
        grouped: dict[str, list[float]] = {}
        window_groups: dict[str, dict[str, list[float]]] = {w: {} for w in ("future_1", "future_2")}
        old_window_groups: dict[str, dict[str, list[bool]]] = {w: {} for w in ("future_1", "future_2")}
        for case_id, r in case_sets[arm["id"]].items():
            delta = r["external_ndu"] - base[case_id]["external_ndu"]
            grouped.setdefault(r["group_id"], []).append(delta)
            window_groups[r["window"]].setdefault(r["group_id"], []).append(delta)
            if r["old_task"]:
                old_window_groups[r["window"]].setdefault(r["group_id"], []).append(
                    r["negative_transfer"])
        group_means = [sum(values) / len(values) for _, values in sorted(grouped.items())]
        window_stats = {}
        for window in ("future_1", "future_2"):
            values = [sum(v) / len(v) for _, v in sorted(window_groups[window].items())]
            rng = random.Random(f'{bundle["seed"]}-{arm["id"]}-{window}')
            bootstrap = sorted(sum(values[rng.randrange(len(values))] for _ in range(len(values)))
                               / len(values) for _ in range(count))
            old = old_window_groups[window]
            old_rate = (sum(sum(v) / len(v) for v in old.values()) / len(old)
                        if old else None)
            window_stats[window] = {
                "delta_ndu_group_mean": sum(values) / len(values),
                "delta_ndu_lcb_familywise": _quantile(bootstrap, alpha),
                "negative_transfer_rate": old_rate,
                "source_groups_reported": len(values),
            }
        lcb = min(v["delta_ndu_lcb_familywise"] for v in window_stats.values())
        transfer_rates = [v["negative_transfer_rate"] for v in window_stats.values()]
        transfer_rate = max(transfer_rates) if all(v is not None for v in transfer_rates) else None
        quality = arm["quality"]
        bq = baseline["quality"]
        quality_ok = transfer_rate is not None and transfer_rate <= lim["max_negative_transfer_rate"] and (
            quality["brier"] - bq["brier"] <= lim["max_brier_increase"] and
            quality["ece"] - bq["ece"] <= lim["max_ece_increase"] and
            quality["ood_false_acceptance_rate"] <= lim["max_ood_false_acceptance_rate"] and
            quality["old_task_regression"] <= lim["max_old_task_regression"])
        resource_ok = all(
            s["p99_ms"] <= lim["max_p99_ms"] and
            s["peak_rss_bytes"] <= lim["max_peak_rss_bytes"] and
            s["gpu_peak_bytes"] <= lim["max_gpu_peak_bytes"] and
            s["recovery_ms"] <= lim["max_recovery_ms"]
            for s in arm["scales"])
        eligible = (bundle["origin"] == "measured" and coverage_ok and
                    arms_complete and groups_ok and quality_ok and resource_ok and lcb > 0)
        result[arm["id"]] = {
            "delta_ndu_group_mean": sum(group_means) / len(group_means),
            "delta_ndu_lcb_familywise": lcb,
            "future_window_bounds": window_stats,
            "adjusted_one_sided_alpha": alpha,
            "source_groups_reported": len(group_means),
            "negative_transfer_rate": transfer_rate,
            "e1_e6_coverage_claimed": coverage_ok and arms_complete,
            "minimum_future_groups_reported": groups_ok,
            "quality_floors_reported": quality_ok,
            "physical_resource_floors_reported": resource_ok,
            "provisional_research_eligible": eligible,
        }
    ranked = sorted((name for name, v in result.items() if v["provisional_research_eligible"]),
                    key=lambda k: (-result[k]["delta_ndu_lcb_familywise"], k))
    return {
        "schema": "hepta.stem.e1-e6-selection-receipt.v1",
        "bundle_sha256": _digest(bundle), "baseline": bundle["baseline"],
        "provisional_research_leader": ranked[0] if ranked else None,
        "arms": result,
        "independent_source_groups_verified": False,
        "external_observer_signature_verified": False,
        "real_model_execution_independently_verified": False,
        "target_host_attestation_verified": False,
        "production_accepted": False,
        "model_selection_authority": False,
        "preregistration_authenticity_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.bundle.read_text(encoding="utf-8"))
    answer = audit(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(answer, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
