"""NumPy research cells; this is not the production HCSN implementation.

The analytic channels are frozen-law, one-sided Brownian first-passage F/G.
Their difference is a signed feature, not a two-sided hitting probability.
Training below uses explicit BPTT/Adam, reported as such rather than no-BP.
"""

import hashlib
import time

import numpy as np
from scipy.special import ndtr


def digest(*arrays):
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str((a.shape, a.dtype)).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def delayed_data(seed, count, width, source="normal", steps=12):
    """Two independently sampled bits arrive far apart; the target is XOR.

    Test source uses Laplace cue noise, different reveal-time support, and
    broader independent initial states. No target enters forward/controller.
    """
    rng = np.random.default_rng(seed)
    bits = rng.choice([-1.0, 1.0], (count, 2))
    x = np.zeros((steps, count, 4))
    late = rng.integers(6 if source == "normal" else 7, steps - 1, count)
    noise = (rng.normal(0, 0.12, (count, 2)) if source == "normal" else
             rng.laplace(0, 0.12 / np.sqrt(2), (count, 2)))
    x[0, :, 0] = bits[:, 0] + noise[:, 0]
    x[0, :, 2] = 1.0
    x[late, np.arange(count), 1] = bits[:, 1] + noise[:, 1]
    x[late, np.arange(count), 3] = 1.0
    z0 = rng.normal(0, 0.05 if source == "normal" else 0.10, (count, width))
    eps = rng.normal(0, 1, (steps, count, width))
    y = (bits[:, 0] * bits[:, 1] > 0).astype(float)
    return {"x": x, "z0": z0, "eps": eps, "y": y, "late": late,
            "hash": digest(x, z0, eps, y), "source": source}


def passage_features(z, boundary, ordinary=False):
    """Exact fixed-law one-sided hit CDF and discounted hit transform.

    Brownian drift=0, sigma=.55, horizon=.8, discount=.7. At/through a
    boundary there is a time-zero atom. This function does not claim that
    the nonlinear network trajectory follows this frozen Brownian law.
    """
    if ordinary:
        return np.tanh(z / boundary), np.tanh(2 * z / boundary)
    sigma, horizon, discount = 0.55, 0.8, 0.7
    k = np.sqrt(2 * discount * sigma**2)
    den = sigma * np.sqrt(horizon)
    def one_side(a):
        d = np.maximum(a, 0)
        f = 2 * ndtr(-d / den)
        g = (np.exp(-k * d / sigma**2) * ndtr((k * horizon - d) / den)
             + np.exp(np.minimum(k * d / sigma**2, 60)) *
             ndtr((-k * horizon - d) / den))
        return f, g
    upf, upg = one_side(boundary - z)
    dnf, dng = one_side(boundary + z)
    return upf - dnf, upg - dng


def channels(z, previous, boundary, mode, ordinary, h, derivatives=True):
    q, v = passage_features(z, boundary, ordinary)
    flow = (z - previous) / h
    f1, f2 = np.tanh(flow), np.tanh(2 * flow)
    if derivatives:
        delta = 1e-5
        zp = passage_features(z + delta, boundary, ordinary)
        zm = passage_features(z - delta, boundary, ordinary)
        bp = passage_features(z, boundary + delta, ordinary)
        bm = passage_features(z, boundary - delta, ordinary)
        dz = [(a - b) / (2 * delta) for a, b in zip(zp, zm)]
        db = [(a - b) / (2 * delta) for a, b in zip(bp, bm)]
        df = [(1 - f1**2) / h, 2 * (1 - f2**2) / h]
    if mode == "boundary":
        out = (q, v)
        if derivatives:
            dp = [np.zeros_like(z), np.zeros_like(z)]
    elif mode == "flow":
        out = (f1, f2)
        if derivatives:
            dz, dp, db = df, [-d for d in df], [np.zeros_like(z)] * 2
    elif mode == "both":
        out = ((q + f1) / np.sqrt(2), (v + f2) / np.sqrt(2))
        if derivatives:
            dz = [(a + b) / np.sqrt(2) for a, b in zip(dz, df)]
            dp = [-d / np.sqrt(2) for d in df]
            db = [d / np.sqrt(2) for d in db]
    else:
        raise ValueError(mode)
    if not derivatives:
        return np.concatenate(out, axis=1), None
    return np.concatenate(out, axis=1), (dz, dp, db)


