"""Small, fully trained NumPy belief kernels for the controlled PRED-1 pilot.

The diagonal SSM is a deliberately simple stable recurrence, not R2I/Mamba.
Historical actions belong in x; candidate actions condition a common nonlinear
head, so changing a candidate never rewrites persistent observed belief.
"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np

KINDS = ("single_step", "gru", "diag_ssm", "dual_timescale")


def sigmoid(x):
    return np.exp(-np.logaddexp(0.0, -x))


def softmax(x):
    z = np.exp(x - x.max(axis=-1, keepdims=True))
    return z / z.sum(axis=-1, keepdims=True)


class Model:
    """A history encoder plus action-conditioned discrete joint-distribution head."""

    def __init__(self, kind, input_dim, action_dim, output_dim, hidden_dim, seed):
        if kind not in KINDS or min(input_dim, action_dim, output_dim, hidden_dim) < 1:
            raise ValueError("invalid model kind or dimensions")
        self.config = dict(
            kind=kind,
            input_dim=input_dim,
            action_dim=action_dim,
            output_dim=output_dim,
            hidden_dim=hidden_dim,
            seed=seed,
        )
        self.kind, self.d, self.a, self.k, self.h = (
            kind,
            input_dim,
            action_dim,
            output_dim,
            hidden_dim,
        )
        rng = np.random.default_rng(seed)
        self.params = {}

        def matrix(name, rows, cols):
            self.params[name] = rng.normal(0, np.sqrt(2 / (rows + cols)), (rows, cols))

        def bias(name, value=0.0):
            self.params[name] = np.full(hidden_dim, value, dtype=np.float64)

        if kind in ("gru", "dual_timescale"):
            for gate in ("z", "r", "n"):
                matrix("W" + gate, input_dim, hidden_dim)
                matrix("U" + gate, hidden_dim, hidden_dim)
                bias("b" + gate, -1.0 if gate == "z" else 0.0)
        else:
            matrix("Wx", input_dim, hidden_dim)
            bias("bx")
        if kind == "diag_ssm":
            rates = np.linspace(0.5, 0.98, hidden_dim)
            self.params["decay"] = np.log(rates / (1 - rates))
        if kind == "dual_timescale":
            matrix("Wsx", input_dim, hidden_dim)
            matrix("Wsf", hidden_dim, hidden_dim)
            bias("bs")
            bias("slow_decay", np.log(19.0))
        width = hidden_dim * (2 if kind == "dual_timescale" else 1)
        matrix("Wh", width + action_dim, hidden_dim)
        bias("bh")
        matrix("Wy", hidden_dim, output_dim)
        self.params["by"] = np.zeros(output_dim)
        self.m = {key: np.zeros_like(value) for key, value in self.params.items()}
        self.v = {key: np.zeros_like(value) for key, value in self.params.items()}
        self.steps = 0

    @property
    def parameter_count(self):
        return sum(value.size for value in self.params.values())

    def initial_state(self, batch_size=1):
        state = {"fast": np.zeros((batch_size, self.h))}
        if self.kind == "dual_timescale":
            state["slow"] = np.zeros((batch_size, self.h))
        return state

    def _step(self, x, state):
        p, previous = self.params, state["fast"]
        if self.kind in ("gru", "dual_timescale"):
            z = sigmoid(x @ p["Wz"] + previous @ p["Uz"] + p["bz"])
            r = sigmoid(x @ p["Wr"] + previous @ p["Ur"] + p["br"])
            n = np.tanh(x @ p["Wn"] + (r * previous) @ p["Un"] + p["bn"])
            fast = (1 - z) * previous + z * n
            cache = (x, previous, z, r, n)
        else:
            n = np.tanh(x @ p["Wx"] + p["bx"])
            alpha = sigmoid(p["decay"]) if self.kind == "diag_ssm" else 0.0
            fast = alpha * previous + (1 - alpha) * n
            cache = (x, previous, n, alpha)
        result = {"fast": fast}
        if self.kind == "dual_timescale":
            rho = sigmoid(p["slow_decay"])
            u = np.tanh(x @ p["Wsx"] + fast @ p["Wsf"] + p["bs"])
            result["slow"] = rho * state["slow"] + (1 - rho) * u
            cache = (cache, fast, state["slow"], u, rho)
        return result, cache

    def observe(self, observation, state):
        """Advance one real observation; return new arrays without mutating state."""
        observation = np.asarray(observation, dtype=np.float64)
        if (
            observation.ndim != 2
            or observation.shape[1] != self.d
            or not np.isfinite(observation).all()
        ):
            raise ValueError("observation must be finite [batch,input_dim]")
        expected = self.initial_state(len(observation))
        if set(state) != set(expected) or any(
            state[k].shape != v.shape for k, v in expected.items()
        ):
            raise ValueError("state shape mismatch")
        return self._step(observation, state)[0]

    def _head(self, state, action):
        pieces = [state["fast"]]
        if self.kind == "dual_timescale":
            pieces.append(state["slow"])
        features = np.concatenate(pieces + [action], axis=1)
        hidden = np.tanh(features @ self.params["Wh"] + self.params["bh"])
        return hidden @ self.params["Wy"] + self.params["by"], (features, hidden)

    def predict_from_state(self, state, action):
        """Predict logits for a candidate without advancing the belief state."""
        action = np.asarray(action, dtype=np.float64)
        if (
            action.shape != (len(state["fast"]), self.a)
            or not np.isfinite(action).all()
        ):
            raise ValueError("action must be finite [batch,action_dim]")
        return self._head(state, action)[0]

    def forward(self, x, action, reset=False, mask_action=False, cache=False):
        x, action = (
            np.asarray(x, dtype=np.float64),
            np.asarray(action, dtype=np.float64),
        )
        if (
            x.ndim != 3
            or x.shape[1] < 1
            or x.shape[2] != self.d
            or action.shape != (len(x), self.a)
        ):
            raise ValueError(
                "expected x[batch,time,input_dim] and action[batch,action_dim]"
            )
        if len(x) == 0 or not np.isfinite(x).all() or not np.isfinite(action).all():
            raise ValueError("empty or nonfinite inputs")
        if reset or self.kind == "single_step":
            x = x[:, -1:, :]
        if mask_action:
            action = np.zeros_like(action)
        state, history = self.initial_state(len(x)), []
        for t in range(x.shape[1]):
            state, item = self._step(x[:, t], state)
            if cache:
                history.append(item)
        logits, head = self._head(state, action)
        if cache:
            self._cache = (history, head)
        return logits

    def predict_proba(self, x, action, **kwargs):
        return softmax(self.forward(x, action, **kwargs))

    def loss_and_grads(self, x, action, allowed_mask, sample_weights=None, **kwargs):
        """Coarsened NLL: unknown/all-allowed targets contribute zero information."""
        logits = self.forward(x, action, cache=True, **kwargs)
        allowed = np.asarray(allowed_mask, dtype=bool)
        if allowed.shape != logits.shape or not allowed.any(axis=1).all():
            raise ValueError("each label must allow at least one joint category")
        weights = (
            np.ones(len(logits))
            if sample_weights is None
            else np.asarray(sample_weights, dtype=float)
        )
        if (
            weights.shape != (len(logits),)
            or not np.isfinite(weights).all()
            or (weights < 0).any()
            or weights.sum() <= 0
        ):
            raise ValueError("invalid sample weights")
        weights = weights / weights.sum()
        logz = np.logaddexp.reduce(logits, axis=1)
        allowed_logits = np.where(allowed, logits, -np.inf)
        logza = np.logaddexp.reduce(allowed_logits, axis=1)
        loss = float(weights @ (logz - logza))
        dl = (softmax(logits) - softmax(allowed_logits)) * weights[:, None]
        p = self.params
        g = {key: np.zeros_like(value) for key, value in p.items()}
        history, (features, hidden) = self._cache
        g["Wy"], g["by"] = hidden.T @ dl, dl.sum(axis=0)
        dh = (dl @ p["Wy"].T) * (1 - hidden**2)
        g["Wh"], g["bh"] = features.T @ dh, dh.sum(axis=0)
        dfeatures = dh @ p["Wh"].T
        df = dfeatures[:, : self.h]
        ds = (
            dfeatures[:, self.h : 2 * self.h] if self.kind == "dual_timescale" else None
        )
        for item in reversed(history):
            if self.kind == "dual_timescale":
                item, fast, previous_slow, u, rho = item
                du = ds * (1 - rho) * (1 - u**2)
                g["slow_decay"] += (
                    (ds * (previous_slow - u)).sum(axis=0) * rho * (1 - rho)
                )
                ds = ds * rho
                g["Wsx"] += item[0].T @ du
                g["Wsf"] += fast.T @ du
                g["bs"] += du.sum(axis=0)
                df = df + du @ p["Wsf"].T
            if self.kind in ("gru", "dual_timescale"):
                xt, previous, z, r, n = item
                dn = df * z * (1 - n**2)
                dz = df * (n - previous) * z * (1 - z)
                dproduct = dn @ p["Un"].T
                dr = dproduct * previous * r * (1 - r)
                for gate, delta, recurrent in (
                    ("n", dn, r * previous),
                    ("z", dz, previous),
                    ("r", dr, previous),
                ):
                    g["W" + gate] += xt.T @ delta
                    g["U" + gate] += recurrent.T @ delta
                    g["b" + gate] += delta.sum(axis=0)
                df = df * (1 - z) + dproduct * r + dz @ p["Uz"].T + dr @ p["Ur"].T
            else:
                xt, previous, n, alpha = item
                dn = df * (1 - alpha) * (1 - n**2)
                g["Wx"] += xt.T @ dn
                g["bx"] += dn.sum(axis=0)
                if self.kind == "diag_ssm":
                    g["decay"] += (
                        (df * (previous - n)).sum(axis=0) * alpha * (1 - alpha)
                    )
                df = df * alpha
        return loss, g

    def fit_step(
        self, x, action, allowed_mask, lr=0.003, clip=5.0, sample_weights=None, **kwargs
    ):
        loss, grads = self.loss_and_grads(
            x, action, allowed_mask, sample_weights, **kwargs
        )
        norm = np.sqrt(sum(np.sum(v**2) for v in grads.values()))
        if not np.isfinite(loss) or not np.isfinite(norm):
            raise FloatingPointError("nonfinite optimization step")
        if lr <= 0 or clip <= 0 or not np.isfinite([lr, clip]).all():
            raise ValueError("learning rate and clip must be finite and positive")
        if norm == 0.0:
            return loss  # Missing-only batches must not consume Adam momentum.
        scale = min(1.0, clip / max(norm, 1e-12))
        self.steps += 1
        for key, grad in grads.items():
            grad = grad * scale
            self.m[key] = 0.9 * self.m[key] + 0.1 * grad
            self.v[key] = 0.999 * self.v[key] + 0.001 * grad**2
            m = self.m[key] / (1 - 0.9**self.steps)
            v = self.v[key] / (1 - 0.999**self.steps)
            self.params[key] -= lr * m / (np.sqrt(v) + 1e-8)
        return loss

    def save(self, path):
        payload = {
            "config": np.array(json.dumps(self.config, sort_keys=True)),
            "steps": np.array(self.steps),
        }
        for group, values in (("p", self.params), ("m", self.m), ("v", self.v)):
            payload.update({group + "_" + key: value for key, value in values.items()})
        with Path(path).open("xb") as stream:
            np.savez_compressed(stream, **payload)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            model = cls(**json.loads(str(data["config"])))
            model.steps = int(data["steps"])
            if model.steps < 0:
                raise ValueError("invalid checkpoint optimizer step")
            for prefix, values in (("p", model.params), ("m", model.m), ("v", model.v)):
                for key, template in values.items():
                    value = data[prefix + "_" + key]
                    if value.shape != template.shape or not np.isfinite(value).all():
                        raise ValueError("invalid checkpoint parameter")
                    values[key] = value.copy()
        return model


def matched_hidden_dim(
    kind, input_dim, action_dim, output_dim, target_parameters, minimum=2, maximum=128
):
    """Nearest parameter count; actual counts must still be reported per model."""
    return min(
        range(minimum, maximum + 1),
        key=lambda h: abs(
            Model(kind, input_dim, action_dim, output_dim, h, 0).parameter_count
            - target_parameters
        ),
    )
