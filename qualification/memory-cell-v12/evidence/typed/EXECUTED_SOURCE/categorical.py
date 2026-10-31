"""Categorical source-memory training; separate from V12 content BCE training.

Targets are distributions over required source IDs. Empty targets contribute no
categorical training examples; abstention is calibrated separately on past data.
"""

import hashlib
import time

import numpy as np
from scipy.special import logsumexp

from learned import ARRAY_NAMES, MLP, parameter_digest


def train_categorical(X, Y, hidden=64, steps=600, seed=1, learning_rate=.01,
                      batch_size=32, initial=None):
    X, Y = np.asarray(X, dtype=np.float32), np.asarray(Y, dtype=np.float32)
    if X.ndim != 2 or Y.ndim != 2 or len(X) != len(Y) or not len(X):
        raise ValueError("nonempty aligned matrices required")
    if not np.isfinite(X).all() or not np.isfinite(Y).all() or (Y < 0).any():
        raise ValueError("finite nonnegative targets required")
    if not (1 <= hidden <= 256 and 0 < steps <= 100000 and 0 < batch_size <= 4096):
        raise ValueError("training budget bound")
    kept = np.flatnonzero(Y.sum(axis=1) > 0)
    if not len(kept):
        raise ValueError("no positive categorical targets")
    original_rows = len(X)
    X, Y = X[kept], Y[kept]
    Y = Y / Y.sum(axis=1, keepdims=True)
    rng = np.random.default_rng(seed)
    if initial is None:
        arrays = {"hidden.weight": (rng.standard_normal((hidden, X.shape[1])) * (2 / X.shape[1])**.5).astype(np.float32),
                  "hidden.bias": np.zeros(hidden, np.float32),
                  "head.weight": (rng.standard_normal((Y.shape[1], hidden)) / hidden**.5).astype(np.float32),
                  "head.bias": np.zeros(Y.shape[1], np.float32)}
        model = MLP(arrays)
    else:
        if initial.receipt.get("objective") != "softmax_cross_entropy":
            raise ValueError("continuation objective differs")
        model = MLP.from_export(initial.export(include_optimizer=True))
        if model.arrays["hidden.weight"].shape != (hidden, X.shape[1]) or model.arrays["head.weight"].shape[0] != Y.shape[1]:
            raise ValueError("continuation shape mismatch")
    before = {name: value.copy() for name, value in model.arrays.items()}
    if model.optimizer is None:
        model.optimizer = {"step": 0, "moments": {name: {"m": np.zeros_like(value), "v": np.zeros_like(value)}
                                                  for name, value in model.arrays.items()}}
    start_step = model.optimizer["step"]
    wall, cpu = time.perf_counter(), time.process_time()
    schedule = hashlib.sha256()
    maximum = {name: 0. for name in ARRAY_NAMES}
    trace, a = [], model.arrays
    for step in range(steps):
        chosen = rng.integers(0, len(X), size=batch_size)
        schedule.update(kept[chosen].astype("<i8").tobytes())
        x, y = X[chosen], Y[chosen]
        pre = x @ a["hidden.weight"].T + a["hidden.bias"]
        h = np.maximum(pre, 0)
        logits = h @ a["head.weight"].T + a["head.bias"]
        log_probabilities = logits - logsumexp(logits, axis=1, keepdims=True)
        delta = (np.exp(log_probabilities) - y) / batch_size
        dh = (delta @ a["head.weight"]) * (pre > 0)
        gradients = {"head.weight": delta.T @ h, "head.bias": delta.sum(axis=0),
                     "hidden.weight": dh.T @ x, "hidden.bias": dh.sum(axis=0)}
        model.optimizer["step"] += 1
        t = model.optimizer["step"]
        for name, grad in gradients.items():
            if not np.isfinite(grad).all():
                raise FloatingPointError("nonfinite categorical gradient")
            maximum[name] = max(maximum[name], float(np.linalg.norm(grad)))
            moment = model.optimizer["moments"][name]
            moment["m"] *= .9
            moment["m"] += .1 * grad
            moment["v"] *= .999
            moment["v"] += .001 * grad * grad
            a[name] -= learning_rate * (moment["m"] / (1 - .9**t)) / (np.sqrt(moment["v"] / (1 - .999**t)) + 1e-8)
        if step == 0 or (step + 1) % 100 == 0 or step + 1 == steps:
            trace.append(dict(step=step + 1, loss=float(-(y * log_probabilities).sum(axis=1).mean())))
    model.receipt = dict(objective="softmax_cross_entropy", seed=seed, steps=steps, batch_size=batch_size,
                         initial_optimizer_step=start_step, optimizer_step=model.optimizer["step"],
                         sample_presentations=steps * batch_size, observations=len(X),
                         ignored_empty_target_rows=original_rows - len(X),
                         schedule_sha256=schedule.hexdigest(), learning_rate=learning_rate,
                         trainable_parameters=sum(v.size for v in a.values()),
                         parameter_bytes=sum(v.nbytes for v in a.values()),
                         optimizer_bytes=sum(v.nbytes for item in model.optimizer["moments"].values() for v in item.values()),
                         initial_parameter_sha256=parameter_digest(before), final_parameter_sha256=parameter_digest(a),
                         max_gradient_norm=maximum,
                         parameter_change_norm={n: float(np.linalg.norm(a[n] - before[n])) for n in a},
                         trace=trace, fit_wall_seconds=time.perf_counter() - wall,
                         fit_cpu_seconds=time.process_time() - cpu)
    return model
