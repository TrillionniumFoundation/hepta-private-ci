# Copyright 2026 Muvon Un Limited
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Exploratory paired actor-cluster intervals from already computed metric deltas.

This module has no file, model, optimization, network or random-number interface.
It does not decide which candidate to evaluate or which comparison to retain.
"""

from functools import lru_cache
import hashlib
import json
import math


ACTORS = (5, 6, 11, 12, 21, 22)
METRICS = ("accuracy", "brier", "ce")
SEED_FAMILIES = {
    (47,): "sender_role",
    (83,): "boundary",
    (137,): "boundary",
    (83, 137): "boundary",
    (47, 83, 137): "bp",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite_number(value, label):
    _require(type(value) in (int, float) and math.isfinite(value), label + " must be finite")
    return float(value)


def _compositions(total, parts):
    if parts == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for tail in _compositions(total - first, parts - 1):
            yield (first,) + tail


@lru_cache(maxsize=1)
def _design():
    """All six-cluster ordered resamples grouped by their exact multiplicities."""
    patterns = tuple((counts, math.factorial(6) // math.prod(math.factorial(c) for c in counts))
                     for counts in _compositions(6, 6))
    _require(len(patterns) == 462 and sum(weight for _, weight in patterns) == 46656,
             "fixed multinomial enumeration differs")
    raw = json.dumps([[list(counts), weight] for counts, weight in patterns],
                     separators=(",", ":"), allow_nan=False).encode()
    return patterns, hashlib.sha256(raw).hexdigest()


def _quantile(sorted_values, numerator):
    cumulative = 0
    for value, weight in sorted_values:
        cumulative += weight
        # Exact 1/40 and39/40 cumulative thresholds; no interpolation or RNG.
        if cumulative * 40 >= numerator * 46656:
            return value
    raise ValueError("incomplete bootstrap probability mass")


def _summarize_metric(deltas, metric, patterns):
    estimate = math.fsum(deltas) / 6
    values = []
    for counts, weight in patterns:
        value = math.fsum(count * delta for count, delta in zip(counts, deltas)) / 6
        _require(math.isfinite(value), "bootstrap aggregate overflows finite arithmetic")
        values.append((value, weight))
    values.sort(key=lambda item: item[0])
    _require(math.isfinite(estimate), "point estimate overflows finite arithmetic")
    return {
        "estimate": estimate,
        "interval": [_quantile(values, 1), _quantile(values, 39)],
        "actor_deltas": list(deltas),
        "delta_definition": "lhs_minus_rhs",
        "favorable_direction": "positive" if metric == "accuracy" else "negative",
        "multiplicity_patterns": 462,
        "ordered_resample_weight": 46656,
        "exploratory": True,
    }


def summarize_contrasts(contrasts):
    """Return fixed-design exploratory intervals without changing any denominator.

    Each actor/parent delta is already its eight-query mean, lhs minus rhs.
    Parents are averaged equally within each actor, then the same six actors
    are resampled together for every comparison. Pooled model seeds are not
    treated as additional independent actor clusters. Missing parents make a
    predeclared comparison UNAVAILABLE rather than reducing its denominator.
    """
    _require(type(contrasts) is list and 1 <= len(contrasts) <= 13,
             "one to thirteen predeclared contrasts required")
    patterns, design_sha = _design()
    identifiers = set()
    result = []
    for item in contrasts:
        _require(type(item) is dict, "contrast must be an object")
        identifier = item.get("id")
        _require(type(identifier) is str and 0 < len(identifier) <= 128
                 and identifier not in identifiers, "unique bounded contrast ID required")
        identifiers.add(identifier)
        seeds = item.get("parent_seeds")
        _require(type(seeds) is list and all(type(seed) is int for seed in seeds),
                 "ordered integer parent seeds required")
        seed_tuple = tuple(seeds)
        _require(seed_tuple in SEED_FAMILIES and item.get("family") == SEED_FAMILIES[seed_tuple],
                 "parent order or mechanism family differs from the fixed comparison")
        status = item.get("status")
        _require(status in ("COMPLETE", "UNAVAILABLE"), "invalid comparison status")
        row = {
            "id": identifier, "family": item["family"], "parent_seeds": list(seeds),
            "status": status, "actor_order": list(ACTORS),
            "expected_parent_count": len(seeds), "expected_queries_per_parent": 48,
            "queries_per_actor_per_parent": 8,
            "point_weighting": "equal_parent_mean_within_actor_then_equal_six_actor_mean",
            "shared_actor_resampling": True, "exploratory": True,
        }
        if status == "UNAVAILABLE":
            _require(item.get("actor_rows") == [], "unavailable comparison must not carry partial actor data")
            reason = item.get("unavailable_reason")
            _require(type(reason) is str and 0 < len(reason) <= 2048,
                     "unavailable comparison requires a bounded reason")
            row.update(unavailable_reason=reason, metrics=None, intervals_computed=False,
                       missing_parents_removed=False)
            result.append(row)
            continue
        actor_rows = item.get("actor_rows")
        _require(type(actor_rows) is list and len(actor_rows) == 6,
                 "all six actors required in each complete comparison")
        metric_deltas = {metric: [] for metric in METRICS}
        for expected_actor, actor_row in zip(ACTORS, actor_rows):
            _require(type(actor_row) is dict and type(actor_row.get("actor")) is int
                     and actor_row["actor"] == expected_actor, "fixed actor order differs")
            per_parent = actor_row.get("per_parent")
            _require(type(per_parent) is list and len(per_parent) == len(seeds),
                     "missing parent cannot be dropped from a complete comparison")
            totals = {metric: [] for metric in METRICS}
            for expected_seed, parent in zip(seeds, per_parent):
                _require(type(parent) is dict and type(parent.get("seed")) is int
                         and parent["seed"] == expected_seed and type(parent.get("n")) is int
                         and parent["n"] == 8, "fixed parent order or eight-query actor size differs")
                for metric in METRICS:
                    value = _finite_number(parent.get(metric + "_delta"), metric + " delta")
                    if metric == "accuracy":
                        _require(-1 <= value <= 1, "accuracy difference outside [-1,1]")
                    totals[metric].append(value)
            for metric in METRICS:
                mean = math.fsum(totals[metric]) / len(seeds)
                _require(math.isfinite(mean), "pooled actor mean overflows finite arithmetic")
                metric_deltas[metric].append(mean)
        row.update(metrics={metric: _summarize_metric(metric_deltas[metric], metric, patterns)
                            for metric in METRICS}, intervals_computed=True,
                   missing_parents_removed=False)
        result.append(row)
    return {
        "schema": "hepta.locked-historical-test.actor-cluster-intervals.v1",
        "contrasts": result, "actor_order": list(ACTORS),
        "bootstrap_design": {"clusters": 6, "draws_per_resample": 6,
            "multiplicity_patterns": 462, "ordered_resamples": 46656,
            "multinomial_weights_are_exact_integers": True,
            "design_sha256": design_sha,
            "quantile_rule": "smallest_value_with_cumulative_weight_times40_at_least_numerator_times46656",
            "quantile_numerators": [1, 39], "quantile_denominator": 40,
            "same_actor_draws_across_parents_and_contrasts": True,
            "random_sampling_performed": False},
        "exploratory_only": True, "confidence_or_coverage_guarantee": False,
        "p_values_computed": False, "multiple_comparison_confirmation_claim": False,
        "fresh_actor_holdout_claim": False, "candidate_selection_performed": False,
        "scope": "Finite empirical paired actor-cluster percentile summaries; six observed actors, historical fixed evaluation and previously selected candidates only.",
    }
