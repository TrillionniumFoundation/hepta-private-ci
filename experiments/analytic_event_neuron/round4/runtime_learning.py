"""Fresh supervised mixture dynamics and matched native/history readout fits."""

import numpy as np
from scipy.special import logsumexp

from ..round3 import feedback as previous
from .runtime_law import make_law, validate_law


SEEDS = (1213, 1427, 1619, 1823, 2017)
DATA_OFFSET = 640000000
ARMS = ("event", "direct", "float", "gaussian", "probit", "analytic", "numeric", "history")
LEARNED = ("analytic", "numeric", "history")


def dataset(seed, n, split):
    if split not in ("train", "development", "confirmation", "qualification") or type(n) is not int or n < 1:
        raise ValueError("Declared split and positive row count required")
    code = {"train": 1, "development": 2, "confirmation": 3, "qualification": 4}[split]
    rng = np.random.default_rng(DATA_OFFSET + 1000 * seed + code)
    initial = rng.normal(size=n)
    component = rng.choice(2, n, p=[.65, .35])
    error = np.asarray([-.45, .85])[component] + np.sqrt(np.asarray([.09, .36])[component]) * rng.normal(size=n)
    variance, wait_variance = rng.choice([.04, .36, 1.44], n), rng.choice([.04, .16, .64], n)
    target = initial + error
    return {"initial_output": initial, "self_evaluation": target + np.sqrt(variance) * rng.normal(size=n),
            "wait_evaluation": target + np.sqrt(wait_variance) * rng.normal(size=n),
            "sensor_variance": variance, "wait_variance": wait_variance,
            "repair_cost": rng.choice([.03, .12, .48], n), "wait_cost": rng.choice([.01, .04, .12], n),
            "target": target, "ids": np.asarray([f"feedback4:{split}:{seed}:{i}" for i in range(n)]),
            "seed": seed, "split": split, "law": "two-component-gaussian-error-independent-paid-sensor.v4"}


def public_row(data, i, second=False):
    initial = float(data["initial_output"][i])
    result = {"initial": initial, "residuals": [float(data["self_evaluation"][i]) - initial],
              "variances": [float(data["sensor_variance"][i])],
              **{k: float(data[k][i]) for k in ("repair_cost", "wait_cost", "wait_variance")}}
    if second:
        result["residuals"].append(float(data["wait_evaluation"][i]) - initial)
        result["variances"].append(result["wait_variance"])
    return result


def fit_dynamics(data):
    errors = data["target"] - data["initial_output"]
    weights, means = np.array([.5, .5]), np.quantile(errors, [.25, .75])
    variances = np.full(2, max(float(np.var(errors)) / 2, .01))
    initial = make_law(weights, means, variances)
    losses = []
    for _ in range(80):
        logp = np.log(weights)[None, :] - .5 * (np.log(2 * np.pi * variances)[None, :]
               + (errors[:, None] - means[None, :]) ** 2 / variances[None, :])
        losses.append(float(-logsumexp(logp, axis=1).mean()))
        responsibilities = np.exp(logp - logsumexp(logp, axis=1)[:, None])
        mass = responsibilities.sum(0)
        weights = np.maximum(mass / len(errors), 1e-6)
        weights /= weights.sum()
        means = np.sum(responsibilities * errors[:, None], axis=0) / mass
        variances = np.maximum(np.sum(responsibilities * (errors[:, None] - means) ** 2, axis=0) / mass, 1e-4)
    order = np.argsort(means)
    prior = make_law(weights[order], means[order], variances[order])
    gaussian = make_law([1.0], [float(errors.mean())], [float(np.var(errors))])
    noise = np.concatenate(((data["self_evaluation"] - data["target"]) ** 2 / data["sensor_variance"],
                            (data["wait_evaluation"] - data["target"]) ** 2 / data["wait_variance"]))
    raw = np.asarray([previous.raw_features(public_row(data, i, bool(stage))) for i in range(len(errors)) for stage in range(2)])
    center, spread = raw.mean(0), np.maximum(raw.std(0), 1e-8)
    calibration = {"noise_scale": float(noise.mean()), "error_variance": float(np.var(errors)),
                   "public_center": center.tolist(), "public_scale": spread.tolist(),
                   "history_centers": ((raw - center) / spread)[np.linspace(0, len(raw) - 1, 43).astype(int)].tolist()}
    receipt = {"prior_initial": initial, "prior_final": prior, "em_steps": 80, "training_nll_by_iteration": losses,
               "gaussian_prior": gaussian, "noise_scale_initial": 1.0, "noise_scale_final": calibration["noise_scale"],
               "prior_parameters_changed": initial != prior, "training_rows": len(errors), "confirmation_used": False}
    return {"prior": prior, "gaussian_prior": gaussian, "calibration": calibration}, receipt


def gaussian_dense(prior, residuals, variances, noise_scale):
    weights, means, prior_variances = validate_law(prior)
    if len(weights) != 1:
        raise ValueError("Dense probit comparator requires K1 prior")
    mean, variance = means[0], prior_variances[0]
    noise = noise_scale * np.asarray(variances)
    covariance = np.diag(noise) + variance
    solution = np.linalg.solve(covariance, np.column_stack((np.asarray(residuals) - mean, np.full(len(noise), variance))))
    return make_law([1], [float(mean + variance * solution[:, 0].sum())], [float(variance - variance * solution[:, 1].sum())])
