"""A training-only affine raw-gain head over an already computed low state.

The content encoder is supplied by the caller and is never trained or evaluated
here. Work inventories are declared operator estimates, including a cubic ridge
solve estimate; they are not hardware FLOPs, memory traffic, CPU, or energy.
"""

from dataclasses import dataclass
import hashlib
from typing import ClassVar

import numpy as np

from control import Controller
from independent.accounting import WorkLedger


KIND = "low-hidden-instruction-affine-v1"
FIT_SCHEMA = "hepta.joint-generation.gain-head-fit.v1"
ARRAY_KEYS = frozenset(("gain_head_version", "gh_classes", "gh_hidden_dim", "gh_mean",
                        "gh_scale", "gh_weights", "gh_intercept", "gh_bounds"))


def _geometry(hidden_dim, n):
    if (type(hidden_dim) is not int or not 1 <= hidden_dim <= 512
            or type(n) is not int or not 1 <= n <= 65536):
        raise ValueError("bounded hidden dimension and nonempty row count required")
    return hidden_dim + 10


def _regularization(plan):
    config = plan["controller"] if "controller" in plan else plan
    value = config["ridge_regularization"]
    if (type(value) not in (int, float) or not np.isfinite(value) or not 0 < value <= 1):
        raise ValueError("finite positive ridge regularization required")
    if config.get("gain_head", KIND) != KIND:
        raise ValueError("unsupported affine gain-head specification")
    return float(value)


def head_work(hidden_dim, n):
    """Normalize, predict, clip and compare one routing decision per row.

    The first-pass hidden state already exists. This includes public finite
    input scans and the caller's gain > decision_price comparison, not another
    encoder evaluation or an unexecuted input gradient.
    """
    d = _geometry(hidden_dim, n)
    return {"macs": n * d, "scalar_ops": n * (d + 1),
            "div_ops": n * d, "compare_ops": n * d + 4 * n}


def fit_work(hidden_dim, n, plan):
    """One cached TRAIN normalizer and one ordinary unweighted ridge fit."""
    d = _geometry(hidden_dim, n)
    _regularization(plan)
    # Mean, cached centered rows, population variance, floor and normalize.
    # The target mean is both the intercept and the receipt's mean statistic.
    # Public finite/support checks and immutable result validation are included.
    return {"macs": n * d * d + n * d,
            "scalar_ops": (4 * n - 2) * d + 2 * n - 1 + d**3 + d + 1,
            "div_ops": (n + 2) * d + 1, "sqrt_ops": d,
            "compare_ops": n * d + 3 * n + 5 * d + 2}


def _readonly(value, shape, name):
    observed = np.asarray(value)
    if observed.shape != shape or observed.dtype.kind != "f" or observed.dtype.itemsize != 8:
        raise ValueError("invalid affine gain-head " + name + " tensor")
    if not np.isfinite(observed).all():
        raise ValueError("finite affine gain-head tensors required")
    result = np.array(observed, dtype=np.float64, copy=True, order="C")
    result.flags.writeable = False
    return result


def _hash(*values):
    digest = hashlib.sha256()
    for value in values:
        digest.update(np.asarray(value, dtype="<f8").tobytes(order="C"))
    return digest.hexdigest()


