"""Fixed-K Fashion objectives and matched requests, not a dataset runner."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from .bound.autodiff import Tensor
from .bound.model import ContentModel, _matrix, _sequence, categorical_ce, joint_risk

ARMS = ("H", "A", "N")


def verify_binding():
    root = Path(__file__).resolve().parent
    binding = json.loads((root / "BINDING.json").read_text())
    for path, entry in binding["dependencies"].items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != entry["bound_sha256"]:
            raise ValueError("Fashion dependency hash mismatch: " + path)
    return binding


def _readonly(value, dtype):
    a = np.asarray(value, dtype=dtype)
    return np.frombuffer(a.tobytes(), dtype=dtype).reshape(a.shape)


@dataclass(frozen=True)
class Batch:
    """One paired offline request: every arm receives exactly these inputs.

    sum(weight * row_loss) / normalizer weights the ENTIRE loss. Default n is
    an importance-weighted mean, not silent sum-weight self-normalization.
    To request a normalized weighted mean, explicitly supply sum(weights).
    """

    noisy: np.ndarray
    clean: np.ndarray
    labels: np.ndarray
    draws: np.ndarray
    weights: np.ndarray
    normalizer: float | None = None

    def __post_init__(self):
        noisy = _matrix(self.noisy, 784, "noisy", True)
        clean = _matrix(self.clean, 784, "clean", True)
        n = len(noisy)
        labels, draws, weights = map(np.asarray, (self.labels, self.draws, self.weights))
        if (clean.shape != noisy.shape or labels.shape != (n,) or labels.dtype.kind not in "iu"
                or (labels < 0).any() or (labels >= 10).any()):
            raise ValueError("invalid paired labels/reference")
        if (draws.shape != (n, 4, 784) or draws.dtype.kind not in "fiu"
                or not np.isfinite(draws).all()):
            raise ValueError("exactly four finite terminal draws per row required")
        if (weights.shape != (n,) or weights.dtype.kind not in "fiu"
                or not np.isfinite(weights).all() or (weights < 0).any() or not (weights > 0).any()):
            raise ValueError("finite nonnegative weights with positive mass required")
        normalizer = n if self.normalizer is None else self.normalizer
        if isinstance(normalizer, (bool, np.bool_)) or not np.isfinite(normalizer) or normalizer <= 0:
            raise ValueError("positive finite explicit normalizer required")
        for name, value, dtype in (("noisy", noisy, np.float64), ("clean", clean, np.float64),
                                   ("labels", labels, np.int64), ("draws", draws, np.float64),
                                   ("weights", weights, np.float64)):
            object.__setattr__(self, name, _readonly(value, dtype))
        object.__setattr__(self, "normalizer", float(normalizer))

    def digest(self):
        h = hashlib.sha256(str(self.normalizer).encode())
        for name in ("noisy", "clean", "labels", "draws", "weights"):
            value = getattr(self, name)
            h.update(name.encode() + str(value.shape).encode() + value.tobytes())
        return h.hexdigest()


class Control:
    """Same pinned model/optimizer for H, A and N; only terminal loss differs."""

    def __init__(self, objective, seed):
        if objective not in ARMS:
            raise ValueError("objective must be H, A or N")
        verify_binding()
        self.objective = objective
        self.model = ContentModel(seed)

    def _loss(self, batch, sequence, grad):
        if not isinstance(batch, Batch):
            raise TypeError("a paired Batch is required")
        sequence = _sequence(sequence)
        ctx, state = self.model._context(batch.noisy, grad)
        for action in sequence:
            state = self.model._advance(state, action, ctx)
        error = state.mu - batch.clean
        ce = categorical_ce(state.shifted, state.p, state.denominator, batch.labels)
        anchor = ce + (error * error).mean(axis=-1) / 0.04
        auxiliary = Tensor(np.zeros(len(batch.noisy)))
        if self.objective != "H":
            samples = (state.mu.reshape(-1, 1, 784) + 0.05 * batch.draws).clip(0, 1)
            residual = samples - batch.clean[:, None, :]
            q = ((residual * residual).mean(axis=-1) / -0.04).exp()
            auxiliary = joint_risk(state.shifted, state.p, q, batch.labels, self.objective)
        rows = anchor - 0.1 * auxiliary
        loss = (rows * batch.weights).sum() / batch.normalizer
        return loss, ctx, {"objective": self.objective, "batch_digest": batch.digest(),
                           "row_loss": rows.data.copy(), "anchor": anchor.data.copy(),
                           "auxiliary": auxiliary.data.copy(), "normalizer": batch.normalizer}

    def loss_value(self, batch, sequence):
        return float(self._loss(batch, sequence, False)[0].data)

    def loss_grad(self, batch, sequence):
        loss, ctx, metrics = self._loss(batch, sequence, True)
        loss.backward()
        grads = {name: leaf.grad.copy() for name, leaf in ctx["params"].items() if leaf.grad is not None}
        return float(loss.data), grads, metrics

    def step(self, batch, sequence, *, learning_rate):
        value, grads, metrics = self.loss_grad(batch, sequence)
        self.model.adam_step(grads, lr=learning_rate)
        return value, metrics

    def serve(self, noisy, sequence):
        """Greedy classes and float32 mean image; no labels, clean image or draws."""
        return self.model.infer(noisy, sequence)


def offline_service_utility(prediction, batch):
    """Score returned float32 pixels, not q or N; NOT a wire-transport audit."""
    pixels = np.asarray(prediction.image, dtype=np.float64).reshape(-1, 784)
    return (prediction.classes == batch.labels) * np.exp(-np.mean((pixels - batch.clean) ** 2, axis=-1) / .04)
