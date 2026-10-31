"""Compact causal Transformer and hard-spike LIF with declared surrogate BPTT."""

import json
from pathlib import Path

import numpy as np
from scipy.special import logsumexp, ndtr


def _layernorm(x, gamma, beta):
    centered = x - x.mean(axis=-1, keepdims=True)
    inv = 1 / np.sqrt(np.mean(centered * centered, axis=-1, keepdims=True) + 1e-5)
    normal = centered * inv
    return normal * gamma + beta, (normal, inv, gamma)


def _layernorm_backward(delta, cache):
    normal, inv, gamma = cache
    dn = delta * gamma
    dx = inv * (dn - dn.mean(axis=-1, keepdims=True)
                - normal * np.mean(dn * normal, axis=-1, keepdims=True))
    axes = tuple(range(delta.ndim - 1))
    return dx, np.sum(delta * normal, axis=axes), np.sum(delta, axis=axes)


def _readout_loss(model, h, label):
    label = np.asarray(label, dtype=np.int64)
    logits = model.logits(h)
    logz = logsumexp(logits, axis=1, keepdims=True)
    loss = float(np.mean(logz[:, 0] - logits[np.arange(len(label)), label]))
    delta = np.exp(logits - logz)
    delta[np.arange(len(label)), label] -= 1
    return loss, delta / len(label)