@dataclass(frozen=True)
class AffineGainHead:
    hidden_dim: int
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    intercept: float
    bounds: np.ndarray
    classes: ClassVar[int] = 12
    kind: ClassVar[str] = KIND

    def __post_init__(self):
        d = _geometry(self.hidden_dim, 1)
        for name, shape in (("mean", (d,)), ("scale", (d,)),
                            ("weights", (d,)), ("bounds", (2,))):
            object.__setattr__(self, name, _readonly(getattr(self, name), shape, name))
        if (type(self.intercept) not in (int, float) or not np.isfinite(self.intercept)
                or np.any(self.scale < 0.05) or self.bounds[0] > self.bounds[1]):
            raise ValueError("invalid affine gain-head normalization/support")
        object.__setattr__(self, "intercept", float(self.intercept))

    def _features(self, hidden, instruction):
        hidden, instruction = np.asarray(hidden, dtype=np.float64), np.asarray(instruction, dtype=np.float64)
        if (hidden.ndim != 2 or not 1 <= len(hidden) <= 65536
                or hidden.shape[1] != self.hidden_dim or instruction.shape != (len(hidden), 10)
                or not np.isfinite(hidden).all() or not np.isfinite(instruction).all()):
            raise ValueError("matching finite low hidden state and ten instruction features required")
        return np.concatenate((hidden, instruction), axis=1)

    def predict_state(self, hidden, instruction):
        observed = self._features(hidden, instruction)
        prediction = ((observed - self.mean) / self.scale) @ self.weights + self.intercept
        if not np.isfinite(prediction).all():
            raise ValueError("affine gain-head prediction overflow")
        return np.clip(prediction, *self.bounds)

    def work(self, n):
        return head_work(self.hidden_dim, n)

    def with_bounds(self, bounds):
        return type(self)(self.hidden_dim, self.mean, self.scale, self.weights,
                          self.intercept, np.asarray(bounds, dtype=np.float64))

    def to_arrays(self):
        arrays = {"gain_head_version": np.array([1], dtype=np.int64),
                  "gh_classes": np.array([self.classes], dtype=np.int64),
                  "gh_hidden_dim": np.array([self.hidden_dim], dtype=np.int64),
                  "gh_mean": self.mean, "gh_scale": self.scale, "gh_weights": self.weights,
                  "gh_intercept": np.array([self.intercept], dtype=np.float64), "gh_bounds": self.bounds}
        for value in arrays.values():
            value.flags.writeable = False
        return arrays

    @classmethod
    def from_arrays(cls, arrays):
        if set(arrays) != ARRAY_KEYS:
            raise ValueError("unknown or missing affine gain-head artifact fields")
        for key in ("gain_head_version", "gh_classes", "gh_hidden_dim"):
            value = np.asarray(arrays[key])
            if value.shape != (1,) or value.dtype.kind != "i" or value.dtype.itemsize != 8:
                raise ValueError("invalid affine gain-head integer metadata")
        if arrays["gain_head_version"][0] != 1 or arrays["gh_classes"][0] != 12:
            raise ValueError("unsupported affine gain-head version/classes")
        intercept = _readonly(arrays["gh_intercept"], (1,), "intercept")
        return cls(int(arrays["gh_hidden_dim"][0]), arrays["gh_mean"], arrays["gh_scale"],
                   arrays["gh_weights"], float(intercept[0]), arrays["gh_bounds"])

    @classmethod
    def fit(cls, hidden, instruction, target, plan, seed, ledger, stage="critic_fit"):
        hidden, instruction, target = (np.asarray(value, dtype=np.float64)
                                       for value in (hidden, instruction, target))
        if hidden.ndim != 2:
            raise ValueError("finite two-dimensional low hidden states required")
        n, hidden_dim = hidden.shape
        d = _geometry(hidden_dim, n)
        if (instruction.shape != (n, 10) or target.shape != (n,)
                or not np.isfinite(hidden).all() or not np.isfinite(instruction).all()
                or not np.isfinite(target).all()):
            raise ValueError("matching finite TRAIN hidden/instruction/raw-gain targets required")
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("bounded provenance seed required")
        if not isinstance(ledger, WorkLedger):
            raise TypeError("WorkLedger required for affine gain-head training")
        regularization = _regularization(plan)
        inventory = fit_work(hidden_dim, n, plan)
        charged = ledger.charge_kernel(stage, "affine_gain_head_fit", **inventory,
            counts={"critic_gain_head_fits": 1, "critic_feature_rows": n,
                    "critic_feature_elements": n * d, "critic_ridge_fits": 1,
                    "critic_ridge_rows": n, "critic_ridge_features": d,
                    "critic_ridge_gram_macs": n * d * d, "critic_ridge_rhs_macs": n * d})
        observed = np.concatenate((hidden, instruction), axis=1)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                mean = observed.mean(axis=0)
                centered = observed - mean
                scale = np.maximum(np.sqrt(np.mean(centered * centered, axis=0)), 0.05)
                normalized = centered / scale
                intercept = float(target.mean())
                gram = normalized.T @ normalized
                gram.flat[::d + 1] += regularization * n
                weights = np.linalg.solve(gram, normalized.T @ (target - intercept))
                bounds = np.array([target.min(), target.max()])
        except (FloatingPointError, np.linalg.LinAlgError) as error:
            raise ValueError("affine gain-head fit failed finite ridge equations") from error
        head = cls(hidden_dim, mean, scale, weights, intercept, bounds)
        receipt = {"schema": FIT_SCHEMA, "kind": KIND, "rows": n,
            "hidden_dim": hidden_dim, "input_dim": d, "ridge_regularization": regularization,
            "seed": seed, "work": inventory, "accounting_units": charged,
            "target": {"min": float(bounds[0]), "mean": intercept, "max": float(bounds[1]),
                       "sha256": _hash(target)},
            "features_sha256": _hash(observed), "normalizer_sha256": _hash(mean, scale),
            "weights_sha256": _hash(weights),
            "objective": "unweighted MSE plus ridge; intercept unpenalized; TRAIN population std floor .05",
            "content_encoder": "caller-provided low state; no encoder or input-gradient work here"}
        return head, receipt


def load_controller(arrays):
    """Load exactly one known controller artifact, preserving legacy support."""
    if "gain_head_version" in arrays:
        return AffineGainHead.from_arrays(arrays)
    if "ctrl_version" in arrays:
        return Controller.from_arrays(arrays)
    raise ValueError("unknown continuation controller artifact")
