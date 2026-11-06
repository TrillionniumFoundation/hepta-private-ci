"""Seven registered gamma-2 contrasts; arithmetic is not custody evidence."""

import math

import numpy as np


METHODS = ("00", "10", "01", "11", "greedy", "planner", "retrieval")
CONTRASTS = (
    "controller_given_generator_training",
    "controller_given_frozen_generator",
    "generator_given_fixed_controller",
    "joint_vs_baseline",
    "interaction",
    "generator_given_controller_training",
    "joint_vs_strong_reference",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ce(values, gamma=2.0):
    values = np.asarray(values, dtype=np.float64)
    require(values.size > 0 and np.isfinite(values).all(), "nonfinite or empty return")
    require(gamma == 2.0, "the inherited gamma is fixed at 2")
    worst = float(values.min())
    return worst - math.log(float(np.exp(-gamma * (values - worst)).mean())) / gamma


def contrasts(arm_values, reference):
    require(reference in ("00", "greedy", "planner", "retrieval"), "unsealed strong reference")
    require(set(arm_values) == set(METHODS), "all seven reported methods required")
    a, b, c, d = (arm_values[m] for m in ("00", "10", "01", "11"))
    return dict(zip(CONTRASTS, (d-c, b-a, c-a, d-a, d-b-c+a, d-b, d-arm_values[reference]), strict=True))


def _weighted_ce(matrix, fit_counts, cluster_counts):
    """matrix is fit,cluster,draw,method; weights preserve both nested draws.

    Use one stable arm shift in the fast path. Rare resamples excluding every
    low-return cell can underflow that shift; recenter those particular samples
    on their actually selected cells instead of producing an infinite CE.
    """
    fit_counts = np.asarray(fit_counts, dtype=np.int64)
    cluster_counts = np.asarray(cluster_counts, dtype=np.int64)
    require(fit_counts.ndim == cluster_counts.ndim == 2, "bootstrap weight dimensions")
    require(fit_counts.shape[0] == cluster_counts.shape[0], "paired bootstrap batch")
    require(fit_counts.shape[1] == matrix.shape[0], "fit count dimensions")
    require(cluster_counts.shape[1] == matrix.shape[1], "cluster count dimensions")
    require((fit_counts >= 0).all() and (cluster_counts >= 0).all(), "negative bootstrap counts")
    require((fit_counts.sum(axis=1) == matrix.shape[0]).all(), "complete fit resample")
    require((cluster_counts.sum(axis=1) == matrix.shape[1]).all(), "complete cluster resample")
    shift = matrix.min(axis=(0, 1, 2))
    scaled = np.exp(-2.0 * (matrix - shift)).mean(axis=2)
    weight = np.einsum("bf,fcm,bc->bm", fit_counts, scaled, cluster_counts, optimize=True)
    denominator = matrix.shape[0] * matrix.shape[1]
    result = np.empty_like(weight)
    positive = weight > 0
    result[positive] = np.broadcast_to(shift, weight.shape)[positive] - np.log(weight[positive] / denominator) / 2.0
    for batch, method in np.argwhere(~positive):
        fs = np.flatnonzero(fit_counts[batch])
        cs = np.flatnonzero(cluster_counts[batch])
        values = matrix[fs[:, None], cs[None, :], :, method]
        local_shift = values.min()
        local_weights = fit_counts[batch, fs, None] * cluster_counts[batch, None, cs]
        mean_exp = float((np.exp(-2.0 * (values-local_shift)).mean(axis=2) * local_weights).sum()) / denominator
        result[batch, method] = local_shift - math.log(mean_exp) / 2.0
    require(np.isfinite(result).all(), "bootstrap numerical failure")
    return result


def crossed_analysis(matrix, reference, *, replicates=99999, seed=4835202611):
    matrix = np.asarray(matrix, dtype=np.float64)
    require(matrix.ndim == 4 and matrix.shape[2:] == (2, 7), "fit/source/two-draw/seven-method tensor required")
    require(matrix.shape[0] >= 2 and matrix.shape[1] >= 2, "at least two fits and source clusters required")
    require(np.isfinite(matrix).all(), "nonfinite panel")
    require(type(replicates) is int and 1 <= replicates <= 99999, "invalid bootstrap count")
    require(type(seed) is int and seed >= 0, "invalid bootstrap seed")
    f, c, _, _ = matrix.shape
    arm_ce = {m: ce(matrix[..., i]) for i, m in enumerate(METHODS)}
    arm_mean = {m: float(matrix[..., i].mean()) for i, m in enumerate(METHODS)}
    point = contrasts(arm_ce, reference)
    samples = {key: np.empty(replicates, dtype=np.float64) for key in CONTRASTS}
    rng = np.random.Generator(np.random.PCG64(seed))
    for start in range(0, replicates, 128):
        n = min(128, replicates-start)
        fw = rng.multinomial(f, np.full(f, 1.0/f), size=n)
        cw = rng.multinomial(c, np.full(c, 1.0/c), size=n)
        batch = _weighted_ce(matrix, fw, cw)
        values = contrasts({m: batch[:, i] for i, m in enumerate(METHODS)}, reference)
        for key, value in values.items():
            samples[key][start:start+n] = value
    tail = 0.05 / (2 * 7)
    lower = math.floor(tail * (replicates-1))
    upper = math.ceil((1-tail) * (replicates-1))
    intervals = {}
    for key, values in samples.items():
        values.sort()
        intervals[key] = [float(values[lower]), float(values[upper])]
    per_fit = []
    for fit in range(f):
        fit_values = {m: ce(matrix[fit, ..., i]) for i, m in enumerate(METHODS)}
        per_fit.append({"fit_index": fit, "contrasts": contrasts(fit_values, reference)})
    return {
        "ce": arm_ce, "mean_return": arm_mean, "contrasts": point,
        "familywise95_bonferroni_percentile_intervals": intervals,
        "per_fit_contrasts": per_fit,
        "bootstrap": {"replicates": replicates, "seed": seed, "generator": "NumPy PCG64",
                      "batch_size": 128, "tail_probability": tail,
                      "lower_order_statistic_zero_based": lower, "upper_order_statistic_zero_based": upper,
                      "unit": "complete fit and independent source cluster; nested draws and all methods stay paired"},
        "shape": {"fit_blocks": f, "source_clusters": c, "nested_draws": 2, "methods": 7},
        "limitations": ["Finite-sample plug-in CE and percentile intervals are not an exact coverage guarantee.",
                        "Repeated control outcomes across fit blocks are not new trained control models.",
                        "This calculation does not authenticate data, evaluator, execution, costs, or candidates.",
                        "No quality/safety floor or automatic promotion is implemented by this arithmetic."],
        "promotion_allowed": False,
    }
