"""A paid second observation, terminal repair, and matched feedback pathways.

Terminal tails describe the remaining error relative to +/-sqrt(repair cost).
They do not describe first passage or a communication event. Action values use
expected squared-error reduction. Private targets never enter policy methods.
"""

import hashlib
import itertools
import json
import math

import numpy as np
from scipy.special import ndtr

from ..feedback_chain import native_features


ARMS = ("gaussian", "probit", "event", "quantized", "numeric", "analytic", "history", "zero", "reset")
LEARNED = ("numeric", "analytic", "history", "zero", "reset")
NATIVE_ARMS = ("numeric", "analytic", "zero", "reset")
Q24 = 1 << 24
STEP = 1.0 / 4096
POWERS = tuple(p for p in itertools.product(range(4), repeat=3) if sum(p) <= 3)
L2 = (0.001, 0.01, 0.1)
OFFSETS = (-0.1, -0.05, 0.0, 0.05, 0.1)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_dataset(seed, n, split):
    if split not in ("train", "development", "confirmation", "runtime_confirmation") or type(n) is not int or n < 1:
        raise ValueError("Declared split and positive row count required")
    rng = np.random.default_rng(seed)
    initial, error = rng.normal(size=(2, n))
    error *= 0.8
    variance = rng.choice([0.04, 0.36, 1.44], n)
    wait_variance = rng.choice([0.04, 0.16, 0.64], n)
    cost, wait_cost = rng.choice([0.03, 0.12, 0.48], n), rng.choice([0.01, 0.04, 0.12], n)
    target = initial + error
    return {"initial_output": initial, "self_evaluation": target + np.sqrt(variance) * rng.normal(size=n),
            "wait_evaluation": target + np.sqrt(wait_variance) * rng.normal(size=n),
            "sensor_variance": variance, "wait_variance": wait_variance,
            "repair_cost": cost, "wait_cost": wait_cost, "target": target,
            "ids": np.asarray([f"feedback3:{split}:{seed}:{i}" for i in range(n)]),
            "seed": int(seed), "split": split, "law": "gaussian_error_paid_independent_sensor_v3"}


def posterior(calibration, public, dense=False):
    """Condition the same constant latent error on one or two acquired sensors."""
    alpha, scale = calibration["error_variance"], calibration["noise_scale"]
    if not all(math.isfinite(x) and x > 0 for x in (alpha, scale)):
        raise ValueError("Finite positive learned prior/noise variances required")
    observations = np.asarray(public["residuals"], float)
    variances = np.asarray(public["variances"], float) * scale
    if (observations.shape != variances.shape or observations.ndim != 1 or not 1 <= len(observations) <= 2
            or not np.isfinite(observations).all() or not np.isfinite(variances).all() or np.any(variances <= 0)):
        raise ValueError("Only acquired finite observations and positive variances accepted")
    if dense:
        covariance = np.diag(variances) + alpha
        solved = np.linalg.solve(covariance, np.column_stack((observations, np.full(len(observations), alpha))))
        return float(alpha * solved[:, 0].sum()), float(alpha - alpha * solved[:, 1].sum())
    precision = 1 / alpha + np.sum(1 / variances)
    return float(np.sum(observations / variances) / precision), float(1 / precision)


def positive_square_expectation(mean, variance, cost):
    """E[(Z^2-cost)+] for a normal Z; independently checked by quadrature."""
    if not all(math.isfinite(x) for x in (mean, variance, cost)) or variance < 0 or cost <= 0:
        raise ValueError("Finite normal moments and positive action cost required")
    if variance == 0:
        value = max(mean * mean - cost, 0.0)
        if not math.isfinite(value):
            raise ValueError("Positive square payoff exceeds finite numerical domain")
        return value
    sigma, cutoff = math.sqrt(variance), math.sqrt(cost)
    upper, lower = (cutoff - mean) / sigma, (-cutoff - mean) / sigma
    phi = lambda z: math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    tail = float(ndtr(-upper) + ndtr(lower))
    first = phi(upper) - phi(lower)
    second = tail + upper * phi(upper) - lower * phi(lower)
    value = (mean * mean - cost) * tail + 2 * mean * sigma * first + variance * second
    if not math.isfinite(value):
        raise ValueError("Positive square payoff exceeds finite numerical domain")
    return max(0.0, value)


def action_values(mean, variance, public, calibration):
    amount = round(mean * Q24) / Q24
    repair = 2 * amount * mean - amount * amount - public["repair_cost"]
    future_sensor = calibration["noise_scale"] * public["wait_variance"]
    mean_variance = variance * variance / (variance + future_sensor)
    wait = positive_square_expectation(mean, mean_variance, public["repair_cost"]) - public["wait_cost"]
    return {"repair_amount": amount, "repair_gain": repair, "wait_gain": wait}


