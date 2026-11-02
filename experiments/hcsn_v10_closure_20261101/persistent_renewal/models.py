"""NumPy multiclass GRU, diagonal SSM and nonrecurrent latest-packet model."""

import numpy as np


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -40, 40)))


def softmax(x):
    p = np.exp(x - x.max(-1, keepdims=True))
    return p / p.sum(-1, keepdims=True)


class Model:
    def __init__(self, family, seed, width, inputs=16, classes=5):
        self.family, self.width, self.classes = family, width, classes
        rng = np.random.default_rng(seed)
        self.p = {"out": rng.normal(0, .1, (width, classes)), "bout": np.zeros(classes)}
        if family == "gru":
            for gate in ("z", "r", "n"):
                self.p["W" + gate] = rng.normal(0, .15, (inputs, width))
                self.p["U" + gate] = rng.normal(0, .1, (width, width))
                self.p["b" + gate] = np.zeros(width)
        elif family in ("ssm", "mlp"):
            self.p.update(W=rng.normal(0, .15, (inputs, width)), b=np.zeros(width))
            if family == "ssm":
                self.p.update(rate=np.zeros(width), event_rate=np.zeros(width))
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
            result, cache = (1 - z) * h + z * n, (x, h, z, r, n)
        elif self.family == "ssm":
            # At time zero initialize from the public packet; a READ adds a jump.
            initialization = (x[:, 15:16] == 0).astype(float)
            event = np.maximum(x[:, 1:2], initialization)
            retention = np.exp(-x[:, :1] * np.logaddexp(0, p["rate"]) -
                               event * np.logaddexp(0, p["event_rate"]))
            drive = np.tanh(x @ p["W"] + p["b"])
            result, cache = retention * h + (1 - retention) * drive, (x, h, retention, drive, event)
        else:
            result = np.tanh(x @ p["W"] + p["b"])
            cache = (x, result)
        probabilities = softmax(result @ p["out"] + p["bout"])
        # Same perfect-READ and invariant uniform initial head for every core.
        probabilities = np.where((x[:, 2:3] == 0), 1 / self.classes, probabilities)
        probabilities = np.where((x[:, 1:2] == 1), x[:, 5:10], probabilities)
        return result, probabilities, cache

    def sequence(self, x):
        h, outputs = self.zero(len(x)), []
        for t in range(x.shape[1]):
            h, p, _ = self.step(x[:, t], h)
            outputs.append(p)
        return np.stack(outputs, 1)

    def loss_grad(self, x, labels):
        h, history, outputs = self.zero(len(x)), [], []
        for t in range(x.shape[1]):
            h, p, cache = self.step(x[:, t], h)
            history.append((h, cache)); outputs.append(p)
        probabilities = np.stack(outputs, 1)
        selected = np.take_along_axis(probabilities, labels[..., None], axis=-1)[..., 0]
        loss = float(-np.log(selected + 1e-12).mean())
        gradient = {k: np.zeros_like(v) for k, v in self.p.items()}
        dh, p = np.zeros_like(h), self.p
        for t in reversed(range(x.shape[1])):
            h_new, cache = history[t]
            dl = probabilities[:, t].copy()
            dl[np.arange(len(x)), labels[:, t]] -= 1
            dl *= ((x[:, t, 2:3] > 0) & (x[:, t, 1:2] == 0))
            dl /= labels.size
            gradient["out"] += h_new.T @ dl
            gradient["bout"] += dl.sum(0)
            dh += dl @ p["out"].T
            if self.family == "gru":
                xx, old, z, r, n = cache
                dn = dh * z * (1 - n * n)
                dz = dh * (n - old) * z * (1 - z)
                drh = dn @ p["Un"].T
                dr = drh * old * r * (1 - r)
                gradient["Wn"] += xx.T @ dn
                gradient["Un"] += (r * old).T @ dn
                gradient["bn"] += dn.sum(0)
                for name, delta in (("z", dz), ("r", dr)):
                    gradient["W" + name] += xx.T @ delta
                    gradient["U" + name] += old.T @ delta
                    gradient["b" + name] += delta.sum(0)
                dh = dh * (1 - z) + drh * r + dz @ p["Uz"].T + dr @ p["Ur"].T
            elif self.family == "ssm":
                xx, old, retention, drive, event = cache
                dd = dh * (1 - retention) * (1 - drive ** 2)
                dr = dh * (old - drive)
                gradient["W"] += xx.T @ dd
                gradient["b"] += dd.sum(0)
                gradient["rate"] += (-dr * retention * xx[:, :1] * sigmoid(p["rate"])).sum(0)
                gradient["event_rate"] += (-dr * retention * event * sigmoid(p["event_rate"])).sum(0)
                dh = dh * retention
            else:
                xx, activation = cache
                dd = dh * (1 - activation ** 2)
                gradient["W"] += xx.T @ dd
                gradient["b"] += dd.sum(0)
                dh = np.zeros_like(dh)
        return loss, gradient
