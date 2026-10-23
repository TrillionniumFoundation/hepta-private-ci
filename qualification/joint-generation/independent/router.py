"""One-forward input routing with a fixed, public accounting profile.

The router observes RGB/instruction inputs before generation. Gain targets exist
only in ``fit``; no model probabilities or target labels enter ``route``. Work
units price the declared operations below, not hardware FLOPs, latency or energy.
Input copies, Python dispatch and serialization are outside this arithmetic
profile. Callers must also charge ``make_thumbnail`` when constructing low input.
"""

from dataclasses import dataclass

import numpy as np


WIDTH = 31
REGULARIZATIONS = (0.001, 0.01, 0.1)
PRICES = {"macs": 2, "scalar_ops": 1, "compare_ops": 1, "div_ops": 4,
          "sqrt_ops": 4, "exp_ops": 8, "log_ops": 8, "tanh_ops": 8, "pow_ops": 8}


def _rows(rows):
    if type(rows) is not int or not 1 <= rows <= 65536:
        raise ValueError("bounded positive row count required")
    return rows


def priced_units(work):
    return sum(PRICES[key] * work.get(key, 0) for key in PRICES)


def _combined(*items):
    value = {key: sum(item.get(key, 0) for item in items) for key in PRICES}
    value["counts"] = {}
    for item in items:
        for key, count in item.get("counts", {}).items():
            value["counts"][key] = value["counts"].get(key, 0) + count
    return value


def thumbnail_work(rows):
    """Input validation plus 48 RGB means: 3 adds and 1 div per 2x2 block."""
    rows = _rows(rows)
    return {"scalar_ops": (144 + 1212) * rows, "compare_ops": 1205 * rows,
            "div_ops": 48 * rows,
            "counts": {"thumbnail_rows": rows, "thumbnail_rgb_blocks": 48 * rows,
                       "thumbnail_arithmetic_scalar_terms": 144 * rows}}


def feature_work(rows):
    """Reuse RGB means for std; predicate/reduction ceilings are included.

    Arithmetic per row: mean 189 adds; std 573 scalar ops; horizontal and
    vertical differences 501 each; left/right and top/bottom 189 each; full-low
    squared residual 573. These use 27 divisions and 3 square roots. Validation
    includes finite/range/instruction predicates and conservative reductions.
    """
    rows = _rows(rows)
    return {"scalar_ops": (2715 + 1212) * rows, "compare_ops": 1205 * rows,
            "div_ops": 27 * rows, "sqrt_ops": 3 * rows,
            "counts": {"router_feature_rows": rows, "router_feature_values": WIDTH * rows,
                       "rgb_feature_scalar_terms": 2715 * rows}}


def prediction_work(rows):
    rows = _rows(rows)
    return {"macs": WIDTH * rows, "scalar_ops": (WIDTH + 1) * rows,
            "div_ops": WIDTH * rows, "compare_ops": 2 * rows,
            "counts": {"router_predictions": rows}}


def fit_work(rows):
    """Declared normalization, ridge Gram/RHS and fixed-loop Cholesky solve.

    Feature extraction is separate. Cholesky avoids a hidden data-dependent
    pivoting solver: the public ledger includes every triangular dot product,
    subtraction, division and square root performed by the implementation.
    """
    n = _rows(rows)
    f = WIDTH
    factor_macs = f * (f - 1) * (f + 1) // 6
    solve_macs = factor_macs + f * (f - 1)
    factor_entries = f * (f + 1) // 2
    normalization = 2 * f * (n - 1) + 2 * n * f + (n - 1) + n + f + 1
    return {"macs": n * (f * f + f) + solve_macs,
            "scalar_ops": normalization + factor_entries + 2 * f + 3 * n + 512,
            "div_ops": n * f + 2 * f + 1 + f * (f - 1) // 2 + 2 * f,
            "sqrt_ops": 2 * f,
            "compare_ops": 4 * n + 500,
            "counts": {"router_fit_rows": n, "router_ridge_features": f,
                       "router_ridge_gram_cells": f * f, "router_fits": 1}}