def raw_features(public):
    precision = sum(1 / v for v in public["variances"])
    residual = sum(x / v for x, v in zip(public["residuals"], public["variances"])) / precision
    return np.asarray([residual, math.log(1 / precision), math.log(public["repair_cost"])])


def feature(public, law, arm, calibration, native, case):
    if arm not in LEARNED:
        return None, []
    z = (raw_features(public) - calibration["public_center"]) / calibration["public_scale"]
    if arm == "history":
        polynomial = [float(np.prod(z ** power)) for power in POWERS]
        radial = np.exp(-0.5 * np.sum((np.asarray(calibration["history_centers"]) - z) ** 2, axis=1))
        return np.concatenate((polynomial, radial)), []
    probability = law["probabilities"]
    drives = np.tanh(z / 3) if arm == "numeric" else np.asarray(
        [probability[2] - probability[0], 2 * probability[1] - 1, math.tanh(z[2] / 3)])
    if arm == "zero":
        drives = np.zeros(3)
    rows, vector = [], []
    for channel, drive in enumerate(drives):
        count = int(round(float(drive) * Q24))
        row = native.tick_pair(case + f"/channel{channel}", digest(public), count,
                               reset_before_readout=arm == "reset")
        row.update(channel=channel, drive_q24=count, public_sha256=digest(public))
        rows.append(row)
        vector.extend(native_features(row))
    return np.asarray(vector), rows


def choose(model, arm, public, law, vector):
    values = action_values(law["mean"], law["variance"], public, model["calibration"])
    score = values["repair_gain"]
    if arm in LEARNED:
        head = model["heads"][arm]
        score = float(np.dot(vector, head["weights"])) + head["offset"]
    scores = {"stop": 0.0, "repair": score}
    if len(public["residuals"]) == 1:
        scores["wait"] = values["wait_gain"]
    choice = max(scores, key=scores.get)
    return choice, values, scores


def fit_head(train_x, train_gain, dev_x, dev_gain, dev_wait, dev_stop):
    """MSE action-value fitting; dev selection scores complete two-stage outcomes."""
    center, scale = train_x.mean(0), train_x.std(0)
    center[0], scale[0] = 0.0, 1.0
    scale = np.where(scale > 1e-8, scale, 1.0)
    x = (train_x - center) / scale
    candidates = []
    for strength in L2:
        weights = np.zeros(x.shape[1])
        # The exact largest-eigenvalue step is stable for this convex quadratic.
        gram = x.T @ x / len(x)
        penalty = np.eye(len(weights)) * strength
        penalty[0, 0] = 0.0
        hessian, rhs = gram + penalty, x.T @ train_gain / len(x)
        rate = 0.9 / max(float(np.linalg.eigvalsh(hessian)[-1]), 1e-8)
        for _ in range(600):
            gradient = hessian @ weights - rhs
            weights -= rate * gradient
        raw = weights / scale
        raw[0] -= float(np.dot(raw, center))
        predicted = (dev_x @ raw).reshape(-1, 2)
        for offset in OFFSETS:
            score = predicted + offset
            first = np.argmax(np.column_stack((np.zeros(len(score)), score[:, 0], dev_wait)), axis=1)
            second_repair = score[:, 1] > 0
            utility = dev_stop + np.where(first == 1, dev_gain[:, 0],
                np.where(first == 2, -dev_gain[:, 2] + second_repair * dev_gain[:, 1], 0))
            candidates.append({"l2": strength, "offset": offset, "weights": raw.tolist(),
                "development_utility": float(utility.mean()), "development_waits": int(np.sum(first == 2)),
                "training_mse": float(np.mean((train_x @ raw - train_gain) ** 2)),
                "gradient_norm": float(np.linalg.norm(gradient)), "steps": 600, "learning_rate": rate})
    chosen = max(candidates, key=lambda c: (c["development_utility"], c["l2"], -abs(c["offset"])))
    return {k: chosen[k] for k in ("weights", "offset", "l2")}, {
        "candidates": candidates, "selection": {k: v for k, v in chosen.items() if k != "weights"},
        "parameter_l2_change": float(np.linalg.norm(chosen["weights"])),
        "initial_weights_sha256": digest([0.0] * len(chosen["weights"])),
        "selected_weights_sha256": digest(chosen["weights"]),
        "training_feature_sha256": digest(train_x.tolist()), "training_gain_sha256": digest(train_gain.tolist())}
