"""Frozen-cohort, source-clustered, externally scored tail-risk diagnostics.

Risk is measured on decoded-output loss receipts already admitted by
registered_factorial. A large draw count from one original source never
becomes a large count of independent natural sources. This is descriptive
scientific accounting, not a time-consistent dynamic CVaR controller,
calibrated risk law, or independent outcome attestation.
"""
from __future__ import annotations

from collections import defaultdict
from math import fsum, isfinite

from factorial_admission import ARMS, ScoreRow
from registered_factorial import (
    RegisteredFactorialCohort, describe_registered_factorial,
)

TAIL_MASS = 0.10


def fractional_upper_tail(values: list[float] | tuple[float, ...]) -> float:
    """Worst 10 percent probability mass, with exact fractional final row.

    Elements have equal mass within the supplied *sampling unit*. Callers
    decide that unit before evaluation (here: independent source strata),
    rather than treating correlated model draws as independent sources.
    """
    if (type(values) not in (list, tuple) or not values
        or any(type(x) not in (int, float) or not isfinite(x) for x in values)):
        raise ValueError("invalid tail probability observations")
    ordered = sorted(values, reverse=True)
    mass = len(ordered) * TAIL_MASS
    whole = int(mass)
    fraction = mass - whole
    weighted = fsum(ordered[:whole])
    if fraction:
        weighted += fraction * ordered[whole]
    return weighted / mass


def describe_source_cluster_tail(
    rows: list[ScoreRow], cohort: RegisteredFactorialCohort,
) -> dict:
    """Preserve four-arm pairing and report tail losses/costs per original source.

    There are two different estimands:
    * source-mean CVaR90: worst decile of independent source-mean losses;
    * draw-tail CVaR90: worst-decile source strata after retaining the
      worst within-world draw decile, rather than averaging away rare errors.

    For two seeds, first compute each tail risk separately by seed, then
    average those seed-level values. No confidence or causal claim follows.
    """
    admitted = describe_registered_factorial(rows, cohort)
    grouped = defaultdict(list)
    world_roster = defaultdict(set)
    seed_sources = defaultdict(set)
    for seed, source, world, _draw in cohort.keys:
        world_roster[(seed, source)].add(world)
        seed_sources[seed].add(source)
    for row in rows:
        grouped[(row.seed, row.original_source, row.world, row.arm)].append(row)

    per_seed_loss = defaultdict(list)
    per_seed_draw_tail = defaultdict(list)
    per_seed_cost_tail = defaultdict(list)
    paired_source_deltas = defaultdict(list)

    for seed, sources in sorted(seed_sources.items()):
        for source in sorted(sources):
            mean_by_arm = {}
            for arm in ARMS:
                world_means = []
                world_draw_tails = []
                world_cost_tails = []
                for world in sorted(world_roster[(seed, source)]):
                    items = grouped[(seed, source, world, arm)]
                    if not items:
                        raise ValueError("missing registered source/world/arm")
                    world_means.append(
                        fsum(x.external_loss for x in items) / len(items))
                    world_draw_tails.append(
                        fractional_upper_tail([x.external_loss for x in items]))
                    world_cost_tails.append(
                        fractional_upper_tail([x.physical_cost for x in items]))
                source_mean = fsum(world_means) / len(world_means)
                mean_by_arm[arm] = source_mean
                per_seed_loss[(seed, arm)].append(source_mean)
                per_seed_draw_tail[(seed, arm)].append(max(world_draw_tails))
                per_seed_cost_tail[(seed, arm)].append(max(world_cost_tails))

            paired_source_deltas[(seed, "base")].append(
                mean_by_arm["base_ndu"] - mean_by_arm["base_static"])
            paired_source_deltas[(seed, "trained")].append(
                mean_by_arm["trained_ndu"] - mean_by_arm["trained_static"])

    seeds = sorted(seed_sources)
    result = {}
    for field, measurements in (
        ("source_mean_cvar90_external_loss", per_seed_loss),
        ("within_source_draw_tail_cvar90_external_loss", per_seed_draw_tail),
        ("within_source_draw_tail_cvar90_physical_cost", per_seed_cost_tail),
    ):
        result[field] = {
            arm: fsum(fractional_upper_tail(measurements[(seed, arm)])
                      for seed in seeds) / len(seeds)
            for arm in ARMS
        }
    result["paired_source_delta_upper_tail90"] = {
        mode: fsum(fractional_upper_tail(paired_source_deltas[(seed, mode)])
                   for seed in seeds) / len(seeds)
        for mode in ("base", "trained")
    }
    result["source_tail_cvar90_inference_contrasts"] = {
        "base_ndu_minus_static": (
            result["source_mean_cvar90_external_loss"]["base_ndu"]
            - result["source_mean_cvar90_external_loss"]["base_static"]),
        "trained_ndu_minus_static": (
            result["source_mean_cvar90_external_loss"]["trained_ndu"]
            - result["source_mean_cvar90_external_loss"]["trained_static"]),
    }

    # The independent calculation must agree with the existing registered
    # mean-loss routine before a risk report can be accepted.
    for arm in ARMS:
        source_mean = fsum(
            fsum(per_seed_loss[(seed, arm)]) / len(per_seed_loss[(seed, arm)])
            for seed in seeds
        ) / len(seeds)
        if abs(source_mean - admitted["balanced_mean_external_loss"][arm]) > 1e-10:
            raise ValueError("hierarchical mean loss accounting mismatch")

    return {
        "scope": "SOURCE_CLUSTERED_TAIL_DESCRIPTIVE_DENY_ALL",
        "registered_cohort_digest": admitted["registered_cohort_digest"],
        # Source × seed strata are only within-seed weighting units. The
        # identical original source across training seeds is a single
        # declared source ID, never an additional independent source.
        "source_strata": admitted["original_source_strata"],
        "declared_unique_original_source_ids":
            admitted["declared_unique_original_source_ids"],
        "declared_source_ids_reused_across_seeds":
            admitted["declared_source_ids_reused_across_seeds"],
        "sampling_unit_independence_verified": False,
        "training_seeds": admitted["training_seeds"],
        "retained_failed_arm_rows": admitted["retained_failed_arm_rows"],
        "physical_cost_unit": admitted["physical_cost_unit"],
        "risk_level": "upper-tail-90-percent",
        "independent_sampling_unit": "original_source_within_training_seed",
        "tail_convention": "fractional_10_percent",
        **result,
        "independent_outcome_attestation_verified": False,
        "correlation_shift_robustness_established": False,
        "scientific_superiority_established": False,
    }
