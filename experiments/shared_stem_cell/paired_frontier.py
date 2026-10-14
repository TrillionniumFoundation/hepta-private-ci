"""Source-paired resource/retention frontier for actual Stem/Cell executions.

This audits externally sealed observations; it does NOT generate model outcomes,
manufacture missing energy/FLOPs, certify observer independence, or choose a
production model. Never use fixture measurements as real resource receipts.
"""
from __future__ import annotations

import hashlib
import json
import math

MIN_INDEPENDENT_GROUPS = 200
METRICS = ("resident_model_bytes", "peak_rss_bytes", "total_active_flops",
           "total_wall_ns", "energy_joules")


class InvalidFrontier(ValueError):
    pass


def _sha(v):
    return type(v) is str and len(v) == 64 and all(x in "0123456789abcdef" for x in v)


def _name(v):
    return type(v) is str and 1 <= len(v) <= 128


def _int(v, label, *, nullable=False):
    if v is None and nullable:
        return
    if type(v) is not int or not 0 <= v <= 2**63 - 1:
        raise InvalidFrontier(f"invalid measured {label}")


def _energy(v):
    if v is not None and (type(v) not in (float, int) or not math.isfinite(v) or v < 0):
        raise InvalidFrontier("invalid actual energy observation")


def _digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def audit(campaign, *, baseline):
    if type(campaign) is not dict or set(campaign) != {
        "schema", "objective_sha256", "source_sha256", "observer_receipt_sha256",
        "host_profile_sha256", "arms"
    } or campaign["schema"] != "hepta.stem.paired-physical-frontier.v1":
        raise InvalidFrontier("versioned exact paired campaign required")
    for k in ("objective_sha256", "source_sha256", "observer_receipt_sha256", "host_profile_sha256"):
        if not _sha(campaign[k]):
            raise InvalidFrontier(f"invalid {k} reference")
    arms = campaign["arms"]
    if type(arms) is not list or not 2 <= len(arms) <= 16:
        raise InvalidFrontier("2..16 observed arms required")
    details, canonical_cases, names = {}, None, set()
    for arm in arms:
        if type(arm) is not dict or set(arm) != {
            "name", "model_sha256", "stem_sha256", "scope", "isolated_process",
            "resident_model_bytes", "peak_rss_bytes", "train_active_flops",
            "train_wall_ns", "energy_joules", "encoder_forward_calls", "outcomes"
        }:
            raise InvalidFrontier("incomplete actual arm measurement")
        name = arm["name"]
        if not _name(name) or name in names or not _name(arm["scope"]):
            raise InvalidFrontier("arm identity/scope collision")
        names.add(name)
        for k in ("model_sha256", "stem_sha256"):
            if not _sha(arm[k]):
                raise InvalidFrontier("unbound model/Stem")
        if arm["isolated_process"] is not True:
            raise InvalidFrontier("physical peak requires separate per-arm process")
        for key in ("resident_model_bytes", "peak_rss_bytes",
                    "train_active_flops", "train_wall_ns", "encoder_forward_calls"):
            _int(arm[key], key, nullable=key not in ("resident_model_bytes",))
        _energy(arm["energy_joules"])
        rows = arm["outcomes"]
        if type(rows) is not list or not 1 <= len(rows) <= 100_000:
            raise InvalidFrontier("complete bounded task rows required")
        normalized, successes, group_success = {}, 0, {}
        inference_flops, inference_wall, groups = 0, 0, {}
        has_all_flops = True
        for row in rows:
            if type(row) is not dict or set(row) != {
                "case_id", "group", "input_sha256", "status", "correct", "active_flops",
                "wall_ns"
            }:
                raise InvalidFrontier("incomplete per-task observations")
            key, group = row["case_id"], row["group"]
            if not _name(key) or not _name(group) or key in normalized or not _sha(row["input_sha256"]):
                raise InvalidFrontier("missing/duplicate task/source identity")
            if row["status"] not in ("ok", "failed", "abstain") or type(row["correct"]) is not bool:
                raise InvalidFrontier("invalid result classification")
            if row["status"] != "ok" and row["correct"]:
                raise InvalidFrontier("failed or abstained case counted correct")
            _int(row["active_flops"], "task FLOPs", nullable=True)
            _int(row["wall_ns"], "task elapsed time")
            if row["active_flops"] is None:
                has_all_flops = False
            else:
                inference_flops += row["active_flops"]
            inference_wall += row["wall_ns"]
            normalized[key] = (group, row["input_sha256"], row["correct"])
            group_success[group] = group_success.get(group, 0) + int(row["correct"])
            groups.setdefault(group, []).append(key)
            successes += int(row["correct"])
        if arm["encoder_forward_calls"] is not None and arm["encoder_forward_calls"] > len(rows):
            raise InvalidFrontier("impossible encoder forward count")
        source = {key: (group, inp) for key, (group, inp, _) in normalized.items()}
        if canonical_cases is None:
            canonical_cases = source
        elif canonical_cases != source:
            raise InvalidFrontier("nonpaired task, input or source group across arms")
        total_flops = (arm["train_active_flops"] + inference_flops
                       if arm["train_active_flops"] is not None and has_all_flops else None)
        total_wall = arm["train_wall_ns"] + inference_wall if arm["train_wall_ns"] is not None else None
        sorted_wall = sorted(row["wall_ns"] for row in rows)
        p99 = sorted_wall[math.ceil(len(sorted_wall) * .99) - 1]
        details[name] = {
            "cases": len(rows), "source_groups": len(groups), "correct": successes,
            "group_correct": group_success, "outcomes": normalized,
            "resident_model_bytes": arm["resident_model_bytes"],
            "peak_rss_bytes": arm["peak_rss_bytes"],
            "total_active_flops": total_flops, "total_wall_ns": total_wall,
            "p99_task_wall_ns": p99, "energy_joules": arm["energy_joules"],
            "encoder_forward_calls": arm["encoder_forward_calls"],
            "unique_input_count": len({x[1] for x in normalized.values()}),
            "failures_or_abstentions": sum(row["status"] != "ok" for row in rows),
        }
    if baseline not in details:
        raise InvalidFrontier("registered baseline missing")
    control, comparisons = details[baseline], {}
    for name, candidate in details.items():
        quality = all(candidate["group_correct"][g] >= count
                      for g, count in control["group_correct"].items())
        gains = {}
        for metric in METRICS:
            a, b = candidate[metric], control[metric]
            gains[metric] = None if a is None or b is None else b - a
        complete = all(v is not None for v in gains.values())
        strict_physical = complete and quality and all(v >= 0 for v in gains.values()) and any(
            v > 0 for v in gains.values())
        comparisons[name] = {
            "empirical_group_nonregression": quality,
            "resource_deltas_vs_baseline": gains,
            "complete_physical_counters": complete,
            "strict_paired_pareto": strict_physical,
            "effective_independent_groups_certified": False,
            "full_promotion_qualified": False,
        }
    return {
        "schema": "hepta.stem.paired-physical-frontier-receipt.v1",
        "campaign_sha256": _digest(campaign), "baseline": baseline,
        "observations": {k: {key: value for key, value in row.items()
                             if key not in ("outcomes", "group_correct")}
                         for k, row in details.items()},
        "comparisons": comparisons, "actual_independent_source_groups_unverified": True,
        "minimum_independent_groups_policy": MIN_INDEPENDENT_GROUPS,
        "external_observer_authenticity_verified": False,
        "input_source_independence_verified": False, "production_accepted": False,
    }
