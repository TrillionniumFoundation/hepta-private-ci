"""NumPy GRU and gated continuous diagonal state model, with full BPTT.

Continuous decay is exact between endpoint input updates. This comparator has
no financial state equations or teacher posterior at inference.
"""

import numpy as np
from scipy.special import expit, softmax

from .estimators import loss_and_logit_gradient


class RecurrentEstimator:
    def __init__(self, kind, seed=0, parameters=None):
        if kind not in ("gru", "continuous_diagonal_ssm"):
            raise ValueError(kind)
        self.kind = kind
        rng = np.random.default_rng(seed)
        self.width = 16 if kind == "gru" else 24
        h = self.width
        random = lambda shape, scale: rng.normal(0, scale, shape)
        self.params = {"Wo": random((h, 20), 1 / np.sqrt(h)), "bo": np.zeros(20)}
        if kind == "gru":
            for name in ("z", "r", "n"):
                self.params["W" + name] = random((10, h), .25)
                self.params["U" + name] = random((h, h), .15)
                self.params["b" + name] = np.zeros(h)
        else:
            self.params.update({"Wu": random((10, h), .25), "bu": np.zeros(h),
                                "Wg": random((10, h), .25), "bg": np.zeros(h),
                                "rate": random((h,), .2)})
        if parameters is not None:
            self.params = {k: np.array(v, dtype=float) for k, v in parameters.items()}
        self.hidden = None
        self.current = None

    def _advance(self, x, previous):
        p = self.params
        if self.kind == "gru":
            z = expit(x @ p["Wz"] + previous @ p["Uz"] + p["bz"])
            r = expit(x @ p["Wr"] + previous @ p["Ur"] + p["br"])
            n = np.tanh(x @ p["Wn"] + (r * previous) @ p["Un"] + p["bn"])
            hidden = z * previous + (1 - z) * n
            return hidden, (x, previous, z, r, n)
        rate = np.logaddexp(0, p["rate"])
        decay = np.exp(-x[:, 8:9] * rate)
        u = np.tanh(x @ p["Wu"] + p["bu"])
        g = expit(x @ p["Wg"] + p["bg"])
        hidden = (1 - g) * decay * previous + g * u
        return hidden, (x, previous, decay, u, g)

    def forward(self, inputs, cache=False):
        batch, length = inputs.shape[:2]
        hidden = np.zeros((batch, self.width))
        probabilities = np.empty((batch, length, 20))
        records = []
        for t in range(length):
            hidden, record = self._advance(inputs[:, t], hidden)
            probabilities[:, t] = softmax(hidden @ self.params["Wo"] + self.params["bo"], axis=-1)
            if cache:
                records.append((hidden, record))
        return (probabilities, records) if cache else probabilities

    def loss_grad(self, inputs, teacher, labels):
        probabilities, records = self.forward(inputs, cache=True)
        loss, output_gradient = loss_and_logit_gradient(probabilities, teacher, labels)
        p = self.params
        grads = {k: np.zeros_like(v) for k, v in p.items()}
        future = np.zeros((inputs.shape[0], self.width))
        for t in range(inputs.shape[1] - 1, -1, -1):
            hidden, record = records[t]
            out = output_gradient[:, t]
            grads["Wo"] += hidden.T @ out
            grads["bo"] += out.sum(axis=0)
            dh = future + out @ p["Wo"].T
            if self.kind == "gru":
                x, previous, z, r, n = record
                dz = dh * (previous - n) * z * (1 - z)
                dn = dh * (1 - z) * (1 - n * n)
                drh = dn @ p["Un"].T
                dr = drh * previous * r * (1 - r)
                future = dh * z + drh * r + dz @ p["Uz"].T + dr @ p["Ur"].T
                for name, derivative, recurrent_input in (("z", dz, previous), ("r", dr, previous), ("n", dn, r * previous)):
                    grads["W" + name] += x.T @ derivative
                    grads["U" + name] += recurrent_input.T @ derivative
                    grads["b" + name] += derivative.sum(axis=0)
            else:
                x, previous, decay, u, g = record
                du = dh * g * (1 - u * u)
                dg = dh * (u - decay * previous) * g * (1 - g)
                rate_gradient = dh * (1 - g) * previous * (-x[:, 8:9] * decay) * expit(p["rate"])
                grads["rate"] += rate_gradient.sum(axis=0)
                future = dh * (1 - g) * decay
                grads["Wu"] += x.T @ du
                grads["bu"] += du.sum(axis=0)
                grads["Wg"] += x.T @ dg
                grads["bg"] += dg.sum(axis=0)
        return loss, grads

    def start(self, prior=None):
        self.hidden = np.zeros((1, self.width))
        self.current = np.full(20, .05) if prior is None else np.array(prior, copy=True)
        return self.current.copy()

    def step(self, inputs):
        if self.hidden is None:
            self.start()
        self.hidden, _ = self._advance(np.asarray(inputs)[None, :], self.hidden)
        self.current = softmax(self.hidden @ self.params["Wo"] + self.params["bo"], axis=-1)[0]
        return self.current.copy()

    def export(self):
        return {"kind": self.kind, "parameters": {k: v.tolist() for k, v in self.params.items()},
                "parameter_count": sum(v.size for v in self.params.values())}
