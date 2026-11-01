"""Preregistered paired-fit statistics; episodes are never independent units.

The primary unit is one of eight independent fitted seed pairs.  The two
primary contrasts compare D with B in IID and OOD.  Other factorial contrasts
are descriptive.  CPU ratios are ratios of domain-level arm means, not means
of per-episode or per-fit ratios.  Online, direct and full costs stay separate.
"""

import itertools
import math

import numpy as np
from scipy.stats import t as student_t


DOMAINS = ("iid", "ood")
ARMS = ("A", "B", "C", "D")
ARM_MAPPING = {
    "A": "ordinary selected core, fixed READ control",
    "B": "ordinary selected core, finite-horizon value control",
    "C": "HX distribution core, fixed READ control",
    "D": "HX distribution core, finite-horizon value control",
}
COST_COLUMNS = ("online_cpu_per_episode", "direct_cpu_per_episode", "full_cpu_per_episode")
FIT_COUNT = 8
QUALITY_EFFECT = .01
NONINFERIORITY_MARGIN = .01
COST_RATIO_LIMIT = .90


def exact_sign_flip(values):
    """Two-sided, exhaustive 2**8 paired sign-flip p-value for the mean."""
    values = np.asarray(values, dtype=np.float64)
    if values.shape != (FIT_COUNT,) or not np.isfinite(values).all():
        raise ValueError("exact primary test requires eight finite paired fit effects")
    observed = abs(float(np.mean(values)))
    scale = max(float(np.sum(np.abs(values)))/FIT_COUNT, observed)
    tolerance = 16*np.finfo(float).eps*scale
    at_least_as_extreme = 0
    for signs in itertools.product((-1., 1.), repeat=FIT_COUNT):
        statistic = abs(float(np.mean(values*np.asarray(signs))))
        at_least_as_extreme += statistic >= observed-tolerance
    return at_least_as_extreme/(2**FIT_COUNT)


def paired_summary(values, seeds):
    values = np.asarray(values, dtype=np.float64)
    if values.shape != (FIT_COUNT,) or not np.isfinite(values).all():
        raise ValueError("descriptive intervals require eight finite paired fit effects")
    mean = float(np.mean(values))
    standard_deviation = float(np.std(values, ddof=1))
    standard_error = standard_deviation/math.sqrt(FIT_COUNT)
    half_width = float(student_t.ppf(.975, FIT_COUNT-1))*standard_error
    return {"independent_unit": "paired fit seed", "n": FIT_COUNT,
            "per_seed": [{"seed": int(seed), "value": float(value)}
                         for seed, value in zip(seeds, values)],
            "mean": mean, "sample_sd": standard_deviation,
            "standard_error": standard_error,
            "t_95pct_ci": [mean-half_width, mean+half_width],
            "degrees_of_freedom": FIT_COUNT-1}


def holm_adjust(p_values):
    """Holm familywise adjustment, preserving the supplied named hypotheses."""
    if len(p_values) != len(DOMAINS) or set(p_values) != set(DOMAINS):
        raise ValueError("primary Holm family is exactly the IID and OOD D-minus-B tests")
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in p_values.values()):
        raise ValueError("invalid primary p-value")
    ordered = sorted(p_values, key=lambda key: (p_values[key], key))
    adjusted = {}
    previous = 0.
    for rank, name in enumerate(ordered):
        previous = max(previous, (len(ordered)-rank)*p_values[name])
        adjusted[name] = min(1., previous)
    return adjusted


def _validate_rows(rows):
    if len(rows) != FIT_COUNT*len(DOMAINS):
        raise ValueError("require exactly eight paired fits in each of two domains")
    indexed = {name: {} for name in DOMAINS}
    direct_present = []
    for row in rows:
        if row.get("domain") not in indexed:
            raise ValueError("domain must be iid or ood")
        seed = row.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("fit seed must be an integer")
        group = indexed[row["domain"]]
        if seed in group:
            raise ValueError("duplicate paired fit seed in one domain")
        if set(row.get("arms", {})) != set(ARMS):
            raise ValueError("every paired fit must contain all four arms A/B/C/D")
        for arm in ARMS:
            item = row["arms"][arm]
            for key in ("mean_utility", "online_cpu_per_episode", "full_cpu_per_episode"):
                value = item.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float, np.number)) or not math.isfinite(float(value)):
                    raise ValueError(f"missing or nonfinite {key} in arm {arm}")
                if key != "mean_utility" and value < 0:
                    raise ValueError("CPU costs cannot be negative")
            present = item.get("direct_cpu_per_episode") is not None
            direct_present.append(present)
            if present:
                value = item["direct_cpu_per_episode"]
                if isinstance(value, bool) or not isinstance(value, (int, float, np.number)) or not math.isfinite(float(value)) or value < 0:
                    raise ValueError("direct CPU must be finite and nonnegative")
        group[int(seed)] = row
    if any(len(group) != FIT_COUNT for group in indexed.values()):
        raise ValueError("each domain must contain eight independent fitted seeds")
    if set(indexed["iid"]) != set(indexed["ood"]):
        raise ValueError("IID and OOD must evaluate the same eight frozen fitted seeds")
    if any(direct_present) and not all(direct_present):
        raise ValueError("optional direct CPU column must be complete or absent, never mixed")
    return indexed, all(direct_present)