class ResearchCellNet:
    def __init__(self, width, seed, mode="both", ordinary=False,
                 boundary_policy="fixed", graph="learned", qvi_bounds=None):
        rng = np.random.default_rng(seed)
        self.width, self.mode, self.ordinary = width, mode, ordinary
        self.boundary_policy, self.graph = boundary_policy, graph
        self.qvi_bounds = qvi_bounds
        self.h, self.leak, self.noise = 0.25, 0.25, 0.01
        self.p = {"win": rng.normal(0, 1.0, (4, width)),
                  "rec": rng.normal(0, 0.4 / np.sqrt(width), (2 * width, width)),
                  "bias": rng.normal(0, 0.1, width),
                  "out": rng.normal(0, 0.5 / np.sqrt(width), width),
                  "offset": np.zeros(1),
                  "boundary_raw": np.full(width, np.log(np.expm1(0.55)))}
        self.initial_rec = self.p["rec"].copy()
        self.keys = [k for k in self.p if k != "boundary_raw"]
        if boundary_policy == "learned":
            self.keys += ["boundary_raw"]
        if graph == "fixed":
            self.keys.remove("rec")

    def boundary(self, t):
        if self.boundary_policy == "qvi_prior":
            return np.full(self.width, self.qvi_bounds[t])
        return 0.2 + np.logaddexp(0, self.p["boundary_raw"])

    def forward(self, data, gradient=False, ablation=None):
        x, z = data["x"], data["z0"].copy()
        prev = z.copy()
        cache, outputs = [], []
        rec = self.p["rec"].copy()
        if ablation == "delete_edges":
            rec[:] = 0
        permutation = np.random.default_rng(9981).permutation(z.shape[0])
        for t in range(len(x)):
            m, deriv = channels(z, prev, self.boundary(t), self.mode,
                                self.ordinary, self.h, gradient)
            if ablation == "shuffle_messages":
                m = m[permutation]
            a = np.tanh(x[t] @ self.p["win"] + m @ rec + self.p["bias"])
            nxt = ((1 - self.h * self.leak) * z + self.h * a +
                   self.noise * np.sqrt(self.h) * data["eps"][t])
            cache.append((m, a, deriv))
            prev, z = z, nxt
            outputs.append(np.tanh(z) @ self.p["out"] + self.p["offset"][0])
        logits = outputs[-1]
        prob = 1 / (1 + np.exp(-np.clip(logits, -40, 40)))
        if not gradient:
            return prob, np.array(outputs)
        error = (prob - data["y"]) / len(prob)
        grads = {k: np.zeros_like(v) for k, v in self.p.items()}
        final = np.tanh(z)
        grads["out"] = final.T @ error
        grads["offset"][0] = np.sum(error)
        adj = [np.zeros_like(z) for _ in range(len(x) + 1)]
        adj[-1] = error[:, None] * self.p["out"] * (1 - final**2)
        for t in range(len(x) - 1, -1, -1):
            m, a, (dz, dp, db) = cache[t]
            drive_grad = adj[t + 1] * self.h * (1 - a**2)
            grads["win"] += x[t].T @ drive_grad
            grads["rec"] += m.T @ drive_grad
            grads["bias"] += drive_grad.sum(axis=0)
            mg = drive_grad @ rec.T
            parts = [mg[:, :self.width], mg[:, self.width:]]
            adj[t] += (1 - self.h * self.leak) * adj[t + 1]
            adj[t] += sum(a * b for a, b in zip(parts, dz))
            adj[max(t - 1, 0)] += sum(a * b for a, b in zip(parts, dp))
            grads["boundary_raw"] += sum((a * b).sum(axis=0)
                                          for a, b in zip(parts, db))
        grads["boundary_raw"] *= 1 / (1 + np.exp(-self.p["boundary_raw"]))
        return prob, grads

    def fit(self, training, validation, steps=180, batch=64, seed=0):
        started = time.perf_counter()
        rng = np.random.default_rng(seed + 991)
        first, second = ({k: np.zeros_like(self.p[k]) for k in self.keys}
                         for _ in range(2))
        best, best_loss, best_step = None, float("inf"), 0
        curve = []
        for step in range(steps + 1):
            if step % 30 == 0 or step == steps:
                prob, _ = self.forward(validation)
                loss = cross_entropy(prob, validation["y"])
                curve.append({"step": step, "validation_ce": loss})
                if loss < best_loss:
                    best = {k: v.copy() for k, v in self.p.items()}
                    best_loss, best_step = loss, step
            if step == steps:
                break
            indices = rng.integers(0, len(training["y"]), batch)
            sub = {"x": training["x"][:, indices], "z0": training["z0"][indices],
                   "eps": training["eps"][:, indices], "y": training["y"][indices]}
            _, grads = self.forward(sub, gradient=True)
            norm = np.sqrt(sum(np.sum(grads[k]**2) for k in self.keys))
            scale = min(1.0, 2.0 / (norm + 1e-15))
            for k in self.keys:
                g = grads[k] * scale
                first[k] = 0.9 * first[k] + 0.1 * g
                second[k] = 0.999 * second[k] + 0.001 * g**2
                self.p[k] -= 0.012 * (first[k] / (1 - 0.9**(step + 1))) / (
                    np.sqrt(second[k] / (1 - 0.999**(step + 1))) + 1e-8)
        self.p = best
        return {"fit_wall_seconds": time.perf_counter() - started,
                "optimizer": "explicit_numpy_BPTT_Adam", "steps": steps,
                "batch": batch, "training_examples_seen": steps * batch,
                "selected_step": best_step, "validation_ce": best_loss,
                "curve": curve, "total_parameters": sum(v.size for v in self.p.values()),
                "trainable_parameters": sum(self.p[k].size for k in self.keys),
                "recurrent_update_norm": float(np.linalg.norm(self.p["rec"] - self.initial_rec)),
                "weights_sha256": digest(*[self.p[k] for k in sorted(self.p)])}


