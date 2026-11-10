"""Small CPU classifiers, including an actual GRU trained by BPTT."""

import numpy as np


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def softmax(x):
    y = np.exp(x - x.max(axis=-1, keepdims=True))
    return y / y.sum(axis=-1, keepdims=True)


class Model:
    def __init__(self, kind, seed, features=10, hidden=12):
        self.kind, self.hidden = kind, hidden
        rng = np.random.default_rng(seed)
        if kind == "head":
            self.p = {"W": rng.normal(0, .08, (features, 3)), "b": np.zeros(3)}
        else:
            self.p = {"W" + gate: rng.normal(0, .08, (features, hidden)) for gate in "zrn"}
            self.p.update({"U" + gate: rng.normal(0, .08, (hidden, hidden)) for gate in "zrn"})
            self.p.update({"b" + gate: np.zeros(hidden) for gate in "zrn"})
            self.p.update(V=rng.normal(0, .08, (hidden, 3)), c=np.zeros(3))

    def forward(self, x):
        if self.kind == "head":
            return softmax(x @ self.p["W"] + self.p["b"]), None
        state = np.zeros((x.shape[0], self.hidden))
        outputs, cache = [], []
        p = self.p
        for step in x.transpose(1, 0, 2):
            old = state
            z = sigmoid(step @ p["Wz"] + old @ p["Uz"] + p["bz"])
            r = sigmoid(step @ p["Wr"] + old @ p["Ur"] + p["br"])
            n = np.tanh(step @ p["Wn"] + (r * old) @ p["Un"] + p["bn"])
            state = (1 - z) * n + z * old
            outputs.append(softmax(state @ p["V"] + p["c"]))
            cache.append((step, old, z, r, n, state))
        return np.stack(outputs, axis=1), cache

    def loss_grad(self, x, y, mask):
        prob, cache = self.forward(x)
        normalizer = mask.sum()
        loss = -(np.log(prob + 1e-12) * y * mask[..., None]).sum() / normalizer
        error = (prob - y) * mask[..., None] / normalizer
        grad = {key: np.zeros_like(value) for key, value in self.p.items()}
        if self.kind == "head":
            grad["W"] = np.einsum("bti,btj->ij", x, error)
            grad["b"] = error.sum(axis=(0, 1))
            return float(loss), grad
        dh = np.zeros((x.shape[0], self.hidden))
        p = self.p
        for t in range(x.shape[1] - 1, -1, -1):
            step, old, z, r, n, state = cache[t]
            e = error[:, t]
            grad["V"] += state.T @ e
            grad["c"] += e.sum(axis=0)
            dh += e @ p["V"].T
            dn = dh * (1 - z) * (1 - n * n)
            dz = dh * (old - n) * z * (1 - z)
            drh = dn @ p["Un"].T
            dr = drh * old * r * (1 - r)
            for gate, dg in (("z", dz), ("r", dr), ("n", dn)):
                grad["W" + gate] += step.T @ dg
                grad["U" + gate] += (r * old if gate == "n" else old).T @ dg
                grad["b" + gate] += dg.sum(axis=0)
            dh = dh * z + dz @ p["Uz"].T + dr @ p["Ur"].T + drh * r
        return float(loss), grad

    def fit(self, x, y, mask, epochs=220):
        first, second = {k: np.zeros_like(v) for k, v in self.p.items()}, {k: np.zeros_like(v) for k, v in self.p.items()}
        losses = []
        for iteration in range(1, epochs + 1):
            loss, gradients = self.loss_grad(x, y, mask)
            losses.append(loss)
            norm = max(1, np.sqrt(sum((g * g).sum() for g in gradients.values())) / 5)
            for key, gradient in gradients.items():
                gradient = gradient / norm
                first[key] = .9 * first[key] + .1 * gradient
                second[key] = .999 * second[key] + .001 * gradient * gradient
                self.p[key] -= .025 * (first[key] / (1 - .9 ** iteration)) / (np.sqrt(second[key] / (1 - .999 ** iteration)) + 1e-8)
        return losses

    def choose(self, feature, state):
        x, p = np.asarray(feature), self.p
        if self.kind == "head":
            return int((x @ p["W"] + p["b"]).argmax()), state
        z = sigmoid(x @ p["Wz"] + state @ p["Uz"] + p["bz"])
        r = sigmoid(x @ p["Wr"] + state @ p["Ur"] + p["br"])
        n = np.tanh(x @ p["Wn"] + (r * state) @ p["Un"] + p["bn"])
        state = (1 - z) * n + z * state
        return int((state @ p["V"] + p["c"]).argmax()), state


def gradient_check():
    rng = np.random.default_rng(41)
    x = rng.normal(size=(2, 3, 10)) * .2
    y = np.eye(3)[rng.integers(0, 3, (2, 3))]
    mask = np.ones((2, 3))
    checked = []
    for kind in ("head", "gru"):
        model = Model(kind, 9)
        _, grad = model.loss_grad(x, y, mask)
        for key, value in model.p.items():
            index = tuple(0 for _ in value.shape)
            original = value[index]
            value[index] = original + 1e-5
            upper = model.loss_grad(x, y, mask)[0]
            value[index] = original - 1e-5
            lower = model.loss_grad(x, y, mask)[0]
            value[index] = original
            numerical = (upper - lower) / 2e-5
            error = abs(numerical - grad[key][index])
            assert error < 2e-7, (kind, key, error)
            checked.append({"model": kind, "parameter": key, "absolute_error": float(error)})
    return checked
