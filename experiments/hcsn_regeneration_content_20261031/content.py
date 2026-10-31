"""A fully trainable NumPy recurrent content model and hand-written BPTT."""

import json
from pathlib import Path

import numpy as np
from scipy.special import expit, logsumexp

try:
    from .renewal import expected_count, expected_count_details
except ImportError:
    from renewal import expected_count, expected_count_details


class Model:
    """Equal parameter shapes across ordinary and analytic renewal-flow gates."""

    def __init__(self, family, input_dim, width, classes, seed):
        if family not in ("ordinary", "analytic"):
            raise ValueError("family must be ordinary or analytic")
        self.family = family
        self.input_dim = int(input_dim)
        self.width = int(width)
        self.classes = int(classes)
        self.seed = int(seed)
        rng = np.random.default_rng(seed)
        self.params = {
            "Wx": rng.normal(0, 1 / np.sqrt(input_dim), (input_dim, width)),
            "Wh": rng.normal(0, 0.7 / np.sqrt(width), (width, width)),
            "b": np.zeros(width),
            "Gx": rng.normal(0, 0.4 / np.sqrt(input_dim), (input_dim, width)),
            "Gh": rng.normal(0, 0.4 / np.sqrt(width), (width, width)),
            "gb": np.zeros(width),
            "Wo": rng.normal(0, 1 / np.sqrt(width), (width, classes)),
            "bo": np.zeros(classes),
        }

    @property
    def parameter_count(self):
        return sum(p.size for p in self.params.values())

    def initial(self, batch):
        return np.zeros((int(batch), self.width), dtype=np.float64)

    def gate(self, a, dt, derivative=False):
        dt = np.asarray(dt, dtype=np.float64)
        if dt.ndim == 1:
            dt = dt[:, None]
        if np.any(dt < 0) or not np.all(np.isfinite(dt)):
            raise ValueError("dt must be finite and nonnegative")
        if self.family == "ordinary":
            rate = np.logaddexp(0.0, a)
            decay = np.exp(-dt * rate)
            gate = -np.expm1(-dt * rate)
            slope = decay * dt * expit(a) if derivative else None
        else:
            distance = np.logaddexp(0.0, -a) + 0.05
            args = (distance, -0.25, 1.0, dt, 0.8, 0.15)
            details = expected_count_details(*args) if derivative else None
            count = details["mean"] if derivative else expected_count(*args)
            decay = np.exp(-count)
            gate = -np.expm1(-count)
            slope = (
                -decay * details["dx"] * expit(-a)
                if derivative else None
            )
        return gate, slope

    def _step(self, x, h, dt, cache):
        x = np.asarray(x, dtype=np.float64)
        h = np.asarray(h, dtype=np.float64)
        if x.ndim != 2 or h.shape != (x.shape[0], self.width):
            raise ValueError("x and h must have shapes [batch,input] and [batch,width]")
        if x.shape[1] != self.input_dim:
            raise ValueError("input dimension mismatch")
        p = self.params
        candidate = np.tanh(x @ p["Wx"] + h @ p["Wh"] + p["b"])
        a = x @ p["Gx"] + h @ p["Gh"] + p["gb"]
        gate, slope = self.gate(a, dt, derivative=cache)
        result = h + gate * (candidate - h)
        saved = (x, h, candidate, gate, slope) if cache else None
        return result, saved

    def step(self, x, h, dt=1.0):
        """Pure transition: neither parameters nor the supplied state are mutated."""
        return self._step(x, h, dt, cache=False)[0]

    def logits(self, h):
        return np.asarray(h) @ self.params["Wo"] + self.params["bo"]

    def features(self, h):
        """Observed-state features only; no task posterior or unseen observations."""
        logits = self.logits(h)
        probs = np.exp(logits - logsumexp(logits, axis=1, keepdims=True))
        return np.concatenate((h, probs), axis=1)

    def forward(self, sequence, dt=None, cache=False):
        sequence = np.asarray(sequence, dtype=np.float64)
        if sequence.ndim != 3:
            raise ValueError("sequence must have shape [time,batch,input]")
        h = self.initial(sequence.shape[1])
        saved = []
        for t, x in enumerate(sequence):
            elapsed = 1.0 if dt is None else np.asarray(dt)[t]
            h, item = self._step(x, h, elapsed, cache)
            if cache:
                saved.append(item)
        return h, saved

    def loss(self, sequence, label, dt=None):
        h, _ = self.forward(sequence, dt)
        logits = self.logits(h)
        return float(np.mean(logsumexp(logits, axis=1) - logits[np.arange(len(label)), label]))

    def loss_grad(self, sequence, label, dt=None):
        """Mean final-token cross entropy and gradients of every parameter."""
        label = np.asarray(label, dtype=np.int64)
        h, saved = self.forward(sequence, dt, cache=True)
        p = self.params
        logits = self.logits(h)
        logz = logsumexp(logits, axis=1, keepdims=True)
        loss = float(np.mean(logz[:, 0] - logits[np.arange(len(label)), label]))
        delta = np.exp(logits - logz)
        delta[np.arange(len(label)), label] -= 1
        delta /= len(label)
        grads = {name: np.zeros_like(value) for name, value in p.items()}
        grads["Wo"] = h.T @ delta
        grads["bo"] = delta.sum(axis=0)
        dh = delta @ p["Wo"].T
        for x, old, candidate, gate, slope in reversed(saved):
            dc = dh * gate * (1 - candidate * candidate)
            da = dh * (candidate - old) * slope
            grads["Wx"] += x.T @ dc
            grads["Wh"] += old.T @ dc
            grads["b"] += dc.sum(axis=0)
            grads["Gx"] += x.T @ da
            grads["Gh"] += old.T @ da
            grads["gb"] += da.sum(axis=0)
            dh = dh * (1 - gate) + dc @ p["Wh"].T + da @ p["Gh"].T
        return loss, grads

    def save(self, path, metadata=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        info = dict(family=self.family, input_dim=self.input_dim, width=self.width,
                    classes=self.classes, seed=self.seed, format_version=1,
                    metadata={} if metadata is None else metadata)
        np.savez_compressed(path, metadata_json=json.dumps(info, sort_keys=True), **self.params)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as saved:
            info = json.loads(str(saved["metadata_json"]))
            if info["format_version"] != 1:
                raise ValueError("unsupported model format")
            model = cls(**{key: info[key] for key in ("family", "input_dim", "width", "classes", "seed")})
            for key, value in model.params.items():
                if saved[key].shape != value.shape or not np.all(np.isfinite(saved[key])):
                    raise ValueError("invalid parameter " + key)
                model.params[key] = saved[key].copy()
        return model


class Adam:
    """Adam with global norm clipping; optimizer state is exportable evidence."""

    def __init__(self, model, lr=0.003, clip=1.0):
        self.lr, self.clip, self.t = float(lr), float(clip), 0
        self.m = {key: np.zeros_like(v) for key, v in model.params.items()}
        self.v = {key: np.zeros_like(v) for key, v in model.params.items()}

    def step(self, model, grads):
        norm = float(np.sqrt(sum(np.sum(g * g) for g in grads.values())))
        if not np.isfinite(norm):
            raise FloatingPointError("nonfinite gradient")
        scale = min(1.0, self.clip / max(norm, np.finfo(float).tiny))
        self.t += 1
        for key, g in grads.items():
            g = g * scale
            self.m[key] = 0.9 * self.m[key] + 0.1 * g
            self.v[key] = 0.999 * self.v[key] + 0.001 * g * g
            m = self.m[key] / (1 - 0.9 ** self.t)
            v = self.v[key] / (1 - 0.999 ** self.t)
            model.params[key] -= self.lr * m / (np.sqrt(v) + 1e-8)
        return norm, scale

    def save(self, path):
        arrays = {"m_" + key: value for key, value in self.m.items()}
        arrays.update({"v_" + key: value for key, value in self.v.items()})
        np.savez_compressed(path, step=self.t, learning_rate=self.lr, clip=self.clip, **arrays)
