"""Paired source/seed statistics for the prospectively registered development study.

Metric cubes are [training_seed, source_pair, view, generation_scenario]. Seeds
are averaged after each trained model's risk is evaluated; they are not extra
generation outcomes. Frozen source identities, not rows, define source groups.
Crossed percentile bootstrap intervals have no guaranteed confirmatory coverage
with five training seeds. Only the two registered net-utility joint-CE contrasts
use nominal 97.5% intervals; all other contrasts are descriptive 95% intervals.
Empirical CE is a finite-scenario plug-in estimate, not an unbiased population
CE. In particular, four scenarios do not precisely identify each conditional
tail; the source/seed bootstrap preserves these draws rather than treating them
as additional independent source units.
"""

from dataclasses import dataclass
import hashlib
import math

import numpy as np


PRIMARY_COMPARISONS = (
    (("output_ndu", "fixed"), ("output_mean", "fixed")),
    (("output_ndu", "feedback"), ("output_ndu", "fixed")),
)


def registered_confidence(candidate, reference, *, metric="net_utility", estimand="joint_ce"):
    return 0.975 if (tuple(candidate), tuple(reference)) in PRIMARY_COMPARISONS and metric == "net_utility" and estimand == "joint_ce" else 0.95


def _cube(values):
    if np.ma.isMaskedArray(values) and np.any(np.ma.getmaskarray(values)):
        raise ValueError("masked/missing observations violate the complete census")
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 4 or min(result.shape) < 1 or not np.isfinite(result).all():
        raise ValueError("metric must be complete finite [seed,source,view,scenario]")
    return result


def _ce(values, gamma, axis=-1):
    gamma = float(gamma)
    if not math.isfinite(gamma) or gamma < 0:
        raise ValueError("gamma must be finite and nonnegative")
    center = values.mean(axis=axis, keepdims=True)
    if gamma == 0:
        return np.squeeze(center, axis=axis)
    with np.errstate(over="ignore", under="ignore", invalid="raise"):
        shifted = -gamma * (values - center)
        small = np.max(np.abs(shifted), axis=axis, keepdims=True) <= 0.5
        correction = np.expm1(np.where(small, shifted, 0)).mean(axis=axis, keepdims=True)
        near_zero = center - np.log1p(correction) / gamma
        minimum = values.min(axis=axis, keepdims=True)
        large = minimum - np.log(np.exp(-gamma * (values - minimum)).mean(axis=axis, keepdims=True)) / gamma
    result = np.squeeze(np.where(small, near_zero, large), axis=axis)
    if not np.isfinite(result).all():
        raise ValueError("CE is outside the finite numeric range")
    return result


def rows_to_cube(rows, *, seeds, cases, views, scenarios, conditions, metrics):
    """Return {(arm,policy): {metric: cube}} after a full frozen-census check.

    All expected axes and conditions must be supplied, not inferred from rows:
    inferring them would conceal a missing entire source or policy. One observer
    per metric/call; repeated timing rounds need a separate timing tensor. Extra
    replay keys do not make duplicate seed/condition/source/view/scenario rows new
    observations. Labels order the arrays; callers must retain this same census
    for every paired comparison. This does not prove physical source independence.
    """
    axes = [tuple(x) for x in (seeds, cases, views, scenarios)]
    conditions, metrics = tuple(tuple(c) for c in conditions), tuple(metrics)
    for axis in (*axes, conditions, metrics):
        if not axis or len(set(axis)) != len(axis):
            raise ValueError("expected census axes/conditions/metrics must be unique and nonempty")
    if any(len(c) != 2 for c in conditions):
        raise ValueError("each condition must be (arm,policy)")
    indices = [{value: i for i, value in enumerate(axis)} for axis in axes]
    shape = tuple(len(axis) for axis in axes)
    data = {condition: {metric: np.empty(shape, dtype=np.float64) for metric in metrics} for condition in conditions}
    seen = {condition: np.zeros(shape, dtype=bool) for condition in conditions}
    for row_number, row in enumerate(rows):
        try:
            condition = (row["arm"], row["policy"])
            position = tuple(index[row[key]] for index, key in zip(indices, ("seed", "case", "view", "scenario")))
            if condition not in seen:
                raise KeyError(condition)
            if seen[condition][position]:
                raise ValueError(f"duplicate policy/replay row at row {row_number}: {condition}, {position}")
            for metric in metrics:
                value = float(row[metric])
                if not math.isfinite(value):
                    raise ValueError(f"non-finite metric at row {row_number}")
                if metric in ("joint_fact_correct", "required_output_complete") and value not in (0.0, 1.0):
                    raise ValueError("success/completion metrics must be binary row indicators")
                data[condition][metric][position] = value
            seen[condition][position] = True
        except KeyError as error:
            raise ValueError(f"missing field or out-of-census identity at row {row_number}: {error}") from error
    missing = {str(c): int((~mask).sum()) for c, mask in seen.items() if not mask.all()}
    if missing:
        raise ValueError(f"incomplete balanced census: missing rows {missing}")
    return data


