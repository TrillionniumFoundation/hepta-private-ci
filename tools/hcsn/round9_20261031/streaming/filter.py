"""Streaming implementation of the frozen R8 known-model Bayes risk task.

Two statistics are sufficient because the future path is conditionally new,
not a censored continuation of the observed sensor path. This implementation
applies equally to the calibrated analytic arm and the ordinary exact filter.
"""

import hashlib
import json

import numpy as np
from scipy.special import log_ndtr, softmax

MODES = np.array([-.8, 0., .8], dtype=np.float64)
PRIOR = np.array([.3, .4, .3], dtype=np.float64)
CONTRACT = "r8-independent-future-three-mode-bayes-v1"


class StreamingFilter:
    def __init__(self, size=1, parameters=None):
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ValueError("size must be a positive integer")
        parameters = parameters or {"log_scales": [0., 0.], "prior_shift": [0., 0., 0.]}
        if set(parameters) != {"log_scales", "prior_shift"}:
            raise ValueError("unknown filter parameter")
        self.log_scales = np.asarray(parameters["log_scales"], dtype=np.float64).copy()
        self.prior_shift = np.asarray(parameters["prior_shift"], dtype=np.float64).copy()
        if self.log_scales.shape != (2,) or self.prior_shift.shape != (3,):
            raise ValueError("invalid parameter shape")
        if not np.isfinite(self.log_scales).all() or not np.isfinite(self.prior_shift).all():
            raise ValueError("nonfinite parameters")
        self.scales = np.exp(self.log_scales)
        if not np.isfinite(self.scales).all() or not (self.scales > 0).all():
            raise ValueError("unrepresentable scales")
        self.a = np.zeros(size)
        self.b = np.zeros(size)
        self.a_error = np.zeros(size)
        self.b_error = np.zeros(size)
        self.count = np.zeros(size, dtype=np.int64)

    @property
    def identity(self):
        payload = {"contract": CONTRACT, "log_scales": self.log_scales.tolist(),
                   "prior_shift": self.prior_shift.tolist()}
        return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()

    @property
    def state_bytes(self):
        return sum(x.nbytes for x in (self.a, self.b, self.a_error, self.b_error, self.count))

    def update(self, history, lengths=None):
        """Consume a new block shaped (streams, observations, 3), once only.

        Each observation is (increment, elapsed time, sensor standard deviation).
        lengths counts valid leading observations per stream, allowing padding.
        Validation completes before mutating any accumulator.
        """
        x = np.asarray(history, dtype=np.float64)
        if x.ndim != 3 or x.shape[0] != len(self.a) or x.shape[2] != 3:
            raise ValueError("history shape must be (streams, observations, 3)")
        if lengths is None:
            lengths = np.full(len(self.a), x.shape[1], dtype=np.int64)
        lengths = np.asarray(lengths)
        if (lengths.shape != self.count.shape or lengths.dtype.kind not in "iu"
                or (lengths < 0).any() or (lengths > x.shape[1]).any()):
            raise ValueError("invalid observation lengths")
        lengths = lengths.astype(np.int64, copy=False)
        active = np.arange(x.shape[1])[None, :] < lengths[:, None]
        if not np.isfinite(x[active]).all() or (x[:, :, 1:][active] <= 0).any():
            raise ValueError("active observations must be finite with positive dt and sensor")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            variance = np.where(active, x[:, :, 2] ** 2, 1.)
            da = np.sum(np.where(active, x[:, :, 0] / variance, 0.), axis=1)
            db = np.sum(np.where(active, x[:, :, 1] / variance, 0.), axis=1)
        if not np.isfinite(da).all() or not np.isfinite(db).all():
            raise ValueError("unrepresentable sufficient statistics")
        if (lengths > np.iinfo(np.int64).max - self.count).any():
            raise ValueError("observation count overflow")
        candidates = []
        for total, error, delta in ((self.a, self.a_error, da), (self.b, self.b_error, db)):
            with np.errstate(over="ignore", invalid="ignore"):
                corrected = delta - error
                updated = total + corrected
                new_error = (updated - total) - corrected
            if not np.isfinite(updated).all() or not np.isfinite(new_error).all():
                raise ValueError("accumulator overflow")
            candidates.append((updated, new_error))
        self.a[:], self.a_error[:] = candidates[0]
        self.b[:], self.b_error[:] = candidates[1]
        self.count += lengths

    def predict(self, query):
        """Risk for (distance, noise, horizon, boundary slope[, protection cost])."""
        q = np.asarray(query, dtype=np.float64)
        if q.ndim != 2 or q.shape[1] not in (4, 5) or len(self.a) not in (1, len(q)):
            raise ValueError("query shape incompatible with state")
        if not np.isfinite(q).all() or (q[:, :3] <= 0).any():
            raise ValueError("query requires finite values and positive distance, noise, horizon")
        d, s, t, slope = (q[:, j, None] for j in range(4))
        mu = MODES - slope
        denominator = s * np.sqrt(t)
        log_f = np.logaddexp(log_ndtr((mu * t - d) / denominator),
                            2 * mu * d / s**2 + log_ndtr((-mu * t - d) / denominator))
        if not np.isfinite(log_f).all() or (log_f > 1e-9).any():
            raise ArithmeticError("first-passage evaluation outside numerical support")
        with np.errstate(over="ignore", invalid="ignore"):
            logits = (self.a[:, None] * MODES * self.scales[0]
                      - .5 * self.b[:, None] * MODES**2 * self.scales[1]
                      + np.log(PRIOR) + self.prior_shift)
        if not np.isfinite(logits).all():
            raise ArithmeticError("unrepresentable posterior logits")
        posterior = softmax(logits, axis=1)
        risk = np.sum(posterior * np.exp(np.minimum(log_f, 0.)), axis=1)
        if not np.isfinite(posterior).all() or not np.isfinite(risk).all():
            raise ArithmeticError("unrepresentable posterior or risk")
        return risk

    def checkpoint(self):
        return json.dumps({"contract": CONTRACT, "identity": self.identity,
                           "parameters": {"log_scales": self.log_scales.tolist(),
                                          "prior_shift": self.prior_shift.tolist()},
                           "a": self.a.tolist(), "b": self.b.tolist(),
                           "a_error": self.a_error.tolist(), "b_error": self.b_error.tolist(),
                           "count": self.count.tolist()}, sort_keys=True, separators=(",", ":"))

    @classmethod
    def restore(cls, payload, expected_identity):
        saved = json.loads(payload)
        keys = {"contract", "identity", "parameters", "a", "b", "a_error", "b_error", "count"}
        if set(saved) != keys or saved["contract"] != CONTRACT:
            raise ValueError("unsupported checkpoint")
        restored = cls(len(saved["a"]), saved["parameters"])
        if saved["identity"] != restored.identity or restored.identity != expected_identity:
            raise ValueError("checkpoint belongs to another model or contract")
        for name in ("a", "b", "a_error", "b_error", "count"):
            values = np.asarray(saved[name])
            if values.shape != restored.a.shape or not np.isfinite(values).all():
                raise ValueError("invalid checkpoint state")
            if name == "count" and (values.dtype.kind not in "iu" or (values < 0).any()
                                    or (values > np.iinfo(np.int64).max).any()):
                raise ValueError("invalid checkpoint count")
            if name == "b" and (values < 0).any():
                raise ValueError("negative elapsed precision")
            getattr(restored, name)[:] = values
        return restored