def _inputs(low, full):
    low, full = np.asarray(low, dtype=np.float64), np.asarray(full, dtype=np.float64)
    if (low.ndim != 2 or full.shape != low.shape or low.shape[1] != 202
            or not 1 <= len(low) <= 65536):
        raise ValueError("matching bounded RGB/instruction matrices required")
    for values in (low, full):
        if (not np.isfinite(values).all() or np.any(values[:, :192] < 0)
                or np.any(values[:, :192] > 1)):
            raise ValueError("finite normalized RGB inputs required")
    words = full[:, 192:]
    if (not np.array_equal(words, low[:, 192:]) or not np.all((words == 0) | (words == 1))
            or any(np.any(words[:, section].sum(axis=1) != 1)
                   for section in (slice(0, 4), slice(4, 7), slice(7, 10)))):
        raise ValueError("matching one-hot instruction words required")
    return low, full


def _features(low, full):
    image = full[:, :192].reshape(-1, 8, 8, 3)
    mean = image.mean(axis=(1, 2))
    centered = image - mean[:, None, None, :]
    std = np.sqrt((centered * centered).mean(axis=(1, 2)))
    horizontal = np.abs(image[:, :, 1:] - image[:, :, :-1]).mean(axis=(1, 2))
    vertical = np.abs(image[:, 1:] - image[:, :-1]).mean(axis=(1, 2))
    left_right = image[:, :, :4].mean(axis=(1, 2)) - image[:, :, 4:].mean(axis=(1, 2))
    top_bottom = image[:, :4].mean(axis=(1, 2)) - image[:, 4:].mean(axis=(1, 2))
    residual = (full[:, :192] - low[:, :192]).reshape(-1, 8, 8, 3)
    residual = (residual * residual).mean(axis=(1, 2))
    return np.column_stack((full[:, 192:], mean, std, horizontal, vertical,
                            left_right, top_bottom, residual))


def _charge(ledger, stage, kernel, work):
    if ledger is not None:
        ledger.charge_kernel(stage, kernel, **work)


def make_thumbnail(full, *, ledger=None, stage="input_preprocess"):
    # Input validation is explicitly included here and again when the two input
    # matrices enter the router; neither actual validation call is free.
    full = np.asarray(full, dtype=np.float64)
    _inputs(full, full)
    _charge(ledger, stage, "rgb_thumbnail", thumbnail_work(len(full)))
    image = full[:, :192].reshape(-1, 4, 2, 4, 2, 3).mean(axis=(2, 4))
    image = image.repeat(2, axis=1).repeat(2, axis=2)
    return np.column_stack((image.reshape(-1, 192), full[:, 192:]))


def input_features(low, full, *, ledger=None, stage="router"):
    low, full = _inputs(low, full)
    _charge(ledger, stage, "router_features", feature_work(len(full)))
    return _features(low, full)


