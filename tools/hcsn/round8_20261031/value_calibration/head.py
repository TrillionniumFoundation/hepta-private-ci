"""A trained action-value head anchored to the known terminal STOP payoff.

Only the finite training model supplies labels. Runtime evaluates these fitted
weights, never an oracle, action table, optimum certificate or held-out label.
All three arms use the same capacity, objective, optimizer and iteration cap.
"""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize


class CalibratedHead:
    def __init__(self, center, scale, w1, b1, w2, b2):
        self.center, self.scale = np.asarray(center), np.asarray(scale)
        self.w1, self.b1, self.w2, self.b2 = map(np.asarray, (w1, b1, w2, b2))

    def predict(self, joined, stop):
        normalized = (joined - self.center) / self.scale
        h = np.tanh(normalized @ self.w1 + self.b1)
        advantage = h @ self.w2 + self.b2
        return np.concatenate((advantage, np.zeros((*advantage.shape[:-1], 1))), -1) + stop[..., None]

    def record(self):
        return {k: getattr(self, k).tolist() for k in ("center", "scale", "w1", "b1", "w2", "b2")}

    def save(self, path, metadata):
        payload = {"schema": "hepta.round8.calibrated-value-head.v1",
            "weights": self.record(), "metadata": metadata}
        Path(path).write_text(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text())["weights"])


def objective(parameters, x, target, mask, weights, hidden):
    """Exact reverse-mode derivative of direct-value and legal action-gap MSE."""
    width = x.shape[1]
    sizes = (width * hidden, hidden, hidden * 3)
    i, j, k = sizes[0], sum(sizes[:2]), sum(sizes)
    w1 = parameters[:i].reshape(width, hidden)
    b1 = parameters[i:j]
    w2 = parameters[j:k].reshape(hidden, 3)
    b2 = parameters[k:]
    h = np.tanh(x @ w1 + b1)
    error = (h @ w2 + b2 - target) * mask
    normalization = np.sum(weights[:, None] * mask)
    weighted = weights[:, None] * error
    value_loss = np.sum(weighted * error) / normalization
    # Include STOP error=0. The pairwise error objective improves value gaps
    # without substituting a classification-only policy for calibrated Q.
    full = np.column_stack((error, np.zeros(len(x))))
    allowed = np.column_stack((mask, np.ones(len(x), dtype=bool)))
    count = allowed.sum(-1)
    total = full.sum(-1)
    pair_loss = np.sum(weights * (count * np.sum(full ** 2, -1) - total ** 2)) / normalization
    derivative = (2 * weighted + 2 * weights[:, None] *
        (count[:, None] * error - total[:, None]) * mask) / normalization
    d2 = h.T @ derivative
    db2 = derivative.sum(0)
    dh = (derivative @ w2.T) * (1 - h ** 2)
    gradient = np.r_[(x.T @ dh).ravel(), dh.sum(0), d2.ravel(), db2]
    penalty = 1e-8
    return value_loss + pair_loss + penalty * float(parameters @ parameters), gradient + 2 * penalty * parameters


def fit(joined, q_target, legal, state_weights, seed, *, hidden=32, iterations=600):
    started, cpu = time.perf_counter(), time.process_time()
    shape = joined.shape
    x = joined.reshape(-1, shape[-1])
    center, scale = x.mean(0), x.std(0)
    scale = np.where(scale > 1e-10, scale, 1.)
    x = (x - center) / scale
    mask = np.broadcast_to(legal[:, None, :3], (*shape[:2], 3)).reshape(-1, 3)
    stop = q_target[:, :, 3]
    y = np.where(mask, (q_target[:, :, :3] - stop[:, :, None]).reshape(-1, 3), 0.)
    weights = np.repeat(state_weights / shape[1], shape[1])
    active = mask.any(-1)
    x, y, mask, weights = x[active], y[active], mask[active], weights[active]
    rng = np.random.default_rng(seed)
    initial = np.r_[rng.normal(0, .25, (shape[-1], hidden)).ravel(), np.zeros(hidden),
        rng.normal(0, .02, (hidden, 3)).ravel(), np.zeros(3)]
    curve = []
    calls = 0
    def function(theta):
        nonlocal calls
        calls += 1
        value, gradient = objective(theta, x, y, mask, weights, hidden)
        if not np.isfinite(value) or not np.isfinite(gradient).all():
            raise FloatingPointError("nonfinite head objective")
        return value, gradient
    def callback(theta):
        value, gradient = function(theta)
        curve.append({"iteration": len(curve) + 1, "objective": float(value),
            "gradient_l2": float(np.linalg.norm(gradient))})
    initial_loss, initial_grad = function(initial)
    result = minimize(function, initial.copy(), method="L-BFGS-B", jac=True, callback=callback,
        options={"maxiter": iterations, "maxfun": iterations * 3, "ftol": 1e-13,
                 "gtol": 1e-8, "maxls": 30})
    d = shape[-1] * hidden
    w1 = result.x[:d].reshape(shape[-1], hidden)
    b1 = result.x[d:d + hidden]
    w2 = result.x[d + hidden:-3].reshape(hidden, 3)
    head = CalibratedHead(center, scale, w1, b1, w2, result.x[-3:])
    metadata = {"seed": seed, "hidden": hidden, "iteration_cap": iterations,
        "actual_iterations": int(result.nit), "function_calls": calls,
        "optimizer_success": bool(result.success), "termination": str(result.message),
        "initial_objective": float(initial_loss), "final_objective": float(result.fun),
        "initial_gradient_l2": float(np.linalg.norm(initial_grad)),
        "final_gradient_l2": float(np.linalg.norm(result.jac)), "curve": curve,
        "parameter_count": len(result.x), "parameter_change_l2": float(np.linalg.norm(result.x - initial)),
        "initial_parameter_sha256": hashlib.sha256(initial.tobytes()).hexdigest(),
        "training_rows": len(x), "training_cpu_seconds": time.process_time() - cpu,
        "training_wall_seconds": time.perf_counter() - started,
        "teacher": "known finite joint-state optimal action values; supervised distillation",
        "stop_anchor": "known terminal payoff minus submission and compute cost",
        "online_oracle": False, "joint_dynamics_training": False}
    return head, metadata