class Base:
    @property
    def parameter_count(self):
        return sum(p.size for p in self.params.values())

    def logits(self, h):
        return h @ self.params["Wread"] + self.params["bread"]

    def loss(self, sequence, label, dt=None):
        h, _ = self.forward(sequence, dt)
        return _readout_loss(self, h, label)[0]

    def save(self, path, metadata=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        info = {"family": self.family, "input_dim": self.input_dim, "width": self.width,
                "classes": self.classes, "seed": self.seed, "format_version": 1,
                "metadata": {} if metadata is None else metadata}
        np.savez_compressed(path, metadata_json=json.dumps(info, sort_keys=True), **self.params)


class Transformer(Base):
    """One causal attention head, pre-LN residual block and exact GELU FFN."""

    family = "transformer"

    def __init__(self, input_dim, width, classes, seed):
        self.input_dim, self.width, self.classes, self.seed = input_dim, width, classes, seed
        if width % 2:
            raise ValueError("sinusoidal encoding requires even width")
        rng = np.random.default_rng(seed)
        self.params = {
            "Win": rng.normal(0, 1 / np.sqrt(input_dim), (input_dim, width)),
            "bin": np.zeros(width), "gamma1": np.ones(width), "beta1": np.zeros(width),
            "Wq": rng.normal(0, 1 / np.sqrt(width), (width, width)),
            "Wk": rng.normal(0, 1 / np.sqrt(width), (width, width)),
            "Wv": rng.normal(0, 1 / np.sqrt(width), (width, width)),
            "Wo": rng.normal(0, 1 / np.sqrt(width), (width, width)),
            "gamma2": np.ones(width), "beta2": np.zeros(width),
            "W1": rng.normal(0, 1 / np.sqrt(width), (width, 2 * width)),
            "b1": np.zeros(2 * width),
            "W2": rng.normal(0, 1 / np.sqrt(2 * width), (2 * width, width)),
            "b2": np.zeros(width),
            "Wread": rng.normal(0, 1 / np.sqrt(width), (width, classes)),
            "bread": np.zeros(classes),
        }

    def forward(self, sequence, dt=None, cache=False):
        x = np.asarray(sequence, dtype=np.float64).transpose(1, 0, 2)
        batch, length, _ = x.shape
        elapsed = np.ones((batch, length)) if dt is None else np.asarray(dt).T
        elapsed = np.broadcast_to(elapsed, (batch, length))
        if np.any(elapsed < 0) or not np.all(np.isfinite(elapsed)):
            raise ValueError("dt must be finite and nonnegative")
        positions = np.cumsum(elapsed, axis=1)
        angles = positions[:, :, None] * np.exp(-np.log(10000) * np.arange(0, self.width, 2) / self.width)
        pos = np.empty((batch, length, self.width))
        pos[:, :, 0::2], pos[:, :, 1::2] = np.sin(angles), np.cos(angles)
        p = self.params
        x0 = x @ p["Win"] + p["bin"] + pos
        n1, ln1 = _layernorm(x0, p["gamma1"], p["beta1"])
        q, k, v = n1 @ p["Wq"], n1 @ p["Wk"], n1 @ p["Wv"]
        score = q @ k.transpose(0, 2, 1) / np.sqrt(self.width)
        score = np.where(np.tril(np.ones((length, length), dtype=bool)), score, -np.inf)
        attention = np.exp(score - logsumexp(score, axis=-1, keepdims=True))
        mixed = attention @ v
        y = x0 + mixed @ p["Wo"]
        n2, ln2 = _layernorm(y, p["gamma2"], p["beta2"])
        z = n2 @ p["W1"] + p["b1"]
        ff = z * ndtr(z)
        states = y + ff @ p["W2"] + p["b2"]
        saved = (x, n1, ln1, q, k, v, attention, mixed, n2, ln2, z, ff) if cache else None
        return states[:, -1, :], saved

    def loss_grad(self, sequence, label, dt=None):
        h, saved = self.forward(sequence, dt, cache=True)
        x, n1, ln1, q, k, v, attention, mixed, n2, ln2, z, ff = saved
        p = self.params
        loss, delta = _readout_loss(self, h, label)
        g = {key: np.zeros_like(value) for key, value in p.items()}
        g["Wread"], g["bread"] = h.T @ delta, delta.sum(axis=0)
        dh = np.zeros_like(n2)
        dh[:, -1, :] = delta @ p["Wread"].T
        g["W2"] = ff.reshape(-1, 2 * self.width).T @ dh.reshape(-1, self.width)
        g["b2"] = dh.sum(axis=(0, 1))
        dz = (dh @ p["W2"].T) * (ndtr(z) + z * np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi))
        g["W1"] = n2.reshape(-1, self.width).T @ dz.reshape(-1, 2 * self.width)
        g["b1"] = dz.sum(axis=(0, 1))
        dn2 = dz @ p["W1"].T
        dy, g["gamma2"], g["beta2"] = _layernorm_backward(dn2, ln2)
        dy += dh
        g["Wo"] = mixed.reshape(-1, self.width).T @ dy.reshape(-1, self.width)
        dmixed = dy @ p["Wo"].T
        dattn = dmixed @ v.transpose(0, 2, 1)
        dv = attention.transpose(0, 2, 1) @ dmixed
        dscore = attention * (dattn - np.sum(dattn * attention, axis=-1, keepdims=True))
        dq = dscore @ k / np.sqrt(self.width)
        dk = dscore.transpose(0, 2, 1) @ q / np.sqrt(self.width)
        flat = n1.reshape(-1, self.width)
        g["Wq"] = flat.T @ dq.reshape(-1, self.width)
        g["Wk"] = flat.T @ dk.reshape(-1, self.width)
        g["Wv"] = flat.T @ dv.reshape(-1, self.width)
        dn1 = dq @ p["Wq"].T + dk @ p["Wk"].T + dv @ p["Wv"].T
        dx0, g["gamma1"], g["beta1"] = _layernorm_backward(dn1, ln1)
        dx0 += dy
        g["Win"] = x.reshape(-1, self.input_dim).T @ dx0.reshape(-1, self.width)
        g["bin"] = dx0.sum(axis=(0, 1))
        return loss, g