@dataclass(frozen=True)
class InputRouter:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    intercept: float
    bounds: np.ndarray
    regularization: float

    def __post_init__(self):
        for name, shape in (("mean", (WIDTH,)), ("scale", (WIDTH,)),
                            ("weights", (WIDTH,)), ("bounds", (2,))):
            value = np.array(getattr(self, name), dtype=np.float64, copy=True)
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError("invalid input-router tensor")
            value.flags.writeable = False
            object.__setattr__(self, name, value)
        if (type(self.intercept) not in (int, float) or not np.isfinite(self.intercept)
                or abs(self.intercept) > 2 or np.any(np.abs(self.mean) > 2)
                or np.any((self.scale < 0.05) | (self.scale > 2))
                or np.any(np.abs(self.weights) > 1e6) or np.any(np.abs(self.bounds) > 2)
                or self.bounds[0] > self.bounds[1]
                or type(self.regularization) not in (int, float)
                or self.regularization not in REGULARIZATIONS):
            raise ValueError("invalid input-router normalization or profile")

    @classmethod
    def fit(cls, low, full, gains, *, regularization=0.01, ledger=None, stage="critic_fit"):
        low, full = _inputs(low, full)
        target = np.asarray(gains, dtype=np.float64)
        if (target.shape != (len(full),) or not np.isfinite(target).all()
                or np.any(np.abs(target) > 2) or type(regularization) not in (int, float)
                or regularization not in REGULARIZATIONS):
            raise ValueError("bounded training-only gains and fixed ridge candidate required")
        _charge(ledger, stage, "input_router_fit", _combined(feature_work(len(full)), fit_work(len(full))))
        observed = _features(low, full)
        mean = observed.mean(axis=0)
        centered = observed - mean
        scale = np.maximum(np.sqrt((centered * centered).mean(axis=0)), 0.05)
        normalized = centered / scale
        intercept = float(target.mean())
        gram = normalized.T @ normalized
        gram.flat[::WIDTH + 1] += regularization * len(observed)
        rhs = normalized.T @ (target - intercept)
        lower = np.zeros_like(gram)
        for i in range(WIDTH):
            for j in range(i + 1):
                value = gram[i, j] - np.dot(lower[i, :j], lower[j, :j])
                if i == j:
                    if value <= 0:
                        raise ValueError("ridge system is not positive definite")
                    lower[i, j] = np.sqrt(value)
                else:
                    lower[i, j] = value / lower[j, j]
        intermediate = np.empty(WIDTH)
        for i in range(WIDTH):
            intermediate[i] = (rhs[i] - np.dot(lower[i, :i], intermediate[:i])) / lower[i, i]
        weights = np.empty(WIDTH)
        for i in range(WIDTH - 1, -1, -1):
            weights[i] = (intermediate[i] - np.dot(lower[i + 1:, i], weights[i + 1:])) / lower[i, i]
        return cls(mean, scale, weights, intercept, np.array([target.min(), target.max()]), float(regularization))

    def _prediction(self, observed):
        return np.clip((observed - self.mean) / self.scale @ self.weights + self.intercept, *self.bounds)

    def predict_gain(self, low, full, *, ledger=None, stage="router"):
        low, full = _inputs(low, full)
        _charge(ledger, stage, "input_router_predict", _combined(feature_work(len(full)), prediction_work(len(full))))
        return self._prediction(_features(low, full))

    def route(self, low, full, *, threshold=0.0, ledger=None, stage="router"):
        if type(threshold) not in (int, float) or not np.isfinite(threshold):
            raise ValueError("finite routing threshold required")
        low, full = _inputs(low, full)
        work = _combined(feature_work(len(full)), prediction_work(len(full)),
                         {"compare_ops": len(full), "counts": {"router_decisions": len(full)}})
        _charge(ledger, stage, "input_router_route", work)
        return self._prediction(_features(low, full)) > threshold

    def to_arrays(self):
        return {"router_version": np.array([1], dtype=np.int64),
                "router_profile": np.array([1], dtype=np.int64),
                "router_mean": self.mean, "router_scale": self.scale,
                "router_weights": self.weights, "router_bounds": self.bounds,
                "router_intercept": np.array([self.intercept]),
                "router_regularization": np.array([self.regularization])}

    @classmethod
    def from_arrays(cls, arrays):
        expected = {"router_version", "router_profile", "router_mean", "router_scale",
                    "router_weights", "router_bounds", "router_intercept", "router_regularization"}
        if set(arrays) != expected:
            raise ValueError("unknown or missing input-router arrays")
        for name in ("router_version", "router_profile"):
            value = np.asarray(arrays[name])
            if value.shape != (1,) or value.dtype.kind not in "iu" or value[0] != 1:
                raise ValueError("unsupported input-router profile")
        for name in expected - {"router_version", "router_profile"}:
            value = np.asarray(arrays[name])
            if value.dtype != np.float64:
                raise ValueError("input-router arrays require float64")
        for name in ("router_intercept", "router_regularization"):
            if np.asarray(arrays[name]).shape != (1,):
                raise ValueError("invalid input-router scalar shape")
        return cls(arrays["router_mean"], arrays["router_scale"], arrays["router_weights"],
                   float(arrays["router_intercept"][0]), arrays["router_bounds"],
                   float(arrays["router_regularization"][0]))