@dataclass(frozen=True)
class CrossedBootstrap:
    seed_indices: np.ndarray
    source_indices: np.ndarray
    random_seed: int
    sha256: str


def crossed_bootstrap(training_seed_count, source_pair_count, *, replicates=4000, seed=20261024):
    if any(not isinstance(n, int) or n < 1 for n in (training_seed_count, source_pair_count)) or not isinstance(replicates, int) or replicates < 2:
        raise ValueError("positive seed/source counts and at least two replicates are required")
    rng = np.random.Generator(np.random.PCG64(seed))
    si = rng.integers(training_seed_count, size=(replicates, training_seed_count), dtype=np.int64)
    ci = rng.integers(source_pair_count, size=(replicates, source_pair_count), dtype=np.int64)
    digest = hashlib.sha256(f"{si.shape}:{ci.shape}".encode() + si.astype("<i8").tobytes() + ci.astype("<i8").tobytes()).hexdigest()
    si.setflags(write=False)
    ci.setflags(write=False)
    return CrossedBootstrap(si, ci, int(seed), digest)


def _plan(shape, plan, replicates, seed, confidence, batch_size):
    if not 0 < confidence < 1 or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("confidence must be in (0,1) and batch_size a positive integer")
    plan = plan if plan is not None else crossed_bootstrap(shape[0], shape[1], replicates=replicates, seed=seed)
    si, ci = plan.seed_indices, plan.source_indices
    if si.ndim != 2 or ci.ndim != 2 or len(si) < 2 or si.shape != (len(si), shape[0]) or ci.shape != (len(si), shape[1]) or si.dtype.kind not in "iu" or ci.dtype.kind not in "iu" or (si < 0).any() or (si >= shape[0]).any() or (ci < 0).any() or (ci >= shape[1]).any():
        raise ValueError("bootstrap plan does not match the paired seed/source axes")
    return plan


def _counts(shape):
    return {"training_seeds": shape[0], "source_pairs": shape[1], "within_source_shape": list(shape[2:]), "observed_rows": math.prod(shape), "rows_or_seed_times_sources_are_independent_n": False}


def _bootstrap_metadata(plan):
    return {"replicates": len(plan.seed_indices), "random_seed": plan.random_seed, "generator": "PCG64", "numpy_version": np.__version__, "paired_indices_sha256": plan.sha256, "resampling": "independently resample seed and source axes; use identical indices for both conditions; keep all within-source observations together", "confirmatory_coverage_guaranteed": False, "scope": "few-seed crossed percentile bootstrap; 97.5% is nominal for the registered two-comparison family, other intervals are descriptive"}


def summarize_utility(values, gamma=2.0):
    cube = _cube(values)
    source_ce = _ce(cube.reshape(*cube.shape[:2], -1), gamma)
    joint = _ce(source_ce, gamma)
    conditional = _ce(cube, gamma).mean(axis=(1, 2))
    return {"gamma": float(gamma), "joint_ce": float(joint.mean()), "joint_ce_per_seed": joint.tolist(), "mean_conditional_ce": float(conditional.mean()), "mean_conditional_ce_per_seed": conditional.tolist(), "mean_utility": float(cube.mean()), "counts": _counts(cube.shape), "risk_hierarchy": "CE within each trained seed, then arithmetic mean across seeds; conditional CE uses generation scenarios within each source/view only"}