def _cost_summary(rows, seeds, include_direct):
    columns = COST_COLUMNS if include_direct else (COST_COLUMNS[0], COST_COLUMNS[2])
    means = {arm: {column: float(np.mean([row["arms"][arm][column] for row in rows]))
                   for column in columns} for arm in ARMS}
    ratios = {}
    for column in COST_COLUMNS:
        if column not in columns or means["B"][column] == 0:
            ratios[column] = None
        else:
            ratios[column] = means["D"][column]/means["B"][column]
    return {"unit": "process CPU seconds per episode",
            "aggregation": "D/B ratio of domain arm means across the eight fits",
            "arm_means": means, "D_over_B": ratios,
            "per_seed": [{"seed": int(seed), "arms": {
                arm: {column: float(row["arms"][arm][column]) for column in columns}
                for arm in ARMS}} for seed, row in zip(seeds, rows)],
            "direct_column_supplied": include_direct,
            "direct_missing_policy": "Absent direct costs remain null and are not replaced by online or full costs"}


def summarize(rows):
    """Summarize sixteen frozen rows without treating their episodes as fits.

    Required row: ``{seed, domain, arms: {A: {mean_utility,
    online_cpu_per_episode, full_cpu_per_episode}, B: ..., C: ..., D: ...}}``.
    A complete ``direct_cpu_per_episode`` column is optional.  The experiment
    runner owns measured-cost construction; this module never reallocates or
    silently substitutes shared calibration, selection or preparation costs.
    """
    rows = list(rows)
    indexed, include_direct = _validate_rows(rows)
    seeds = sorted(indexed["iid"])
    domains, raw_p = {}, {}
    for domain in DOMAINS:
        ordered = [indexed[domain][seed] for seed in seeds]
        means = {arm: np.asarray([row["arms"][arm]["mean_utility"] for row in ordered], dtype=float)
                 for arm in ARMS}
        effects = {"B-A": means["B"]-means["A"], "D-C": means["D"]-means["C"],
                   "C-A": means["C"]-means["A"], "D-B": means["D"]-means["B"]}
        effects["interaction"] = effects["D-C"]-effects["B-A"]
        contrasts = {name: paired_summary(values, seeds) for name, values in effects.items()}
        raw_p[domain] = exact_sign_flip(effects["D-B"])
        primary = contrasts["D-B"]
        lower = primary["mean"]-float(student_t.ppf(.975, FIT_COUNT-1))*primary["standard_error"]
        cost = _cost_summary(ordered, seeds, include_direct)
        full_ratio = cost["D_over_B"]["full_cpu_per_episode"]
        utility_noninferior = lower > -NONINFERIORITY_MARGIN
        cpu_acceptable = full_ratio is not None and full_ratio <= COST_RATIO_LIMIT
        domains[domain] = {
            "utility_arm_means": {arm: float(np.mean(values)) for arm, values in means.items()},
            "contrasts": contrasts, "costs": cost,
            "primary_test": {"contrast": "D-B", "test": "two-sided exhaustive paired sign flip",
                             "enumerated_sign_vectors": 2**FIT_COUNT, "raw_p": raw_p[domain]},
            "cost_acceptance": {"utility_lower_bound": lower,
                                "per_domain_one_sided_confidence": .975,
                                "familywise_confidence_at_least": .95,
                                "multiplicity": "Bonferroni across IID/OOD utility bounds",
                                "noninferiority_margin": NONINFERIORITY_MARGIN,
                                "utility_noninferior": bool(utility_noninferior),
                                "measured_full_cpu_ratio": full_ratio,
                                "full_cpu_ratio_maximum": COST_RATIO_LIMIT,
                                "cpu_acceptable": bool(cpu_acceptable),
                                "accepted": bool(utility_noninferior and cpu_acceptable)},
        }
    adjusted = holm_adjust(raw_p)
    for domain in DOMAINS:
        primary = domains[domain]["primary_test"]
        mean = domains[domain]["contrasts"]["D-B"]["mean"]
        primary.update(holm_adjusted_p=adjusted[domain], family="IID/OOD D-B",
                       alpha=.05, minimum_mean_improvement=QUALITY_EFFECT,
                       improvement=bool(mean >= QUALITY_EFFECT and adjusted[domain] < .05))
    return {"schema": "hcsn-r13-eight-paired-fit-statistics-v1", "fit_seeds": seeds,
            "independent_unit": "paired fitted seed, not episodes or time steps",
            "fits_per_domain": FIT_COUNT, "arm_mapping": ARM_MAPPING,
            "interaction_definition": "(D-C)-(B-A)", "domains": domains,
            "inference_limits": "Sign-flip inference assumes exchangeable effect signs under the null; t bounds assume paired fit means are adequately approximated by a t sampling model with seven degrees of freedom.",
            "cost_limits": "CPU is measured computation, not energy. Cost acceptance uses full costs only; online and direct columns are descriptive and never substitute for full cost.",
            "cost_allocation_contract": "All arms include common preparation. HX fitting supplies the shared controller calibration; C/D count that fit once, A/B also include both ordinary candidate fits used for validation selection, amortized by the runner at 1000 episodes."}
