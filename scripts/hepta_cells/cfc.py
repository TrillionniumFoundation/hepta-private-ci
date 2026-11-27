"""Default CfC recurrence with exact NumPy BPTT for bounded Cell experiments.

Equation reference: ncps/torch/cfc_cell.py, default mode, backbone_layers=0,
commit 695ec22d7d1831f2ced67346ef7d2f08c525bd47 (Apache-2.0).
The final input feature is elapsed seconds; it is also an ordinary input feature
and must be supplied identically to the GRU baseline. Explicit (batch, 1) time
avoids the reference sequence wrapper's squeeze/broadcast hazard. Zero elapsed
time is not an identity transition in this equation; replay rejection is owned
by the lifecycle wrapper. This is neither the optional mixed-memory CfC nor LTC.

Initialization uses the PRED-1 normal scale, not the ncps initializer. Runtime
numerical parity is measured separately by cfc_reference_probe; it does not
establish initialization or task-performance equivalence. Validation receipts
identify the exact implementation bytes tested.
"""

import numpy as np

from hepta_pred1.models import Model, sigmoid, softmax


NCPS_REFERENCE_COMMIT = "695ec22d7d1831f2ced67346ef7d2f08c525bd47"
NCPS_REFERENCE_PATH = "ncps/torch/cfc_cell.py"


class CfCModel(Model):
    """Action-conditioned PRED-1 head with the default closed-form CfC cell."""

    def __init__(self, kind, input_dim, action_dim, output_dim, hidden_dim, seed):
        dims = (input_dim, action_dim, output_dim, hidden_dim)
        if kind != "cfc" or any(type(v) is not int or v < 1 for v in dims):
            raise ValueError("invalid CfC kind or dimensions")
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

        for gate in ("f1", "f2", "ta", "tb"):
            matrix("W" + gate, input_dim + hidden_dim, hidden_dim)
            self.params["b" + gate] = np.zeros(hidden_dim)
        matrix("Wh", hidden_dim + action_dim, hidden_dim)
        self.params["bh"] = np.zeros(hidden_dim)
        matrix("Wy", hidden_dim, output_dim)
        self.params["by"] = np.zeros(output_dim)
        self.m = {key: np.zeros_like(value) for key, value in self.params.items()}
        self.v = {key: np.zeros_like(value) for key, value in self.params.items()}
        self.steps = 0

    def _step(self, x, state):
        p = self.params
        dt = x[:, -1:]
        if not np.isfinite(dt).all() or (dt < 0).any():
            raise ValueError(
                "CfC final input feature must be finite nonnegative seconds"
            )
        z = np.concatenate((x, state["fast"]), axis=1)
        f1 = np.tanh(z @ p["Wf1"] + p["bf1"])
        f2 = np.tanh(z @ p["Wf2"] + p["bf2"])
        ta = z @ p["Wta"] + p["bta"]
        tb = z @ p["Wtb"] + p["btb"]
        gate = sigmoid(ta * dt + tb)
        return {"fast": (1 - gate) * f1 + gate * f2}, (z, dt, f1, f2, gate)

    def loss_and_grads(self, x, action, allowed_mask, sample_weights=None, **kwargs):
        """Coarsened NLL through every observation, including recurrent gates."""
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
        allowed_logits = np.where(allowed, logits, -np.inf)
        loss = float(
            weights
            @ (
                np.logaddexp.reduce(logits, axis=1)
                - np.logaddexp.reduce(allowed_logits, axis=1)
            )
        )
        dl = (softmax(logits) - softmax(allowed_logits)) * weights[:, None]
        p = self.params
        grads = {key: np.zeros_like(value) for key, value in p.items()}
        history, (features, hidden) = self._cache
        grads["Wy"], grads["by"] = hidden.T @ dl, dl.sum(axis=0)
        dh = (dl @ p["Wy"].T) * (1 - hidden**2)
        grads["Wh"], grads["bh"] = features.T @ dh, dh.sum(axis=0)
        df = (dh @ p["Wh"].T)[:, : self.h]
        for z, dt, f1, f2, gate in reversed(history):
            dg = df * (f2 - f1) * gate * (1 - gate)
            deltas = {
                "f1": df * (1 - gate) * (1 - f1**2),
                "f2": df * gate * (1 - f2**2),
                "ta": dg * dt,
                "tb": dg,
            }
            dz = np.zeros_like(z)
            for name, delta in deltas.items():
                grads["W" + name] += z.T @ delta
                grads["b" + name] += delta.sum(axis=0)
                dz += delta @ p["W" + name].T
            df = dz[:, self.d :]
        return loss, grads