def _source_statistic(cube, estimand, gamma):
    if estimand == "joint_ce":
        return _ce(cube.reshape(*cube.shape[:2], -1), gamma)
    if estimand == "mean_conditional_ce":
        return _ce(cube, gamma).mean(axis=2)
    if estimand == "success_rate":
        if not np.isin(cube, (0.0, 1.0)).all():
            raise ValueError("success_rate requires binary observations")
    elif estimand != "loss_reduction":
        raise ValueError("unknown paired estimand")
    return cube.mean(axis=(2, 3))


def paired_comparison(candidate, reference, *, estimand="joint_ce", gamma=2.0, confidence=0.95, replicates=4000, bootstrap_seed=20261024, batch_size=256, bootstrap=None):
    """A positive gain always favors candidate; aligned frozen axes are required.

    A supplied CrossedBootstrap overrides replicates/seed and can be reused for
    every arm, policy and metric. Source-level CE preaggregation is exactly
    equivalent to flat within-seed CE because every source has the same mass.
    Indeed exp(-gamma * CE_source) is its average exponential utility, so an
    average across sources is exactly the average across all their outputs.
    No bootstrap resampling is performed within source views/scenarios.
    """
    candidate, reference = _cube(candidate), _cube(reference)
    if candidate.shape != reference.shape:
        raise ValueError("paired conditions must have identical balanced census shapes")
    plan = _plan(candidate.shape, bootstrap, replicates, bootstrap_seed, confidence, batch_size)
    a, b = _source_statistic(candidate, estimand, gamma), _source_statistic(reference, estimand, gamma)
    nonlinear = estimand == "joint_ce"
    per_seed_a = _ce(a, gamma) if nonlinear else a.mean(axis=-1)
    per_seed_b = _ce(b, gamma) if nonlinear else b.mean(axis=-1)
    sign = -1 if estimand == "loss_reduction" else 1
    draws = np.empty(len(plan.seed_indices))
    for start in range(0, len(draws), batch_size):
        si, ci = plan.seed_indices[start:start + batch_size, :, None], plan.source_indices[start:start + batch_size, None, :]
        aa, bb = a[si, ci], b[si, ci]
        av = _ce(aa, gamma).mean(axis=-1) if nonlinear else aa.mean(axis=(1, 2))
        bv = _ce(bb, gamma).mean(axis=-1) if nonlinear else bb.mean(axis=(1, 2))
        draws[start:start + len(av)] = sign * (av - bv)
    alpha = (1 - confidence) / 2
    interval = np.quantile(draws, (alpha, 1 - alpha), method="linear").tolist()
    gain = float(sign * (per_seed_a.mean() - per_seed_b.mean()))
    result = {"estimand": estimand, "candidate_value": float(per_seed_a.mean()), "reference_value": float(per_seed_b.mean()), "gain": gain, "gain_direction": "reference loss minus candidate loss" if sign < 0 else "candidate minus reference", "positive_gain_favors_candidate": True, "confidence": confidence, "interval": interval, "per_seed_gain": (sign * (per_seed_a - per_seed_b)).tolist(), "counts": _counts(candidate.shape), "bootstrap": _bootstrap_metadata(plan)}
    if estimand == "success_rate":
        result.update({"gain_units": "probability difference, not relative percent change", "gain_percentage_points": 100 * gain, "interval_percentage_points": [100 * x for x in interval]})
    return result


def fractional_tail(values, fraction=0.1):
    """Upper-loss CVaR with exact fractional boundary mass; P95 uses linear quantile."""
    if np.ma.isMaskedArray(values) and np.any(np.ma.getmaskarray(values)):
        raise ValueError("masked/missing tail observations violate the complete census")
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    if not len(values) or not np.isfinite(values).all() or not 0 < fraction <= 1:
        raise ValueError("tail needs finite observations and fraction in (0,1]")
    descending = np.sort(values)[::-1]
    mass = fraction * len(values)
    full = math.floor(mass)
    boundary = mass - full
    total = descending[:full].sum() + (boundary * descending[full] if boundary > 0 and full < len(values) else 0.0)
    return {"n": len(values), "mean": float(values.mean()), "p95": float(np.quantile(values, 0.95, method="linear")), "cvar": float(total / mass), "tail_fraction": fraction, "tail_mass": mass, "full_tail_observations": full, "boundary_mass": boundary, "quantile_method": "linear"}


