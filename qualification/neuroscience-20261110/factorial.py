#!/usr/bin/env python3
"""Strict, shadow-only 2x2 Core x NDU paired research-evidence preflight.

This code performs *no* tasks, training, effect verification, owner attestation,
model selection, or adoption. Digest strings and independence flags are
self-declared; an analysis result cannot confer deployment authority.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path
from typing import Iterable

ARMS = ("A", "B", "C", "D")
# Fixed a priori contrasts in the order required by the research protocol.
CONTRASTS = {
    "B_minus_A": {"B": 1, "A": -1},
    "D_minus_C": {"D": 1, "C": -1},
    "D_minus_B": {"D": 1, "B": -1},
    "interaction": {"D": 1, "C": -1, "B": -1, "A": 1},
}
SCHEMA = "hepta.neuroscience.factorial-shadow.v1"


class FactorialContractError(ValueError):
    """A missing or inconsistent research contract, not a failed model."""


def _hash_ok(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(
        letter in "0123456789abcdef" for letter in value
    )


def _finite(value: object) -> bool:
    if type(value) not in (float, int):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FactorialRow:
    episode_id: str
    seed: int
    family: str
    arm: str                 # A ordinary, B ordinary+NDU, C Hepta, D Hepta+NDU
    workload_digest: str    # exact future task, not a training task
    train_data_digest: str  # locked training A and its separation from future B
    evaluator_digest: str   # frozen independent prospective evaluator declaration
    capacity_contract_digest: str  # explicit capacity and baseline opportunity contract
    core_model_digest: str
    controller_digest: str
    feedback_contract_digest: str  # dense/sparse schedule and information budget
    outcome_receipt_digest: str
    query_budget: int
    training_budget: int
    compute_budget_us: int
    feedback_budget_bits: int
    gross_value: float | None       # never impute missing outcomes as zero
    full_cost: float | None         # same declared utility units as gross_value
    retention_value: float | None  # old-task score, never impute null
    wall_time_us: int | None
    cpu_time_us: int | None
    gpu_time_us: int | None
    failed_actions: int | None
    evaluator_independent: bool     # declaration, NOT independently validated


def _valid_row(r: FactorialRow) -> None:
    if (type(r.episode_id) is not str or not r.episode_id
            or type(r.family) is not str or not r.family or r.arm not in ARMS
            or type(r.seed) is not int or r.seed < 0
            or type(r.evaluator_independent) is not bool
            or not all(_hash_ok(v) for v in (
                r.workload_digest, r.train_data_digest, r.evaluator_digest,
                r.capacity_contract_digest, r.core_model_digest,
                r.controller_digest, r.feedback_contract_digest,
                r.outcome_receipt_digest))
            or any(type(v) is not int or v < 0 for v in (
                r.query_budget, r.training_budget, r.compute_budget_us,
                r.feedback_budget_bits))):
        raise FactorialContractError("invalid identity, digest or opportunity budget")
    for metric in (r.gross_value, r.full_cost, r.retention_value):
        if metric is not None and not _finite(metric):
            raise FactorialContractError("invalid non-finite outcome or cost")
    if r.full_cost is not None and r.full_cost < 0:
        raise FactorialContractError("negative realized full cost")
    for measured in (r.wall_time_us, r.cpu_time_us, r.gpu_time_us, r.failed_actions):
        if measured is not None and (type(measured) is not int or measured < 0):
            raise FactorialContractError("invalid actual resource observation")


def _contrast(values: dict[str, float], weights: dict[str, int]) -> float:
    return sum(values[arm] * weight for arm, weight in weights.items())


def _signflip_p(values: list[float]) -> float | None:
    """One-sided exploratory exact sign flip; cluster is the training seed."""
    if not values or len(values) > 16:
        return None
    observed = sum(values)
    count = sum(1 for signs in product((-1, 1), repeat=len(values))
                if sum(x * sign for x, sign in zip(values, signs)) >= observed - 1e-12)
    return count / (1 << len(values))


def _holm_p(values: dict[str, float | None]) -> dict[str, float | None]:
    """Holm adjusted p under arbitrary test dependence, conditional on valid raw p."""
    if any(v is None for v in values.values()):
        return {key: None for key in values}
    ordered = sorted(values, key=lambda key: (values[key], key))
    previous = 0.0
    adjusted = {}
    for pos, key in enumerate(ordered):
        previous = max(previous, (len(ordered) - pos) * values[key])
        adjusted[key] = min(1.0, previous)
    return {key: adjusted[key] for key in values}


def factorial_evidence(rows: Iterable[FactorialRow]) -> dict:
    """Audit a complete factorial panel; no scientific/production pass is possible.

    Resource *budgets* and identity strings are checked for consistency, not
    actual equality of compute or real ownership. Missing realized outcomes
    withhold all inferential statistics instead of dropping unfavorable arms.
    A seed occurring in many tasks/families remains one randomization unit.
    """
    data = list(rows)
    if not data or len(data) > 400_000:
        raise FactorialContractError("empty or oversized factorial panel")
    blocks: dict[tuple[str, int, str], dict[str, FactorialRow]] = {}
    seen_receipts: set[str] = set()
    for row in data:
        if not isinstance(row, FactorialRow):
            raise FactorialContractError("expected typed FactorialRow")
        _valid_row(row)
        if row.outcome_receipt_digest in seen_receipts:
            raise FactorialContractError("reused outcome receipt")
        seen_receipts.add(row.outcome_receipt_digest)
        block = blocks.setdefault((row.episode_id, row.seed, row.family), {})
        if row.arm in block:
            raise FactorialContractError("duplicate arm in paired block")
        block[row.arm] = row
    # Hold a model/evaluator cohort fixed per seed and arm across families.
    # Different family-specific tasks/feedback are intentionally allowed.
    cohort_by_seed_arm: dict[tuple[int, str], tuple[str, ...]] = {}
    family_roster_by_seed: dict[int, dict[str, int]] = {}
    for (_, seed, family), block in blocks.items():
        counts = family_roster_by_seed.setdefault(seed, {})
        counts[family] = counts.get(family, 0) + 1
        for arm, row in block.items():
            if row.train_data_digest == row.workload_digest:
                raise FactorialContractError(
                    "identical training and future-task digests: disjointness violated")
            lock = (row.train_data_digest, row.evaluator_digest,
                    row.capacity_contract_digest, row.core_model_digest,
                    row.controller_digest)
            key = (seed, arm)
            if key in cohort_by_seed_arm and cohort_by_seed_arm[key] != lock:
                raise FactorialContractError(
                    "frozen per-seed model/evaluator/cohort identity drift across families")
            cohort_by_seed_arm[key] = lock
    if len({tuple(sorted(counts.items())) for counts
            in family_roster_by_seed.values()}) != 1:
        raise FactorialContractError(
            "unequal family/episode roster across training seed clusters")

    seed_contrasts: dict[str, dict[int, list[float]]] = {
        name: {} for name in CONTRASTS
    }
    seed_costs: dict[str, dict[int, list[float]]] = {
        name: {} for name in CONTRASTS
    }
    seed_retention: dict[str, dict[int, list[float]]] = {
        name: {} for name in CONTRASTS
    }
    family_seed_net: dict[str, dict[str, dict[int, list[float]]]] = {}
    family_seed_cost: dict[str, dict[str, dict[int, list[float]]]] = {}
    family_seed_retention: dict[str, dict[str, dict[int, list[float]]]] = {}
    actual_by_arm: dict[str, dict[str, list[int]]] = {
        arm: {name: [] for name in (
            "wall_time_us", "cpu_time_us", "gpu_time_us", "failed_actions")}
        for arm in ARMS
    }
    missing_outcome_blocks = 0
    missing_retention_blocks = 0
    missing_resource_blocks = 0
    all_independence_declared = True
    for (episode, seed, family), block in blocks.items():
        if set(block) != set(ARMS):
            raise FactorialContractError("missing Core x NDU arm")
        a, b, c, d = (block[arm] for arm in ARMS)
        fixed = (
            "workload_digest", "train_data_digest", "evaluator_digest",
            "capacity_contract_digest", "feedback_contract_digest",
            "query_budget", "training_budget", "compute_budget_us",
            "feedback_budget_bits",
        )
        if any(getattr(row, field) != getattr(a, field)
               for row in block.values() for field in fixed):
            raise FactorialContractError("unequal future task, evaluator, data or opportunity")
        if not (a.core_model_digest == b.core_model_digest
                and c.core_model_digest == d.core_model_digest
                and a.core_model_digest != c.core_model_digest):
            raise FactorialContractError("core model identity not locked within controller arms")
        if not (a.controller_digest == c.controller_digest
                and b.controller_digest == d.controller_digest
                and a.controller_digest != b.controller_digest):
            raise FactorialContractError("controller identity not locked across cores")
        all_independence_declared &= all(row.evaluator_independent for row in block.values())
        resource_names = ("wall_time_us", "cpu_time_us", "gpu_time_us", "failed_actions")
        for arm, row in block.items():
            for name in resource_names:
                if getattr(row, name) is not None:
                    actual_by_arm[arm][name].append(getattr(row, name))
        if any(getattr(row, name) is None for row in block.values()
               for name in resource_names):
            missing_resource_blocks += 1
        if any(row.gross_value is None or row.full_cost is None for row in block.values()):
            missing_outcome_blocks += 1
        else:
            net = {arm: row.gross_value - row.full_cost for arm, row in block.items()}
            costs = {arm: row.full_cost for arm, row in block.items()}
            for name, weights in CONTRASTS.items():
                seed_contrasts[name].setdefault(seed, []).append(_contrast(net, weights))
                family_seed_net.setdefault(family, {}).setdefault(
                    name, {}).setdefault(seed, []).append(_contrast(net, weights))
                family_seed_cost.setdefault(family, {}).setdefault(
                    name, {}).setdefault(seed, []).append(_contrast(costs, weights))
                seed_costs[name].setdefault(seed, []).append(_contrast(costs, weights))
        if any(row.retention_value is None for row in block.values()):
            missing_retention_blocks += 1
        else:
            retention = {arm: row.retention_value for arm, row in block.items()}
            for name, weights in CONTRASTS.items():
                family_seed_retention.setdefault(family, {}).setdefault(
                    name, {}).setdefault(seed, []).append(_contrast(retention, weights))
                seed_retention[name].setdefault(seed, []).append(_contrast(retention, weights))

    # Conservative complete-case gate: no conditioning on observed outcomes.
    outcomes_complete = missing_outcome_blocks == 0
    retention_complete = missing_retention_blocks == 0
    resource_complete = missing_resource_blocks == 0
    contrasts = {}
    raw_p = {}
    for name in CONTRASTS:
        differences = ([sum(sample) / len(sample) for _, sample in
                        sorted(seed_contrasts[name].items())] if outcomes_complete else [])
        costs = ([sum(sample) / len(sample) for _, sample in
                  sorted(seed_costs[name].items())] if outcomes_complete else [])
        retentions = ([sum(sample) / len(sample) for _, sample in
                       sorted(seed_retention[name].items())] if retention_complete else [])
        raw_p[name] = _signflip_p(differences) if outcomes_complete else None
        contrasts[name] = {
            "mean_net_delta": sum(differences) / len(differences) if differences else None,
            "mean_cost_delta": sum(costs) / len(costs) if costs else None,
            "mean_retention_delta": (sum(retentions) / len(retentions)
                                      if retentions else None),
            "one_sided_exact_signflip_p": raw_p[name],
            "holm_four_contrasts_p": None,
        }
    for name, p in _holm_p(raw_p).items():
        contrasts[name]["holm_four_contrasts_p"] = p
    # Descriptive family slices cannot be selected after observing outcomes.
    # Any missing outcome blocks all per-family net-value calculations.
    family_contrasts = {}
    for family in sorted({family for (_, _, family) in blocks}):
        family_contrasts[family] = {}
        for name in CONTRASTS:
            def seed_means(source: dict) -> list[float]:
                return [sum(v) / len(v) for _, v in
                        sorted(source.get(family, {}).get(name, {}).items())]
            net_values = seed_means(family_seed_net) if outcomes_complete else []
            cost_values = seed_means(family_seed_cost) if outcomes_complete else []
            retention_values = (seed_means(family_seed_retention)
                                if retention_complete else [])
            family_contrasts[family][name] = {
                "mean_net_delta": (sum(net_values) / len(net_values)
                                   if net_values else None),
                "mean_cost_delta": (sum(cost_values) / len(cost_values)
                                    if cost_values else None),
                "mean_retention_delta": (sum(retention_values) / len(retention_values)
                                         if retention_values else None),
                "seed_clusters": len(net_values) if outcomes_complete else None,
            }
    adverse_families = {
        name: ([family for family in sorted(family_contrasts)
                if family_contrasts[family][name]["mean_net_delta"] < 0]
               if outcomes_complete else None)
        for name in CONTRASTS
    }
    return {
        "registered_family_episode_counts": dict(
            sorted(next(iter(family_roster_by_seed.values())).items())),
        "family_contrasts": family_contrasts,
        "negative_net_families_by_contrast": adverse_families,
        "family_diagnostic_note": (
            "Descriptive paired net-value signs, not per-family efficacy tests; "
            "no family may be dropped after outcomes are observed."),
        "schema": SCHEMA,
        "factorial_cells": {"A": "Ordinary+ordinary", "B": "Ordinary+NDU",
                            "C": "Hepta+ordinary", "D": "Hepta+NDU"},
        "blocks": len(blocks),
        "seed_clusters": len({seed for (_, seed, _) in blocks}),
        "families": sorted({family for (_, _, family) in blocks}),
        "missing_outcome_blocks": missing_outcome_blocks,
        "missing_retention_blocks": missing_retention_blocks,
        "missing_resource_blocks": missing_resource_blocks,
        "all_evaluator_independence_declared": all_independence_declared,
        "actual_resource_mean_by_arm": {
            arm: {name: (sum(values) / len(values) if resource_complete else None)
                  for name, values in measurements.items()}
            for arm, measurements in actual_by_arm.items()
        },
        "contrasts": contrasts,
        "inference_note": ("Exploratory, conditional on seed sign-exchangeability and fixed "
                           "outcomes; four one-sided Holm corrections do not establish "
                           "external evaluator independence or causal attribution."),
        "credential_verification": "NOT_PERFORMED",
        "owner_attestation": "NOT_PERFORMED",
        "realized_cost_audit": "NOT_PERFORMED",
        "qualification": "HOLD_NO_GO",
        "authority": "DENY_ALL",
        "input_digest": _digest([asdict(row) for row in sorted(data, key=lambda r:
                               (r.episode_id, r.seed, r.family, r.arm))]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", required=True, type=Path,
                        help="frozen factorial FactorialRow JSONL; never live tasks")
    args = parser.parse_args()
    with args.trials.open(encoding="utf-8") as stream:
        rows = [FactorialRow(**json.loads(line)) for line in stream if line.strip()]
    print(json.dumps(factorial_evidence(rows), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
