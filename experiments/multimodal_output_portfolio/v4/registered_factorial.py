"""Strict, frozen-cohort, externally-scored four-arm NDU factorial research gate.

This is a non-authorizing *descriptive* analysis. Hashes, costs, original-source
identities, failure labels and independent scores are caller supplied; authentic
outcome-observer custody and genuinely executed neural interventions are outside
this function. No data can be dropped or reweighted after cohort registration.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from math import fsum, isfinite

from factorial_admission import (
    ARMS, PHYSICAL_UNITS, ScoreRow, describe_factorial, verify_and_pair,
)

MAX_REGISTERED_PAIRS = 100_000
MAX_FAILURE_LOSS = 1e12
MAX_SEED = 2**63 - 1


def _digest(value: str) -> bool:
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


@dataclass(frozen=True)
class RegisteredFactorialCohort:
    # Exact registered world/draw roster, not just source and arm cardinality.
    keys: tuple[tuple[int, str, str, int], ...]
    allowed_sources: frozenset[str]
    scoring_digest: str
    physical_unit: str
    failed_output_loss: float

    def __post_init__(self) -> None:
        if (type(self.keys) is not tuple
            or not 0 < len(self.keys) <= MAX_REGISTERED_PAIRS
            or type(self.allowed_sources) is not frozenset
            or not self.allowed_sources
            or any(type(s) is not str or not s for s in self.allowed_sources)
            or not _digest(self.scoring_digest)
            or self.physical_unit not in PHYSICAL_UNITS
            or type(self.failed_output_loss) not in (int, float)
            or not 0 < self.failed_output_loss <= MAX_FAILURE_LOSS
            or not isfinite(self.failed_output_loss)):
            raise ValueError("invalid frozen factorial cohort contract")
        seen = set()
        seeds = set()
        seed_sources = defaultdict(set)
        world_owner = {}
        for key in self.keys:
            if (type(key) is not tuple or len(key) != 4
                or type(key[0]) is not int or not 0 <= key[0] <= MAX_SEED
                or type(key[1]) is not str or key[1] not in self.allowed_sources
                or type(key[2]) is not str or not key[2]
                or type(key[3]) is not int or not 0 <= key[3] <= 1_000_000
                or key in seen):
                raise ValueError("invalid or duplicate registered episode")
            seen.add(key)
            seed, source, world, _draw = key
            seeds.add(seed)
            seed_sources[seed].add(source)
            owner = world_owner.setdefault(world, source)
            if owner != source:
                raise ValueError("registered world/source alias")
        if len(seeds) < 2 or any(len(sources) < 2 for sources in seed_sources.values()):
            raise ValueError("insufficient seed and original-source coverage")

    @property
    def cohort_digest(self) -> str:
        blob = json.dumps(
            {"schema": "hepta.ndu.factorial.registered-cohort.v1",
             "keys": sorted(self.keys),
             "allowed_sources": sorted(self.allowed_sources),
             "scoring_digest": self.scoring_digest,
             "physical_unit": self.physical_unit,
             "failed_output_loss": self.failed_output_loss},
            sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
        return sha256(blob).hexdigest()


def describe_registered_factorial(
    rows: list[ScoreRow], cohort: RegisteredFactorialCohort,
) -> dict:
    """Reject nonregistered episodes, failures without fixed penalty and selective loss omission."""
    if type(cohort) is not RegisteredFactorialCohort or type(rows) is not list:
        raise ValueError("missing frozen registration or score rows")
    if len(rows) != 4 * len(cohort.keys):
        raise ValueError("registered 2x2 panel cardinality mismatch")
    normalized = []
    failed = 0
    raw_groups = defaultdict(list)
    for r in rows:
        if (type(r) is not ScoreRow
            or type(r.arm) is not str or r.arm not in ARMS
            or type(r.seed) is not int or not 0 <= r.seed <= MAX_SEED
            or type(r.original_source) is not str
            or type(r.world) is not str or not r.world
            or type(r.draw) is not int or not 0 <= r.draw <= 1_000_000
            or type(r.external_loss) not in (int, float)
            or not 0 <= r.external_loss <= cohort.failed_output_loss
            or not isfinite(r.external_loss)
            or type(r.physical_cost) not in (int, float)
            or not 0 <= r.physical_cost <= 1e12
            or not isfinite(r.physical_cost)
            or type(r.complete) is not bool
            or r.unit != cohort.physical_unit):
            raise ValueError("invalid externally scored loss or physical cost")
        if not r.complete:
            # A failure is a paid, retained observation, never a dropped row
            # and never a cheaper label for a catastrophic completed output.
            if r.external_loss != cohort.failed_output_loss:
                raise ValueError("incomplete output is missing fixed failure loss")
            failed += 1
        raw_groups[(r.seed, r.original_source, r.arm)].append(r)
        normalized.append(replace(r, complete=True))
    # The existing source/draw/randomness/scorer/decoder checker still owns the
    # inner four-arm pairing; normalization is only after enforcing the
    # independent fixed failure-loss contract above.
    match = verify_and_pair(
        normalized, frozen_scoring_digest=cohort.scoring_digest,
        allowed_sources=set(cohort.allowed_sources))
    if set(match["pairs"]) != set(cohort.keys):
        raise ValueError("unregistered, missing or selectively omitted world/draw")
    seed_sources = defaultdict(set)
    for seed, source, _world, _draw in cohort.keys:
        seed_sources[seed].add(source)

    balanced_loss, balanced_cost = {}, {}
    for arm in ARMS:
        per_seed_loss = []
        per_seed_cost = []
        for seed, sources in sorted(seed_sources.items()):
            per_source_loss = []
            per_source_cost = []
            for source in sorted(sources):
                group = raw_groups[(seed, source, arm)]
                if not group:
                    raise ValueError("registered seed/source arm missing")
                per_source_loss.append(fsum(r.external_loss for r in group) / len(group))
                per_source_cost.append(fsum(r.physical_cost for r in group) / len(group))
            per_seed_loss.append(fsum(per_source_loss) / len(per_source_loss))
            per_seed_cost.append(fsum(per_source_cost) / len(per_source_cost))
        balanced_loss[arm] = fsum(per_seed_loss) / len(per_seed_loss)
        balanced_cost[arm] = fsum(per_seed_cost) / len(per_seed_cost)

    pooled = describe_factorial(
        normalized, frozen_scoring_digest=cohort.scoring_digest,
        allowed_sources=set(cohort.allowed_sources))
    delta_base = balanced_loss["base_ndu"] - balanced_loss["base_static"]
    delta_trained = balanced_loss["trained_ndu"] - balanced_loss["trained_static"]
    return {
        "scope": "REGISTERED_DESCRIPTIVE_ONLY_DENY_ALL",
        "registered_cohort_digest": cohort.cohort_digest,
        "registered_world_draws": len(cohort.keys),
        "retained_failed_arm_rows": failed,
        "training_seeds": len(seed_sources),
        "original_source_strata": len({(seed, source)
                                       for seed, sources in seed_sources.items()
                                       for source in sources}),
        "physical_cost_unit": cohort.physical_unit,
        "balanced_mean_external_loss": balanced_loss,
        "balanced_mean_physical_cost": balanced_cost,
        "balanced_inference_effect_on_base": delta_base,
        "balanced_inference_effect_after_training": delta_trained,
        "balanced_training_effect_under_static":
            balanced_loss["trained_static"] - balanced_loss["base_static"],
        "balanced_factorial_interaction": delta_trained - delta_base,
        "pooled_mean_external_loss_diagnostic": pooled["mean_external_loss"],
        "independent_outcome_attestation_verified": False,
        "scientific_causality_or_superiority_established": False,
    }
