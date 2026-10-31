"""Train a normalized 100-target joint posterior with proper joint log score.

Both encoder feature vectors enter one shared network. Its 100 logits are not
constructed by multiplying two ten-class predictions. This executable estimator
does not establish calibration, generalization or superiority without data.
"""

import math

import numpy as np


SCHEMA = "hepta.repair.joint-target-posterior.v1"


def group_weights(groups):
    if not groups or any(type(g) is not str or not g for g in groups):
        raise ValueError("Nonempty opaque source-group IDs are required")
    counts = {g: groups.count(g) for g in set(groups)}
    return np.array([1. / (len(counts) * counts[g]) for g in groups])


class JointPrior:
    """One tanh hidden layer and a full joint categorical output."""

    def __init__(self, mean, scale, parameters, provenance=None):
        self.mean, self.scale = np.asarray(mean, float), np.asarray(scale, float)
        self.parameters = {k: np.asarray(v, float).copy() for k, v in parameters.items()}
        p = self.parameters
        if (set(p) != {"w1", "b1", "w2", "b2"} or self.mean.ndim != 1
                or not len(self.mean) or self.scale.shape != self.mean.shape
                or not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all()
                or (self.scale <= 0).any() or p["w1"].ndim != 2
                or p["w1"].shape[1] != len(self.mean)
                or p["b1"].shape != (len(p["w1"]),)
                or p["w2"].shape != (100, len(p["w1"])) or p["b2"].shape != (100,)
                or any(not np.isfinite(v).all() for v in p.values())):
            raise ValueError("Invalid full-joint posterior parameters")
        self.provenance = dict(provenance or {})

    def _forward(self, features):
        x = np.asarray(features, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != len(self.mean) or not np.isfinite(x).all():
            raise ValueError("Finite paired public encoder features are required")
        x = (x - self.mean) / self.scale
        p = self.parameters
        hidden = np.tanh(x @ p["w1"].T + p["b1"])
        logits = hidden @ p["w2"].T + p["b2"]
        logits -= logits.max(1, keepdims=True)
        log_q = logits - np.log(np.exp(logits).sum(1, keepdims=True))
        return x, hidden, log_q

    def predict(self, features):
        return np.exp(self._forward(features)[2])

    def loss_and_gradient(self, features, targets, weights, l2=0.):
        """Exact minibatch joint-NLL gradient, with explicit optional regularization."""
        x, hidden, log_q = self._forward(features)
        target, weights = np.asarray(targets), np.asarray(weights, float)
        if (target.shape != (len(x),) or target.dtype.kind not in "iu"
                or (target < 0).any() or (target >= 100).any()
                or weights.shape != target.shape or not np.isfinite(weights).all()
                or (weights < 0).any() or not math.isclose(float(weights.sum()), 1., abs_tol=1e-12)
                or not math.isfinite(l2) or l2 < 0):
            raise ValueError("Normalized fitting weights and actual joint target codes required")
        p = self.parameters
        loss = -float(weights @ log_q[np.arange(len(x)), target])
        loss += .5 * l2 * (np.square(p["w1"]).sum() + np.square(p["w2"]).sum())
        delta = np.exp(log_q)
        delta[np.arange(len(x)), target] -= 1.
        delta *= weights[:, None]
        back = (delta @ p["w2"]) * (1. - hidden * hidden)
        return loss, {"w2": delta.T @ hidden + l2 * p["w2"], "b2": delta.sum(0),
                      "w1": back.T @ x + l2 * p["w1"], "b1": back.sum(0)}

    @classmethod
    def fit(cls, features, targets, groups, *, steps, learning_rate, seed, hidden=32,
            l2=0., excluded_groups=()):
        x, targets, groups = np.asarray(features, float), np.asarray(targets), list(groups)
        if (x.ndim != 2 or len(x) != len(groups) or len(x) < 2
                or not np.isfinite(x).all() or set(groups) & set(excluded_groups)
                or type(steps) is not int or steps <= 0 or type(hidden) is not int or hidden <= 0
                or not math.isfinite(learning_rate) or learning_rate <= 0):
            raise ValueError("Invalid source-separated training inputs or fixed schedule")
        weights = group_weights(groups)
        mean = weights @ x
        scale = np.sqrt(weights @ np.square(x - mean))
        scale = np.where(scale < 1e-8, 1., scale)
        rng = np.random.default_rng(seed)
        p = {"w1": rng.normal(0, 1. / math.sqrt(x.shape[1]), (hidden, x.shape[1])),
             "b1": np.zeros(hidden), "w2": rng.normal(0, .01, (100, hidden)), "b2": np.zeros(100)}
        model = cls(mean, scale, p)
        first = model.loss_and_gradient(x, targets, weights, l2)[0]
        m, v = ({k: np.zeros_like(a) for k, a in p.items()} for _ in range(2))
        for step in range(1, steps + 1):
            loss, gradients = model.loss_and_gradient(x, targets, weights, l2)
            if not math.isfinite(loss) or any(not np.isfinite(g).all() for g in gradients.values()):
                raise ValueError("Nonfinite training trajectory; no model may be exported")
            for key, gradient in gradients.items():
                m[key] = .9 * m[key] + .1 * gradient
                v[key] = .999 * v[key] + .001 * gradient * gradient
                model.parameters[key] -= learning_rate * (m[key] / (1 - .9 ** step)) / (
                    np.sqrt(v[key] / (1 - .999 ** step)) + 1e-8)
        final = model.loss_and_gradient(x, targets, weights, l2)[0]
        model.provenance = {"source_groups": sorted(set(groups)), "training_rows": len(x),
                            "steps": steps, "learning_rate": learning_rate, "seed": seed,
                            "l2": l2, "initial_objective": first, "final_objective": final,
                            "objective": "source-group-weighted joint NLL plus declared L2",
                            "statistical_qualification": "not established"}
        return model

    def export(self):
        return {"schema": SCHEMA, "target_order": "left*10+right", "activation": "tanh",
                "mean": self.mean.tolist(), "scale": self.scale.tolist(),
                "parameters": {k: v.tolist() for k, v in self.parameters.items()},
                "provenance": self.provenance}

    @classmethod
    def load(cls, record):
        if (record.get("schema") != SCHEMA or record.get("target_order") != "left*10+right"
                or record.get("activation") != "tanh"):
            raise ValueError("Wrong joint-target posterior schema")
        return cls(record["mean"], record["scale"], record["parameters"], record.get("provenance"))
