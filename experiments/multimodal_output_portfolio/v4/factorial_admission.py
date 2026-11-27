"""Research-only 2x2 generator-training / inference-controller admission.

This module validates *externally supplied* raw-output score receipts. It does
not execute models, authenticate self-asserted hashes, or claim NDU efficacy.
The scorer, permitted sources, and physical-unit convention must be fixed by a
separate independent owner before any heldout evidence is admitted.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite, fsum

ARMS = ("base_static", "base_ndu", "trained_static", "trained_ndu")
PHYSICAL_UNITS = ("measured_wall_seconds", "measured_cpu_seconds",
                  "measured_device_joules")


@dataclass(frozen=True)
class ScoreRow:
    arm: str
    seed: int
    original_source: str
    world: str
    draw: int
    randomness_digest: str
    input_digest: str
    decoder_digest: str
    scoring_digest: str
    external_loss: float
    physical_cost: float
    unit: str
    complete: bool


def _valid_digest(value: str) -> bool:
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def verify_and_pair(rows: list[ScoreRow], *, frozen_scoring_digest: str,
                    allowed_sources: set[str]) -> dict:
    """Fail closed before estimating any interaction or paired effect."""
    if (not rows or not _valid_digest(frozen_scoring_digest)
        or not allowed_sources or any(type(x) is not str or not x for x in allowed_sources)):
        raise ValueError("missing immutable evaluation contract")
    pairs = defaultdict(dict)
    seed_sources = defaultdict(set)
    for r in rows:
        if (type(r) is not ScoreRow or r.arm not in ARMS
            or type(r.seed) is not int or type(r.draw) is not int or r.draw < 0
            or not r.original_source or r.original_source not in allowed_sources
            or not r.world or not _valid_digest(r.randomness_digest)
            or not _valid_digest(r.input_digest)
            or not _valid_digest(r.decoder_digest)
            or r.scoring_digest != frozen_scoring_digest
            or not isfinite(r.external_loss) or r.external_loss < 0
            or not isfinite(r.physical_cost) or r.physical_cost < 0
            or r.unit not in PHYSICAL_UNITS or type(r.complete) is not bool):
            raise ValueError("untrusted or invalid score row")
        key = (r.seed, r.original_source, r.world, r.draw)
        if r.arm in pairs[key]:
            raise ValueError("duplicate policy arm")
        pairs[key][r.arm] = r
        seed_sources[r.seed].add(r.original_source)
    if not pairs:
        raise ValueError("no paired worlds")
    # A repeated world from two original source groups is unsupported:
    # repeated views of one underlying source cannot invent independence.
    world_owner = {}
    for _, source, world, _ in pairs:
        owner = world_owner.setdefault(world, source)
        if owner != source:
            raise ValueError("world/source alias")
    for key, arms in pairs.items():
        if set(arms) != set(ARMS):
            raise ValueError("incomplete 2x2 factorial")
        items = list(arms.values())
        if (len({r.randomness_digest for r in items}) != 1
            or len({r.input_digest for r in items}) != 1
            or len({r.decoder_digest for r in items}) != 1
            or len({r.unit for r in items}) != 1):
            raise ValueError("unpaired randomness, inputs, decoder or physical cost units")
        # Failures remain in the dataset and pay their measured costs.
        # Never impute quality or silently delete failed/over-budget rows.
        if any(not r.complete for r in items):
            raise ValueError("failed output lacks independently assigned failure loss")
    if len(seed_sources) < 2:
        raise ValueError("insufficient independent training seeds")
    unit = next(iter(pairs.values()))["base_static"].unit
    if any(r.unit != unit for arm_map in pairs.values() for r in arm_map.values()):
        raise ValueError("mixed physical cost units")
    return {"pairs": pairs, "seed_sources": dict(seed_sources), "unit": unit}


def describe_factorial(rows: list[ScoreRow], *, frozen_scoring_digest: str,
                       allowed_sources: set[str]) -> dict:
    """Descriptive contrasts only; never an automatic superiority verdict."""
    matched = verify_and_pair(rows, frozen_scoring_digest=frozen_scoring_digest,
                              allowed_sources=allowed_sources)
    pairs = matched["pairs"]
    count = len(pairs)
    mean_loss = {arm: fsum(p[arm].external_loss for p in pairs.values()) / count
                 for arm in ARMS}
    mean_cost = {arm: fsum(p[arm].physical_cost for p in pairs.values()) / count
                 for arm in ARMS}
    # Negative contrasts favor the NDU-controlled arm for external loss.
    inference_on_base = mean_loss["base_ndu"] - mean_loss["base_static"]
    training_under_static = mean_loss["trained_static"] - mean_loss["base_static"]
    inference_after_training = mean_loss["trained_ndu"] - mean_loss["trained_static"]
    interaction = inference_after_training - inference_on_base
    return {
        "scope": "DESCRIPTIVE_ONLY_DENY_ALL",
        "paired_world_draws": count,
        "independent_training_seeds": len(matched["seed_sources"]),
        "distinct_original_sources": len({k[1] for k in pairs}),
        "physical_cost_unit": matched["unit"],
        "mean_external_loss": mean_loss,
        "mean_physical_cost": mean_cost,
        "inference_effect_on_base": inference_on_base,
        "training_effect_under_static": training_under_static,
        "inference_effect_after_training": inference_after_training,
        "factorial_interaction": interaction,
        "causal_or_statistical_superiority_established": False,
    }
