"""Four-arm HPCA Core x NDU research evidence audit; never owner authority.

This checker consumes *claims* about resource-complete held-out tasks; it does
not verify physical task delivery, owner signatures, or evaluator independence.
Every output retains HOLD_NO_GO even when numbers appear favorable.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from itertools import product
import json
import math
from typing import Any

SCHEMA = "hepta.hpca.factorial.shadow.v1"
ARMS = {"A": ("ordinary", False), "B": ("ordinary", True),
        "C": ("hepta", False), "D": ("hepta", True)}
CONTRASTS = {"B-A": ("B", "A"), "D-C": ("D", "C"),
             "D-B": ("D", "B")}
PRIMARY = ("B-A", "D-C", "D-B", "interaction")
FAMILIES = frozenset({"text", "multimodal", "correction", "prepare",
                      "stop", "retention"})
REGIMES = frozenset({"dense", "sparse"})
RESOURCE_FIELDS = ("wall_us", "cpu_us", "peak_rss_bytes", "api_calls",
                   "tokens_in", "tokens_out", "energy_millijoules")
CAP_FIELDS = ("wall_us", "cpu_us", "memory_bytes", "api_calls", "tokens",
              "feedback_bits", "train_updates")


class EvidenceError(ValueError):
    """Incomplete, mismatched or nonfinite evidence; no partial score."""


def _hash64(s: Any) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _finite(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _digest(obj: Any) -> str:
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def _signflip_positive_p(differences: list[float]) -> float | None:
    """Exact one-sided paired sign flip under symmetry, at most 16 seed clusters."""
    if not 2 <= len(differences) <= 16:
        return None
    observed = sum(differences)
    threshold = 1e-12 * max(1., sum(abs(x) for x in differences))
    extreme = 0
    for signs in product((-1., 1.), repeat=len(differences)):
        if sum(s * x for s, x in zip(signs, differences)) >= observed - threshold:
            extreme += 1
    return extreme / (1 << len(differences))


def _holm(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    """Holm correction over four predeclared primary contrasts only."""
    if any(x is None for x in pvalues.values()):
        return {k: None for k in pvalues}
    ordered = sorted(pvalues, key=lambda k: (pvalues[k], k))
    out: dict[str, float | None] = {}
    running = 0.
    for i, key in enumerate(ordered):
        running = max(running, min(1., (len(ordered) - i) * pvalues[key]))
        out[key] = running
    return {k: out[k] for k in pvalues}


def audit(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile frozen six-family x dense/sparse x four-cell evidence.

    Self-declared receipts and hashes are not independent owner attestation.
    """
    _require(isinstance(manifest, dict) and isinstance(rows, list), "invalid payload")
    _require(manifest.get("schema") == SCHEMA, "schema mismatch")
    _require(isinstance(manifest.get("source_sha"), str)
             and len(manifest["source_sha"]) == 40
             and all(c in "0123456789abcdef" for c in manifest["source_sha"]),
             "source commit not pinned")
    _require(isinstance(manifest.get("source_tree_sha"), str)
             and len(manifest["source_tree_sha"]) == 40
             and all(c in "0123456789abcdef" for c in manifest["source_tree_sha"]),
             "source tree not pinned")
    for k in ("evaluator_digest", "data_digest", "seed_assignment_digest",
              "training_contract_digest"):
        _require(_hash64(manifest.get(k)), f"missing frozen {k}")
    core_digests = manifest.get("core_arch_digests")
    _require(isinstance(core_digests, dict) and set(core_digests) == {"ordinary", "hepta"}
             and all(_hash64(v) for v in core_digests.values())
             and core_digests["ordinary"] != core_digests["hepta"],
             "missing distinct frozen core identities")
    seeds = manifest.get("seeds")
    _require(isinstance(seeds, list) and 2 <= len(seeds) <= 256
             and all(_nonnegative_int(s) for s in seeds) and len(set(seeds)) == len(seeds),
             "frozen seed roster missing or duplicated")
    _require(isinstance(manifest.get("families"), list)
             and all(isinstance(x, str) for x in manifest["families"])
             and set(manifest["families"]) == FAMILIES
             and len(manifest["families"]) == len(FAMILIES),
             "six task families must be frozen")
    _require(isinstance(manifest.get("regimes"), list)
             and all(isinstance(x, str) for x in manifest["regimes"])
             and set(manifest["regimes"]) == REGIMES
             and len(manifest["regimes"]) == len(REGIMES),
             "both sparse and dense feedback must be frozen")
    _require(_finite(manifest.get("practical_delta"))
             and manifest["practical_delta"] > 0
             and _finite(manifest.get("retention_floor"))
             and 0 <= manifest["retention_floor"] <= 1,
             "predeclared practical and retention thresholds required")
    _require(len(rows) == len(seeds) * len(FAMILIES) * len(REGIMES) * len(ARMS),
             "incomplete registered factorial roster")

    by_block: dict[tuple[int, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    receipt_ids: set[str] = set()
    for r in rows:
        _require(isinstance(r, dict), "row must be an object")
        seed, family, regime, arm = (r.get(k) for k in ("seed", "family", "regime", "arm"))
        _require(seed in seeds and family in FAMILIES and regime in REGIMES
                 and arm in ARMS and type(seed) is int,
                 "out-of-roster evaluation")
        _require(r.get("core") == ARMS[arm][0] and r.get("ndu") is ARMS[arm][1],
                 "core x controller cell mislabeled")
        _require(r.get("core_arch_digest") == core_digests[r["core"]]
                 and _hash64(r.get("trained_model_digest")),
                 "missing or mislabeled actual trained model identity")
        for k in ("task_a_digest", "task_b_digest", "task_c_digest", "result_receipt_digest"):
            _require(_hash64(r.get(k)), f"missing {k}")
        _require(len({r["task_a_digest"], r["task_b_digest"],
                      r["task_c_digest"]}) == 3,
                 "training A, evaluation B and next-task C must differ")
        _require(_nonnegative_int(r.get("train_end_sequence"))
                 and _positive_int(r.get("eval_start_sequence"))
                 and r["train_end_sequence"] < r["eval_start_sequence"],
                 "evaluation B must be later than training A")
        _require(isinstance(r.get("task_instance"), str) and r["task_instance"],
                 "missing held-out task instance")
        _require(isinstance(r.get("resource_caps"), dict)
                 and set(r["resource_caps"]) == set(CAP_FIELDS)
                 and all(_nonnegative_int(v) for v in r["resource_caps"].values()),
                 "complete numeric resource opportunity caps required")
        _require(isinstance(r.get("actual_resources"), dict)
                 and set(r["actual_resources"]) == set(RESOURCE_FIELDS)
                 and all(_nonnegative_int(v) for v in r["actual_resources"].values()),
                 "complete numeric actual cost accounting required")
        _require(_finite(r.get("gross_utility"))
                 and _finite(r.get("cost_utility")) and r["cost_utility"] >= 0,
                 "missing or nonfinite net utility inputs")
        _require(r.get("old_task_retention") is None
                 or (_finite(r["old_task_retention"])
                     and 0 <= r["old_task_retention"] <= 1),
                 "old task retention must be bounded or explicitly null")
        _require(_nonnegative_int(r.get("safety_failures"))
                 and type(r.get("timeout")) is bool,
                 "failure and timeout outcomes required")
        _require(r["result_receipt_digest"] not in receipt_ids,
                 "reused result receipt across cells")
        receipt_ids.add(r["result_receipt_digest"])
        key = (seed, family, regime)
        _require(arm not in by_block[key], "duplicate cell in paired block")
        by_block[key][arm] = r

    differences: dict[str, dict[int, list[float]]] = {
        k: defaultdict(list) for k in PRIMARY
    }
    stratified: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    retention_complete = True
    missing_retention = 0
    total_timeouts = total_safety_failures = 0
    retention_by_arm: dict[str, list[float]] = {a: [] for a in ARMS}
    failures_by_arm = {a: {"timeouts": 0, "safety_failures": 0} for a in ARMS}
    resources_per_arm: dict[str, dict[str, int]] = {
        a: {k: 0 for k in RESOURCE_FIELDS} for a in ARMS
    }
    for seed in seeds:
        for family in sorted(FAMILIES):
            for regime in sorted(REGIMES):
                block = by_block.get((seed, family, regime))
                _require(block is not None and set(block) == set(ARMS),
                         "missing member of frozen matched block")
                baseline = block["A"]
                for r in block.values():
                    _require(r["task_instance"] == baseline["task_instance"]
                             and all(r[k] == baseline[k] for k in
                                     ("task_a_digest", "task_b_digest", "task_c_digest"))
                             and r["resource_caps"] == baseline["resource_caps"],
                             "task identities or resource opportunities differ")
                net = {arm: r["gross_utility"] - r["cost_utility"]
                       for arm, r in block.items()}
                values = {name: net[high] - net[low]
                          for name, (high, low) in CONTRASTS.items()}
                values["interaction"] = values["D-C"] - values["B-A"]
                for name, value in values.items():
                    differences[name][seed].append(value)
                    stratified[f"{family}/{regime}"][name].append(value)
                for arm, r in block.items():
                    total_timeouts += int(r["timeout"])
                    total_safety_failures += r["safety_failures"]
                    failures_by_arm[arm]["timeouts"] += int(r["timeout"])
                    failures_by_arm[arm]["safety_failures"] += r["safety_failures"]
                    for resource, value in r["actual_resources"].items():
                        resources_per_arm[arm][resource] += value
                    if r["old_task_retention"] is None:
                        missing_retention += 1
                        retention_complete = False
                    else:
                        retention_by_arm[arm].append(r["old_task_retention"])

    clustered = {name: [sum(differences[name][s]) / len(differences[name][s])
                        for s in seeds] for name in PRIMARY}
    p = {name: _signflip_positive_p(x) for name, x in clustered.items()}
    corrected = _holm(p)
    report = {
        "schema": SCHEMA,
        "verdict": "HOLD_NO_GO",
        "authority": "DENY_ALL",
        "attestation": "UNVERIFIED_EXTERNAL_OWNER_AND_EVALUATOR",
        "source_sha": manifest["source_sha"],
        "source_tree_sha": manifest["source_tree_sha"],
        "registered_seeds": len(seeds),
        "paired_blocks": len(seeds) * len(FAMILIES) * len(REGIMES),
        "evaluated_rows": len(rows),
        "retention_complete": retention_complete,
        "missing_retention_rows": missing_retention,
        "timeouts": total_timeouts,
        "safety_failures": total_safety_failures,
        "failures_by_arm": failures_by_arm,
        "mean_old_retention_by_arm": {
            a: (sum(xs) / len(xs) if retention_complete else None)
            for a, xs in retention_by_arm.items()
        },
        "actual_resource_totals_by_arm": resources_per_arm,
        "retention_contrasts": (
            {"B-A": sum(retention_by_arm["B"]) / len(retention_by_arm["B"])
                     - sum(retention_by_arm["A"]) / len(retention_by_arm["A"]),
             "D-C": sum(retention_by_arm["D"]) / len(retention_by_arm["D"])
                     - sum(retention_by_arm["C"]) / len(retention_by_arm["C"]),
             "D-B": sum(retention_by_arm["D"]) / len(retention_by_arm["D"])
                     - sum(retention_by_arm["B"]) / len(retention_by_arm["B"]),
             "interaction": (sum(retention_by_arm["D"]) / len(retention_by_arm["D"])
                             - sum(retention_by_arm["C"]) / len(retention_by_arm["C"]))
                            - (sum(retention_by_arm["B"]) / len(retention_by_arm["B"])
                               - sum(retention_by_arm["A"]) / len(retention_by_arm["A"]))}
            if retention_complete else None
        ),
        "preregistered_practical_delta": manifest["practical_delta"],
        "preregistered_retention_floor": manifest["retention_floor"],
        "primary": {name: {
            "mean_net_difference": sum(clustered[name]) / len(seeds),
            "seed_cluster_differences": clustered[name],
            "one_sided_exact_signflip_p": p[name],
            "holm_four_primary_p": corrected[name],
        } for name in PRIMARY},
        "strata_descriptive_only": {
            strata: {name: sum(xs) / len(xs) for name, xs in mapping.items()}
            for strata, mapping in sorted(stratified.items())
        },
        "input_digest": _digest({
            "manifest": manifest,
            "rows": sorted(rows, key=lambda r:
                           (r["seed"], r["family"], r["regime"], r["arm"]))
        }),
        "interpretation": ("Full-roster self-consistency and seed-cluster diagnostic "
                           "statistics only; no real-world task, source attestation, "
                           "independent evaluator, selection, NextUse or cold recovery "
                           "has been verified by this code."),
    }
    return report
