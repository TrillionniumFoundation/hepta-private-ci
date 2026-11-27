"""Two-unit, genuinely state-changing residual content updates; no routing."""

import numpy as np

from independent.learning import CachedObjective, objective_work
from model import JointModel, softmax


PATHS = ("TT", "TI", "IT", "II", "J")


def add_work(*parts):
    result = {}
    for part in parts:
        for key, value in part.items():
            result[key] = result.get(key, 0) + int(value)
    return result


def encode(base, x, ledger, stage):
    x = base._input(x)
    n, (_, k, _, h) = len(x), base.dimensions
    ledger.charge_kernel(stage, "fixed_features", macs=n * (202 * h + 2 * h * k),
        scalar_ops=n * h + 2 * n * k, tanh_ops=n * h, compare_ops=x.size,
        counts={"feature_rows": n})
    hidden = np.tanh(x @ base.params["encoder"] + base.params["bias"])
    return hidden, hidden @ base.params["text"] + base.params["text_bias"], hidden @ base.params["image"] + base.params["image_bias"]


def forward_work(n, path, hidden=32):
    if path not in PATHS:
        raise ValueError("one of the five fixed two-unit paths required")
    # Every path applies exactly two single-head corrections, J simultaneously.
    k = 12
    return {"macs": 2 * n * (hidden * k + k * k),
        "scalar_ops": 2 * (5 * n * k - n) + 4 * n * k - 2 * n,
        "compare_ops": 4 * n * (k - 1), "exp_ops": 4 * n * k,
        "div_ops": 4 * n * k}


class Refiner:
    """Frozen h, recurrent text/image logits, six real trainable arrays."""

    apply_gradients = JointModel.apply_gradients

    def __init__(self, hidden=32):
        self.params = {"Wt": np.zeros((hidden, 12)), "Wi": np.zeros((hidden, 12)),
            "Ct": np.zeros((12, 12)), "Ci": np.zeros((12, 12)),
            "bt": np.zeros(12), "bi": np.zeros(12)}
        self._moments, self.updates = {}, 0

    def forward(self, features, path, *, tape=False):
        if path not in PATHS:
            raise ValueError("fixed two-unit path required")
        h, t, i = features
        history = []
        for action in path:
            old_t, old_i = t, i
            q = softmax(old_i) if action in ("T", "J") else None
            p = softmax(old_t) if action in ("I", "J") else None
            if q is not None:
                t = old_t + (h @ self.params["Wt"] + q @ self.params["Ct"] + self.params["bt"])
            if p is not None:
                i = old_i + (h @ self.params["Wi"] + p @ self.params["Ci"] + self.params["bi"])
            history.append((action, p, q))
        output = softmax(t), softmax(i)
        return (*output, history) if tape else output

    def loss_and_gradients(self, features, labels, objective, paths=PATHS):
        h = features[0]
        gradients = {key: np.zeros_like(value) for key, value in self.params.items()}
        loss = 0.0
        for path in paths:
            p, q, tape = self.forward(features, path, tape=True)
            value, dt, di = objective._policy_gradients_checked(p, q, labels)
            loss += value / len(paths)
            dt, di = dt / len(paths), di / len(paths)
            for action, previous_p, previous_q in reversed(tape):
                old_dt, old_di = dt, di
                if previous_q is not None:
                    gradients["Wt"] += h.T @ old_dt
                    gradients["Ct"] += previous_q.T @ old_dt
                    gradients["bt"] += old_dt.sum(0)
                    back = old_dt @ self.params["Ct"].T
                    di = old_di + previous_q * (back - np.sum(previous_q * back, axis=1, keepdims=True))
                if previous_p is not None:
                    gradients["Wi"] += h.T @ old_di
                    gradients["Ci"] += previous_p.T @ old_di
                    gradients["bi"] += old_di.sum(0)
                    back = old_di @ self.params["Ci"].T
                    dt = old_dt + previous_p * (back - np.sum(previous_p * back, axis=1, keepdims=True))
        return float(loss), gradients

    def step_work(self, n, arm):
        h, k = self.params["Wt"].shape
        size = sum(value.size for value in self.params.values())
        backward = {"macs": 10 * n * (h * k + 2 * k * k),
            "scalar_ops": 10 * ((n - 1) * k + 5 * n * k - n + h * k + k * k + k)}
        optimizer = {"scalar_ops": 13 * size + 24, "div_ops": 3 * size + 1,
            "sqrt_ops": size + 1, "pow_ops": 12, "compare_ops": size + 2}
        objective = objective_work(arm, n)
        # Divide both terminal directions by five and sum the five losses.
        accumulation = {"div_ops": 10 * n * k + 5, "scalar_ops": 5}
        return add_work(*(forward_work(n, path, h) for path in PATHS), backward,
                        *(objective for _ in PATHS), optimizer, accumulation)

    def step(self, features, labels, objective, lr, ledger, capture):
        ledger.charge_kernel("search_train", "five_path_refiner", **self.step_work(len(labels), objective.arm),
            counts={"content_updates": 1, "path_losses": 5, "single_head_actions": 10 * len(labels)})
        loss, gradients = self.loss_and_gradients(features, labels, objective)
        capture.apply_gradients(self, gradients, lr)
        return loss


class Capture:
    """Retain first/last actual optimizer inputs and first parameter movement."""

    def __init__(self, ledger, optimizer=None):
        self.ledger, self.first, self.last, self.first_delta = ledger, None, None, None
        self.optimizer = optimizer

    def apply_gradients(self, model, grads, lr):
        before = None
        if self.first is None:
            before = {key: model.params[key].copy() for key in grads}
            self.first = {key: value.copy() for key, value in grads.items()}
        if self.optimizer is None:
            model.apply_gradients(grads, lr)
        else:
            self.optimizer.apply_gradients(model, grads, lr)
        self.last = grads
        if before is not None:
            self.ledger.charge_kernel("gradient_evidence", "first_delta",
                                     scalar_ops=sum(value.size for value in before.values()))
            self.first_delta = {key: model.params[key] - value for key, value in before.items()}

    def save(self, path, model, initial, losses):
        arrays = {"loss": np.asarray(losses)}
        for label, values in (("first_gradient", self.first), ("last_gradient", self.last),
                              ("first_delta", self.first_delta)):
            arrays.update({label + "/" + key: value for key, value in values.items()})
        self.ledger.charge_kernel("gradient_evidence", "final_delta",
                                 scalar_ops=sum(value.size for value in initial.values()))
        arrays.update({"final_delta/" + key: model.params[key] - value for key, value in initial.items()})
        np.savez_compressed(path, **arrays)
        self.ledger.record("gradient_evidence", serialized_bytes=path.stat().st_size)
