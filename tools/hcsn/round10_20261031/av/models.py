"""Small, fully trainable recurrent controls; all derivatives are NumPy BPTT.

The analytic arm is a zero-drift Brownian first-passage gate, not full He--Xiong.
CfC default equations reproduce ncps 695ec22, backbone_layers=0, no sparsity.
CfC equation attribution: Mathias Lechner and Ramin Hasani, Apache-2.0;
the preserved upstream_cfc_cell.py contains the full source/license notice.
"""

import numpy as np
from scipy.special import expit, erfc, logsumexp


SIGMA = 3.0
GAP_FLOOR = 0.001


def gate(kind, z, dt):
    if kind == "ordinary":
        p = expit(z)
        return p, p * (1 - p)
    scale = SIGMA * np.sqrt(dt)
    if kind == "analytic":
        distance = np.logaddexp(0, -z) + GAP_FLOOR
        p = erfc(distance / (np.sqrt(2) * scale))
        slope = np.sqrt(2 / np.pi) / scale * np.exp(-0.5 * (distance / scale) ** 2) * expit(-z)
        return p, slope
    if kind == "matched_c1":
        distance = np.log(2) + GAP_FLOOR
        p0 = erfc(distance / (np.sqrt(2) * scale))
        slope0 = np.sqrt(2 / np.pi) / scale * np.exp(-0.5 * (distance / scale) ** 2) * 0.5
        slope = slope0 / (p0 * (1 - p0))
        intercept = np.log(p0) - np.log1p(-p0)
        p = expit(slope * z + intercept)
        return p, slope * p * (1 - p)
    raise ValueError(kind)


class Model:
    def __init__(self, kind, width, input_dim=261, seed=0):
        self.kind, self.width, self.input_dim = kind, width, input_dim
        heads = 4 if kind == "cfc" else 2
        rng = np.random.default_rng(seed)
        size = input_dim + width
        lim = np.sqrt(6 / (size + width))
        self.p = {
            "w": np.concatenate([rng.uniform(-lim, lim, (size, width)) for _ in range(heads)], axis=1),
            "b": np.zeros(heads * width),
            "out": rng.uniform(-np.sqrt(6 / (width + 6)), np.sqrt(6 / (width + 6)), (width, 6)),
            "bias": np.zeros(6),
        }

    @property
    def parameters(self):
        return sum(v.size for v in self.p.values())

    def forward(self, x, dt, retain=False):
        h = np.zeros((len(x), self.width))
        history = []
        for t in range(x.shape[1]):
            q = np.concatenate((x[:, t], h), axis=1)
            pre = q @ self.p["w"] + self.p["b"]
            if self.kind == "cfc":
                a, b, ta, tb = np.split(pre, 4, axis=1)
                f1, f2 = np.tanh(a), np.tanh(b)
                mix = expit(ta * dt[:, t, None] + tb)
                new = f1 * (1 - mix) + f2 * mix
                if retain:
                    history.append((q, f1, f2, mix, dt[:, t, None]))
            else:
                a, z = np.split(pre, 2, axis=1)
                f = np.tanh(a)
                mix, slope = gate(self.kind, z, dt[:, t, None])
                new = h * (1 - mix) + f * mix
                if retain:
                    history.append((q, h, f, mix, slope))
            h = new
        logits = h @ self.p["out"] + self.p["bias"]
        return logits, h, history

    def loss(self, x, dt, y, gradients=True):
        logits, h, history = self.forward(x, dt, gradients)
        loss = float(np.mean(logsumexp(logits, axis=1) - logits[np.arange(len(y)), y]))
        if not gradients:
            return loss
        probs = np.exp(logits - logsumexp(logits, axis=1, keepdims=True))
        probs[np.arange(len(y)), y] -= 1
        probs /= len(y)
        g = {key: np.zeros_like(value) for key, value in self.p.items()}
        g["out"] = h.T @ probs
        g["bias"] = probs.sum(axis=0)
        dh = probs @ self.p["out"].T
        for item in reversed(history):
            if self.kind == "cfc":
                q, f1, f2, mix, elapsed = item
                dm = dh * (f2 - f1) * mix * (1 - mix)
                dpre = np.concatenate((dh * (1 - mix) * (1 - f1 ** 2),
                                       dh * mix * (1 - f2 ** 2), dm * elapsed, dm), axis=1)
                direct = 0
            else:
                q, before, f, mix, slope = item
                dpre = np.concatenate((dh * mix * (1 - f ** 2), dh * (f - before) * slope), axis=1)
                direct = dh * (1 - mix)
            g["w"] += q.T @ dpre
            g["b"] += dpre.sum(axis=0)
            dh = dpre @ self.p["w"][self.input_dim:].T + direct
        if not np.isfinite(loss) or any(not np.isfinite(v).all() for v in g.values()):
            raise FloatingPointError("Nonfinite forward/backward")
        return loss, g


class Adam:
    def __init__(self, model, lr=0.003):
        self.m = {k: np.zeros_like(v) for k, v in model.p.items()}
        self.v = {k: np.zeros_like(v) for k, v in model.p.items()}
        self.lr, self.step = lr, 0

    def update(self, model, grad):
        norm = float(np.sqrt(sum(np.sum(v * v) for v in grad.values())))
        factor = min(1.0, 2.0 / max(norm, 1e-30))
        self.step += 1
        for key, value in model.p.items():
            derivative = factor * grad[key]
            self.m[key] = 0.9 * self.m[key] + 0.1 * derivative
            self.v[key] = 0.999 * self.v[key] + 0.001 * derivative * derivative
            m = self.m[key] / (1 - 0.9 ** self.step)
            v = self.v[key] / (1 - 0.999 ** self.step)
            value -= self.lr * m / (np.sqrt(v) + 1e-8)
        return norm