def cross_entropy(prob, y):
    p = np.clip(prob, 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log1p(-p)))


def evaluate(net, data, ablation=None):
    start = time.perf_counter()
    prob, logits = net.forward(data, ablation=ablation)
    pre = 1 / (1 + np.exp(-np.clip(logits[5], -40, 40)))
    return {"accuracy": float(np.mean((prob >= 0.5) == data["y"])),
            "ce": cross_entropy(prob, data["y"]),
            "brier": float(np.mean((prob - data["y"])**2)),
            "pre_reveal_accuracy": float(np.mean((pre >= 0.5) == data["y"])),
            "prediction_sha256": digest(prob),
            "evaluation_wall_seconds": time.perf_counter() - start}


def gradient_check():
    """Independent FD of end-to-end CE checks BPTT and finite-difference kernels."""
    data = delayed_data(441, 7, 8)
    errors = {}
    for mode in ("boundary", "flow", "both"):
        net = ResearchCellNet(8, 71, mode, boundary_policy="learned")
        _, grad = net.forward(data, gradient=True)
        for name, index in (("win", (0, 1)), ("rec", (3, 2)),
                            ("boundary_raw", (2,)), ("out", (1,))):
            old = net.p[name][index]
            eps = 1e-5
            net.p[name][index] = old + eps
            plus = cross_entropy(net.forward(data)[0], data["y"])
            net.p[name][index] = old - eps
            minus = cross_entropy(net.forward(data)[0], data["y"])
            net.p[name][index] = old
            fd, ad = (plus - minus) / (2 * eps), grad[name][index]
            errors[mode + ":" + name] = float(abs(fd - ad))
    return {"maximum_absolute_error": max(errors.values()), "errors": errors,
            "passed": max(errors.values()) < 2e-6}
