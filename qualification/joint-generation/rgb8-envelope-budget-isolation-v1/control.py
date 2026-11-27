"""Training-only continuation critic for a bounded second image inference.

Runtime features contain only the first pass's content distributions. The caller
charges the critic and any selected second pass before executing them. This is a
qualification-local two-stage policy, not a general NDU control solver.
"""

from dataclasses import dataclass

import numpy as np


def features(p, q):
    p, q = np.asarray(p, dtype=np.float64), np.asarray(q, dtype=np.float64)
    if p.ndim != 2 or p.shape != q.shape or not 1 <= len(p) <= 65536:
        raise ValueError("matching nonempty probability batches required")
    if not 2 <= p.shape[1] <= 64:
        raise ValueError("class count outside bounded controller profile")
    for values in (p, q):
        if (not np.isfinite(values).all() or np.any(values < 0)
                or not np.allclose(values.sum(axis=1), 1, atol=1e-8, rtol=0)):
            raise ValueError("invalid content probabilities")
    summaries = []
    for values in (p, q):
        ordered = np.sort(values, axis=1)
        entropy = -(values * np.log(np.maximum(values, 1e-300))).sum(axis=1)
        summaries.extend((entropy / np.log(p.shape[1]),
                          ordered[:, -1] - ordered[:, -2], ordered[:, -1]))
    summaries.append((p * q).sum(axis=1))
    return np.column_stack((p, q, *summaries))


@dataclass(frozen=True)
class Controller:
    classes: int
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    intercept: float
    bounds: np.ndarray

    def __post_init__(self):
        if (isinstance(self.classes, (bool, np.bool_))
                or not isinstance(self.classes, (int, np.integer))
                or not 2 <= self.classes <= 64):
            raise ValueError("invalid controller class count")
        width = 2 * self.classes + 7
        for name, shape in (("mean", (width,)), ("scale", (width,)),
                            ("weights", (width,)), ("bounds", (2,))):
            value = np.array(getattr(self, name), dtype=np.float64, copy=True)
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError("invalid controller tensor")
            value.flags.writeable = False
            object.__setattr__(self, name, value)
        if (not np.isfinite(self.intercept) or np.any(self.scale <= 0)
                or self.bounds[0] > self.bounds[1]):
            raise ValueError("invalid controller normalization/support")

    def predict_gain(self, p, q):
        observed = features(p, q)
        if observed.shape[1] != len(self.weights):
            raise ValueError("controller/content model class mismatch")
        prediction = (observed - self.mean) / self.scale @ self.weights
        return np.clip(prediction + self.intercept, *self.bounds)

    def decide(self, p, q, remaining_steps, price=0.0):
        """Choose continue only when predicted gain exceeds its fixed price.

        Remaining steps means *additional* model forwards after the mandatory
        first pass. Only 0/1 is admitted, so no caller can request a third pass.
        Ties, absent budget, and non-positive expected net gain stop.
        """
        if not np.isscalar(price) or not np.isfinite(price) or price < 0:
            raise ValueError("price must be finite and nonnegative")
        gain = self.predict_gain(p, q)
        budget = np.asarray(remaining_steps)
        if budget.dtype.kind not in "iu" or budget.shape not in ((), gain.shape):
            raise ValueError("remaining steps must be integer scalar or batch")
        if np.any((budget < 0) | (budget > 1)):
            raise ValueError("only one additional inference is admitted")
        return (budget == 1) & (gain > price)

    def inference_operation_estimate(self, batch_size=1):
        """Conservative scalar-op count; log/sort are separately identified.

        This is an accounting estimate, not measured FLOPs or GPU time.
        """
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("positive integer batch size required")
        return {"scalar_operations": batch_size * (24 * self.classes + 40),
                "log_evaluations": batch_size * 2 * self.classes,
                "sort_items": batch_size * 2 * self.classes}

    def to_arrays(self):
        return {"ctrl_version": np.array([1], dtype=np.int64),
                "ctrl_classes": np.array([self.classes], dtype=np.int64),
                "ctrl_mean": self.mean, "ctrl_scale": self.scale,
                "ctrl_weights": self.weights,
                "ctrl_intercept": np.array([self.intercept]),
                "ctrl_bounds": self.bounds}

    @classmethod
    def from_arrays(cls, arrays):
        expected = {"ctrl_version", "ctrl_classes", "ctrl_mean", "ctrl_scale",
                    "ctrl_weights", "ctrl_intercept", "ctrl_bounds"}
        if set(arrays) != expected:
            raise ValueError("unknown or missing controller artifact fields")
        for name in ("ctrl_version", "ctrl_classes", "ctrl_intercept"):
            if np.asarray(arrays[name]).shape != (1,):
                raise ValueError("invalid controller metadata shape")
        if arrays["ctrl_version"][0] != 1:
            raise ValueError("unsupported controller artifact")
        classes = arrays["ctrl_classes"][0]
        if not np.isfinite(classes) or int(classes) != classes:
            raise ValueError("invalid serialized class count")
        return cls(int(classes), arrays["ctrl_mean"], arrays["ctrl_scale"],
                   arrays["ctrl_weights"], float(arrays["ctrl_intercept"][0]),
                   arrays["ctrl_bounds"])


def fit_controller(p, q, delta, regularization=1e-3):
    """Fit once on training-only measured full-minus-thumbnail utility.

    No outcome, target, or full-image prediction is accepted at inference time.
    Normalizers and support clipping are learned from this same training fold.
    """
    observed = features(p, q)
    target = np.asarray(delta, dtype=np.float64)
    if target.shape != (len(observed),) or not np.isfinite(target).all():
        raise ValueError("finite continuation targets required")
    if not np.isscalar(regularization) or not np.isfinite(regularization) or regularization <= 0:
        raise ValueError("positive finite ridge regularization required")
    mean, scale = observed.mean(axis=0), np.maximum(observed.std(axis=0), 0.05)
    normalized = (observed - mean) / scale
    intercept = float(target.mean())
    gram = normalized.T @ normalized
    gram.flat[::len(gram) + 1] += regularization * len(observed)
    weights = np.linalg.solve(gram, normalized.T @ (target - intercept))
    return Controller((observed.shape[1] - 7) // 2, mean, scale, weights, intercept,
                      np.array([target.min(), target.max()]))