class LIF(Base):
    """Hard 0/1 forward spikes, subtractive reset, full-reset surrogate BPTT.

    Fixed tau_m=2, tau_read=4, threshold=1. At most one spike per input slot.
    The declared local spike Jacobian is 1/(1+abs(pre_voltage-1))**2.
    This is not the derivative of the hard-spike forward objective.
    """

    family = "lif_surrogate"

    def __init__(self, input_dim, width, classes, seed):
        self.input_dim, self.width, self.classes, self.seed = input_dim, width, classes, seed
        rng = np.random.default_rng(seed)
        self.params = {
            "Win": rng.normal(0, 1 / np.sqrt(input_dim), (input_dim, width)),
            "Wrec": rng.normal(0, 0.7 / np.sqrt(width), (width, width)),
            "b": np.zeros(width),
            "Wread": rng.normal(0, 1 / np.sqrt(width), (width, classes)),
            "bread": np.zeros(classes),
        }

    def forward(self, sequence, dt=None, cache=False):
        sequence = np.asarray(sequence, dtype=np.float64)
        batch = sequence.shape[1]
        voltage = np.zeros((batch, self.width))
        spike, read = np.zeros_like(voltage), np.zeros_like(voltage)
        saved = []
        p = self.params
        for t, x in enumerate(sequence):
            elapsed = np.ones((batch, 1)) if dt is None else np.asarray(dt[t]).reshape(-1, 1)
            if np.any(elapsed < 0) or not np.all(np.isfinite(elapsed)):
                raise ValueError("dt must be finite and nonnegative")
            alpha, rho = np.exp(-elapsed / 2), np.exp(-elapsed / 4)
            current = x @ p["Win"] + spike @ p["Wrec"] + p["b"]
            pre = alpha * voltage + (1 - alpha) * current
            next_spike = (pre >= 1).astype(np.float64)
            if cache:
                saved.append((x, spike, pre, alpha, rho, next_spike))
            voltage = pre - next_spike
            read = rho * read + (1 - rho) * next_spike
            spike = next_spike
        return read, saved

    def loss_grad(self, sequence, label, dt=None):
        read, saved = self.forward(sequence, dt, cache=True)
        self.last_diagnostics = {"forward_spikes": int(sum(np.sum(item[-1]) for item in saved)),
                                 "possible_spike_slots": int(np.prod(sequence.shape[:2]) * self.width)}
        p = self.params
        loss, delta = _readout_loss(self, read, label)
        g = {key: np.zeros_like(value) for key, value in p.items()}
        g["Wread"], g["bread"] = read.T @ delta, delta.sum(axis=0)
        dr = delta @ p["Wread"].T
        dv, ds = np.zeros_like(read), np.zeros_like(read)
        for x, old_spike, pre, alpha, rho, _ in reversed(saved):
            surrogate = 1 / (1 + np.abs(pre - 1)) ** 2
            du = dv + surrogate * (ds + (1 - rho) * dr - dv)
            dcurrent = (1 - alpha) * du
            g["Win"] += x.T @ dcurrent
            g["Wrec"] += old_spike.T @ dcurrent
            g["b"] += dcurrent.sum(axis=0)
            dv, ds, dr = alpha * du, dcurrent @ p["Wrec"].T, rho * dr
        return loss, g

    def surrogate_directional_derivative(self, sequence, label, direction, dt=None):
        """Independent forward-mode propagation of the declared surrogate tangent."""
        read, saved = self.forward(sequence, dt, cache=True)
        _, delta = _readout_loss(self, read, label)
        dv, ds, dr = np.zeros_like(read), np.zeros_like(read), np.zeros_like(read)
        for x, old_spike, pre, alpha, rho, _ in saved:
            dc = (x @ direction["Win"] + old_spike @ direction["Wrec"]
                  + ds @ self.params["Wrec"] + direction["b"])
            du = alpha * dv + (1 - alpha) * dc
            ds = du / (1 + np.abs(pre - 1)) ** 2
            dv = du - ds
            dr = rho * dr + (1 - rho) * ds
        dlogits = dr @ self.params["Wread"] + read @ direction["Wread"] + direction["bread"]
        return float(np.sum(delta * dlogits))


def make_model(family, input_dim, width, classes, seed):
    if family == "transformer":
        return Transformer(input_dim, width, classes, seed)
    if family == "lif_surrogate":
        return LIF(input_dim, width, classes, seed)
    raise ValueError("unknown comparison family")


def load_model(path):
    with np.load(path, allow_pickle=False) as saved:
        info = json.loads(str(saved["metadata_json"]))
        if info["format_version"] != 1:
            raise ValueError("unsupported checkpoint format")
        model = make_model(**{key: info[key] for key in ("family", "input_dim", "width", "classes", "seed")})
        for key, value in model.params.items():
            if saved[key].shape != value.shape or not np.all(np.isfinite(saved[key])):
                raise ValueError("invalid parameter " + key)
            model.params[key] = saved[key].copy()
    return model