def loss_tails(values, fraction=0.1):
    cube = _cube(values)
    if (cube < 0).any():
        raise ValueError("loss tails require nonnegative losses")
    output = [fractional_tail(seed, fraction) for seed in cube]
    source = [fractional_tail(seed.mean(axis=(1, 2)), fraction) for seed in cube]
    return {"counts": _counts(cube.shape), "output_level": {"per_seed": output, "mean_across_seed_summaries": {k: float(np.mean([r[k] for r in output])) for k in ("mean", "p95", "cvar")}, "equal_seed_mixture": fractional_tail(cube, fraction)}, "source_mean_level": {"per_seed": source, "mean_across_seed_summaries": {k: float(np.mean([r[k] for r in source])) for k in ("mean", "p95", "cvar")}, "source_means_averaged_across_seeds": fractional_tail(cube.mean(axis=(0, 2, 3)), fraction)}, "scope": "descriptive exact empirical tails; source averaging changes the estimand; equal-seed mixture is not the generation-risk CE and is not the average per-seed tail"}


def cost_summary(costs, *, reference=None, unit="ms", confidence=0.95, replicates=4000, bootstrap_seed=20261024, batch_size=64, bootstrap=None):
    """Costs are [seed,source,...within-source timing axes], e.g. view/scenario/round.

    A supplied reference uses the same paired resamples; differences are
    candidate minus reference, so positive means greater cost. Caller validates
    timing round identities/census and matches quality cases before this call.
    No timing outlier is removed. This is not a utility price or a cost-CE.
    """
    inputs = (costs,) if reference is None else (costs, reference)
    if any(np.ma.isMaskedArray(x) and np.any(np.ma.getmaskarray(x)) for x in inputs):
        raise ValueError("masked/missing costs violate the complete census")
    arrays = [np.asarray(x, dtype=np.float64) for x in inputs]
    shape = arrays[0].shape
    if len(shape) < 3 or min(shape) < 1 or any(a.shape != shape or not np.isfinite(a).all() or (a < 0).any() for a in arrays):
        raise ValueError("costs must be aligned complete finite nonnegative [seed,source,...]")
    plan = _plan(shape, bootstrap, replicates, bootstrap_seed, confidence, batch_size)
    points = [np.array([a.mean(), *np.quantile(a, (0.5, 0.95), method="linear")]) for a in arrays]
    point = points[0] if reference is None else points[0] - points[1]
    flattened = [a.reshape(*shape[:2], -1) for a in arrays]
    draws = np.empty((len(plan.seed_indices), 3))
    for start in range(0, len(draws), batch_size):
        si, ci = plan.seed_indices[start:start + batch_size, :, None], plan.source_indices[start:start + batch_size, None, :]
        estimates = []
        for a in flattened:
            samples = a[si, ci]
            quantiles = np.quantile(samples, (0.5, 0.95), axis=(1, 2, 3), method="linear")
            estimates.append(np.column_stack((samples.mean(axis=(1, 2, 3)), quantiles[0], quantiles[1])))
        draws[start:start + len(estimates[0])] = estimates[0] if reference is None else estimates[0] - estimates[1]
    alpha = (1 - confidence) / 2
    intervals = np.quantile(draws, (alpha, 1 - alpha), axis=0, method="linear")
    names = ("mean", "p50", "p95")
    return {"unit": unit, "estimand": "absolute_cost" if reference is None else "candidate_minus_reference_cost", "positive_difference_is_greater_cost": reference is not None, "point_estimates": dict(zip(names, point.tolist())), "candidate": dict(zip(names, points[0].tolist())), "reference": None if reference is None else dict(zip(names, points[1].tolist())), "confidence": confidence, "intervals": {name: intervals[:, i].tolist() for i, name in enumerate(names)}, "counts": _counts(shape), "bootstrap": _bootstrap_metadata(plan), "quantile_method": "linear", "outlier_deletion": False}
