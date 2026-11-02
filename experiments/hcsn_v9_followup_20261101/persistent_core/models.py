"""NumPy persistent observation filters with full supervised BPTT.

This module is a synthetic development experiment, not a production AV model.
Inputs are elapsed time and newly accepted sensor events; state is per episode.
"""

import numpy as np


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -40, 40)))


def features(dt, modality=None, value=0):
    return np.array([dt, modality == "A", modality == "V",
                     value if modality == "A" else 0,
                     value if modality == "V" else 0], dtype=float)


class LearnedFilter:
    def __init__(self, family, seed, width=16):
        self.family, self.width = family, width
        rng = np.random.default_rng(seed)
        self.p = {"out": rng.normal(0, .1, (width, 1)), "bout": np.zeros(1)}
        if family == "gru":
            for gate in ("z", "r", "n"):
                self.p["W" + gate] = rng.normal(0, .2, (5, width))
                self.p["U" + gate] = rng.normal(0, .15, (width, width))
                self.p["b" + gate] = np.zeros(width)
        elif family == "ssm":
            self.p.update(W=rng.normal(0, .2, (5, width)), b=np.zeros(width),
                          rate=np.zeros(width), event_rate=np.zeros(width))
        else:
            raise ValueError("Unknown family")

    def zero(self, batch=1):
        return np.zeros((batch, self.width))

    def step(self, x, h):
        p = self.p
        if self.family == "gru":
            z = sigmoid(x @ p["Wz"] + h @ p["Uz"] + p["bz"])
            r = sigmoid(x @ p["Wr"] + h @ p["Ur"] + p["br"])
            n = np.tanh(x @ p["Wn"] + (r * h) @ p["Un"] + p["bn"])
            active = (np.abs(x).sum(1, keepdims=True) > 0).astype(float)
            result = h + active * z * (n - h)
            cache = (x, h, z, r, n, active)
        else:
            rate = np.logaddexp(0, p["rate"])
            event_rate = np.logaddexp(0, p["event_rate"])
            event = x[:, 1:3].sum(1, keepdims=True)
            retention = np.exp(-x[:, :1] * rate - event * event_rate)
            drive = np.tanh(x @ p["W"] + p["b"])
            result = retention * h + (1 - retention) * drive
            cache = (x, h, retention, drive, event)
        return result, sigmoid(result @ p["out"] + p["bout"])[:, 0], cache

    def loss_grad(self, inputs, labels, weights=None):
        n, steps, _ = inputs.shape
        h, history, probability = self.zero(n), [], []
        for t in range(steps):
            h, q, cache = self.step(inputs[:, t], h)
            history.append((h, cache))
            probability.append(q)
        probability = np.array(probability).T
        weights = np.ones_like(labels) if weights is None else weights
        norm = weights.sum()
        loss = -np.sum(weights * (labels * np.log(probability + 1e-12) +
                    (1 - labels) * np.log(1 - probability + 1e-12))) / norm
        grad = {k: np.zeros_like(v) for k, v in self.p.items()}
        dh = np.zeros_like(h)
        p = self.p
        for t in reversed(range(steps)):
            h_new, cache = history[t]
            dl = ((probability[:, t] - labels[:, t]) * weights[:, t] / norm)[:, None]
            grad["out"] += h_new.T @ dl
            grad["bout"] += dl.sum(0)
            dh += dl @ p["out"].T
            if self.family == "gru":
                x, h, z, r, candidate, active = cache
                dn = dh * active * z * (1 - candidate ** 2)
                dz = dh * active * (candidate - h) * z * (1 - z)
                drh = dn @ p["Un"].T
                dr = drh * h * r * (1 - r)
                grad["Wn"] += x.T @ dn
                grad["Un"] += (r * h).T @ dn
                grad["bn"] += dn.sum(0)
                for name, delta in (("z", dz), ("r", dr)):
                    grad["W" + name] += x.T @ delta
                    grad["U" + name] += h.T @ delta
                    grad["b" + name] += delta.sum(0)
                dh = (dh * (1 - active * z) + drh * r +
                      dz @ p["Uz"].T + dr @ p["Ur"].T)
            else:
                x, h, retention, drive, event = cache
                dd = dh * (1 - retention) * (1 - drive ** 2)
                dr = dh * (h - drive)
                grad["W"] += x.T @ dd
                grad["b"] += dd.sum(0)
                grad["rate"] += (-dr * retention * x[:, :1] * sigmoid(p["rate"])).sum(0)
                grad["event_rate"] += (-dr * retention * event * sigmoid(p["event_rate"])).sum(0)
                dh = dh * retention
        return float(loss), grad, probability

    def sequence(self, inputs):
        h = self.zero(len(inputs))
        predictions = []
        for t in range(inputs.shape[1]):
            h, q, _ = self.step(inputs[:, t], h)
            predictions.append(q)
        return np.array(predictions).T


class AnalyticFilter:
    def __init__(self, rate=.35, accuracy=None):
        self.rate = rate
        self.accuracy = accuracy or {"A": .78, "V": .9}

    def step(self, dt, p, modality=None, value=0):
        p = .5 + (p - .5) * np.exp(-2 * self.rate * dt)
        if modality:
            q = self.accuracy[modality]
            lhs = q if value == 1 else 1 - q
            rhs = 1 - lhs
            p = p * lhs / (p * lhs + (1 - p) * rhs)
        return float(p)

    def history(self, events):
        """Strong no-core reference: recompute from raw visible history."""
        p = .5
        for dt, modality, value in events:
            p = self.step(dt, p, modality, value)
        return p
