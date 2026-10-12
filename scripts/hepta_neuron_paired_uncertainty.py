#!/usr/bin/env python3
"""Bounded deterministic source-group paired uncertainty for shadow Neuron trials.

This is evaluator-only descriptive statistics, never NDU or a promotion gate.
Groups, not individual episodes, are the bootstrap resampling units. When
there are too few independently sourced groups, bounds are deliberately null.
"""
from __future__ import annotations

import hashlib
import math
import random
import re

BOOTSTRAP_DRAWS = 1024
MIN_GROUPS = 8
MAX_EVENTS = 4096
_GROUP = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class InvalidPairedUncertainty(ValueError):
    pass


def paired_cluster_interval(pairs, *, seed_identity: str, unit: str) -> dict:
    """Return a descriptive 95% group bootstrap interval for candidate - baseline.

    pairs is an iterable of (source_group, per-case score difference) pairs.
    Positive accuracy differences favor the candidate; negative MSE
    differences favor the candidate. Do not mix these units within one call.
    """
    if unit not in ("accuracy", "mse"):
        raise InvalidPairedUncertainty("unknown paired difference units")
    if not isinstance(seed_identity, str) or not (1 <= len(seed_identity) <= 256):
        raise InvalidPairedUncertainty("bounded frozen sample identity required")
    grouped = {}
    count = 0
    for row in pairs:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise InvalidPairedUncertainty("expected grouped paired sample")
        group, value = row
        if not isinstance(group, str) or _GROUP.fullmatch(group) is None:
            raise InvalidPairedUncertainty("invalid source group")
        if type(value) not in (int, float) or not math.isfinite(value):
            raise InvalidPairedUncertainty("nonfinite or nonnumeric paired difference")
        if abs(value) > (1 if unit == "accuracy" else 256):
            raise InvalidPairedUncertainty("paired score outside registered range")
        count += 1
        if count > MAX_EVENTS:
            raise InvalidPairedUncertainty("source sample cap exceeded")
        grouped.setdefault(group, []).append(float(value))
    if not count:
        raise InvalidPairedUncertainty("no paired comparison cases")

    # Canonical iteration is insensitive to dataset row ordering. Each group
    # is resampled as a whole, retaining its observed case count and values.
    groups = [sorted(grouped[name]) for name in sorted(grouped)]
    values = [value for group in groups for value in group]
    estimate = sum(values) / count
    result = {
        "method": "source_group_cluster_bootstrap_percentile_v1",
        "statistic": "candidate_minus_production_no_change_" + unit,
        "benefit_when": "positive" if unit == "accuracy" else "negative",
        "paired_events": count,
        "independent_source_groups": len(groups),
        "minimum_groups_for_interval": MIN_GROUPS,
        "point_estimate": estimate,
        "confidence_level_descriptive": 0.95,
        "lower": None,
        "upper": None,
        "resamples": 0,
        "reason": "insufficient_independent_source_groups",
        "significance_or_promotion_claim": False,
    }
    if len(groups) < MIN_GROUPS:
        return result

    seed = hashlib.sha256(
        b"hepta.neuron.paired-cluster-bootstrap.v1\0" + seed_identity.encode("utf-8")
    ).digest()
    rng = random.Random(int.from_bytes(seed, "big"))
    group_summaries = [(sum(group), len(group)) for group in groups]
    quantiles = []
    for _ in range(BOOTSTRAP_DRAWS):
        numerator, denominator = 0.0, 0
        for _ in range(len(groups)):
            total, size = group_summaries[rng.randrange(len(groups))]
            numerator += total
            denominator += size
        quantiles.append(numerator / denominator)
    quantiles.sort()
    result.update(
        lower=quantiles[math.floor((BOOTSTRAP_DRAWS - 1) * 0.025)],
        upper=quantiles[math.ceil((BOOTSTRAP_DRAWS - 1) * 0.975)],
        resamples=BOOTSTRAP_DRAWS,
        reason="descriptive_only_not_a_causal_or_independent_evaluator_gate",
    )
    return result
