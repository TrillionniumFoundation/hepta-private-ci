"""Fully trained bounded recurrent policies, separate from the sealed first study.

All three families have 464 live trainable scalars, 18 inputs and 6 persistent
states. The dual/GRU pair has identical initial effective weights and fixed
sign arrays. Only dual projects selected magnitudes to nonnegative values.
This is a signed dual-bank prior, not an exact financial option operator or a
proof of global monotonicity. The Elman control allocates more weights to its
readout. Inference here is Python; final action selection is delegated to NDU.
"""

import time

import numpy as np
from scipy.special import expit

INPUT_DIM, HIDDEN_DIM = 18, 6
KINDS = ("dual", "gru", "elman")
_GRU_SHAPES = {
    **{f"W{k}": (18, 6) for k in ("z", "r", "n")},
    **{f"U{k}": (6, 6) for k in ("z", "r", "n")},
    **{f"b{k}": (6,) for k in ("z", "r", "n")},
    "head": (6, 2),
    "head_bias": (2,),
}
_ELMAN_SHAPES = {
    "W": (18, 6),
    "U": (6, 6),
    "b": (6,),
    "M": (24, 12),
    "head": (12, 2),
    "head_bias": (2,),
}
_BANK = np.array([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])
_SIGNS = {
    "Wn": np.ones((18, 6)),
    "Un": np.outer(_BANK, _BANK),
    "head": np.column_stack((_BANK, -_BANK)),
}
# Input order: 11 public context values, margin, C, P, F, previous risk / dt,
# previous observed failure, and previous repair indicator.
_SIGNS["Wn"][11:] = np.outer([1, 1, -1, -1, -1, -1, 1], _BANK)
_MASK = np.zeros((18, 6), dtype=bool)
_MASK[11:] = True


def parameter_count(params):
    return sum(np.asarray(value).size for value in params.values())


def architecture(kind):
    if kind not in KINDS:
        raise ValueError("Unknown recurrent family")
    shapes = _ELMAN_SHAPES if kind == "elman" else _GRU_SHAPES
    return {
        "kind": kind,
        "input_dims": 18,
        "persistent_state_dims": 6,
        "trainable_scalars": sum(np.prod(shape).item() for shape in shapes.values()),
        "parameter_shapes": {name: list(shape) for name, shape in shapes.items()},
        "fixed_numeric_coefficients": 0 if kind == "elman" else 156,
        "matrix_multiply_scalars_per_tick": 456 if kind == "elman" else 444,
        "stop_logit": 0.0,
        "score_bound": 8.0,
        "prior": "projected signed dual-bank candidate/head magnitudes"
        if kind == "dual"
        else "unconstrained ordinary recurrent policy",
    }


def _validate(params, kind):
    if kind not in KINDS:
        raise ValueError("Unknown recurrent family")
    shapes = _ELMAN_SHAPES if kind == "elman" else _GRU_SHAPES
    if set(params) != set(shapes):
        raise ValueError("Parameter keys do not match the declared architecture")
    for name, shape in shapes.items():
        value = np.asarray(params[name])
        if (
            value.shape != shape
            or not np.isfinite(value).all()
            or np.any(np.abs(value) > 8)
        ):
            raise ValueError("Invalid bounded recurrent coefficient")
    if kind == "dual" and (
        np.any(params["Wn"][_MASK] < 0)
        or np.any(params["Un"] < 0)
        or np.any(params["head"] < 0)
    ):
        raise ValueError("Dual sign constraints violated")


def initialize(seed, kind):
    """Dual and GRU share the exact effective initial policy for a given seed."""
    if kind not in KINDS:
        raise ValueError("Unknown recurrent family")
    rng = np.random.Generator(np.random.Philox(int(seed)))
    shapes = _ELMAN_SHAPES if kind == "elman" else _GRU_SHAPES
    params = {
        name: rng.normal(0, 0.16, shape) if len(shape) == 2 else np.zeros(shape)
        for name, shape in shapes.items()
    }
    if kind != "elman":
        params["Wn"][_MASK] = np.abs(params["Wn"][_MASK])
        params["Un"] = np.abs(params["Un"])
        params["head"] = np.abs(params["head"])
    _validate(params, kind)
    return params


def _effective(params, kind):
    return {
        name: value * _SIGNS[name] if kind != "elman" and name in _SIGNS else value
        for name, value in params.items()
    }


def _one(x, reset, previous, effective, kind):
    old = previous * (1 - reset[:, None])
    p = effective
    if kind == "elman":
        h = np.tanh(x @ p["W"] + old @ p["U"] + p["b"])
        joined = np.column_stack((x, h))
        readout = np.tanh(joined @ p["M"])
        cache = {"joined": joined, "readout": readout}
    else:
        z = expit(x @ p["Wz"] + old @ p["Uz"] + p["bz"])
        r = expit(x @ p["Wr"] + old @ p["Ur"] + p["br"])
        n = np.tanh(x @ p["Wn"] + (r * old) @ p["Un"] + p["bn"])
        h = (1 - z) * old + z * n
        readout = h
        cache = {"z": z, "r": r, "n": n, "readout": readout}
    logits = 8 * np.tanh((readout @ p["head"] + p["head_bias"]) / 8)
    scores = np.column_stack((logits, np.zeros(len(x))))
    cache.update(x=x, reset=reset, old=old, h=h, scores=scores)
    return scores, h, cache


def step(x, reset, state, params, kind):
    """One causal step. Return scores[B,3] and next state[B,6]."""
    _validate(params, kind)
    x, reset, state = [np.asarray(v, dtype=float) for v in (x, reset, state)]
    if (
        x.ndim != 2
        or x.shape[1] != 18
        or not len(x)
        or reset.shape != (len(x),)
        or state.shape != (len(x), 6)
    ):
        raise ValueError("Invalid recurrent step shape")
    if (
        not all(np.isfinite(v).all() for v in (x, reset, state))
        or np.any(np.abs(x) > 8)
        or np.any(np.abs(state) > 1)
        or np.any((reset < 0) | (reset > 1))
    ):
        raise ValueError("Invalid bounded recurrent input or state")
    scores, state, _ = _one(x, reset, state, _effective(params, kind), kind)
    return scores, state


def forward(x, resets, params, kind, return_cache=False):
    """Return (scores[T,B,3], states[T,B,6], cache or None), initially zero."""
    _validate(params, kind)
    x, resets = np.asarray(x, dtype=float), np.asarray(resets, dtype=float)
    if (
        x.ndim != 3
        or x.shape[-1] != 18
        or min(x.shape[:2]) < 1
        or resets.shape != x.shape[:2]
    ):
        raise ValueError("Invalid recurrent sequence shape")
    if (
        not np.isfinite(x).all()
        or not np.isfinite(resets).all()
        or np.any(np.abs(x) > 8)
        or np.any((resets < 0) | (resets > 1))
    ):
        raise ValueError("Invalid bounded recurrent sequence")
    p, state = _effective(params, kind), np.zeros((x.shape[1], 6))
    scores, states, cache = [], [], []
    for row, reset in zip(x, resets):
        score, state, item = _one(row, reset, state, p, kind)
        scores.append(score)
        states.append(state)
        cache.append(item)
    return np.asarray(scores), np.asarray(states), cache if return_cache else None


def loss_and_grad(x, resets, q, params, kind, mask=None):
    """CE plus normalized expected DP action regret; exact full NumPy BPTT.

    Q has physical task units and action order wait, repair, stop. Teacher ties
    prefer stop, then repair, then wait, matching the research NDU tie rule.
    Optional mask weights only observed training windows, not padding.
    """
    scores, _, cache = forward(x, resets, params, kind, return_cache=True)
    q = np.asarray(q, dtype=float)
    weights = (
        np.ones(scores.shape[:2]) if mask is None else np.asarray(mask, dtype=float)
    )
    if (
        q.shape != scores.shape
        or not np.isfinite(q).all()
        or weights.shape != scores.shape[:2]
        or not np.isfinite(weights).all()
        or np.any(weights < 0)
        or weights.sum() <= 0
    ):
        raise ValueError("Invalid teacher or training mask")
    weights = weights / weights.sum()
    shifted = scores - scores.max(axis=-1, keepdims=True)
    probability = np.exp(shifted)
    probability /= probability.sum(axis=-1, keepdims=True)
    labels = 2 - np.argmax(q[..., ::-1], axis=-1)
    one_hot = np.eye(3)[labels]
    gap = q.max(axis=-1, keepdims=True) - q
    regret = gap / (1 + gap.max(axis=-1, keepdims=True))
    expected = np.sum(probability * regret, axis=-1)
    ce = -np.sum(one_hot * np.log(probability), axis=-1)
    loss = float(np.sum(weights * (ce + expected)))
    score_grad = (
        probability - one_hot + probability * (regret - expected[..., None])
    ) * weights[..., None]
    gradients = {name: np.zeros_like(value) for name, value in params.items()}
    p, carry = _effective(params, kind), np.zeros((scores.shape[1], 6))
    for item, derivative in zip(reversed(cache), reversed(score_grad)):
        logits_grad = derivative[:, :2] * (1 - (item["scores"][:, :2] / 8) ** 2)
        gradients["head"] += item["readout"].T @ logits_grad
        gradients["head_bias"] += logits_grad.sum(axis=0)
        readout_grad = logits_grad @ p["head"].T
        if kind == "elman":
            hidden_grad = readout_grad * (1 - item["readout"] ** 2)
            gradients["M"] += item["joined"].T @ hidden_grad
            dh = (hidden_grad @ p["M"].T)[:, 18:] + carry
            candidate_grad = dh * (1 - item["h"] ** 2)
            gradients["W"] += item["x"].T @ candidate_grad
            gradients["U"] += item["old"].T @ candidate_grad
            gradients["b"] += candidate_grad.sum(axis=0)
            old_grad = candidate_grad @ p["U"].T
        else:
            dh = readout_grad + carry
            z, r, n, old = [item[name] for name in ("z", "r", "n", "old")]
            candidate_grad = dh * z * (1 - n**2)
            z_grad = dh * (n - old) * z * (1 - z)
            reset_hidden_grad = candidate_grad @ p["Un"].T
            r_grad = reset_hidden_grad * old * r * (1 - r)
            for gate, gate_grad in (
                ("z", z_grad),
                ("r", r_grad),
                ("n", candidate_grad),
            ):
                gradients["W" + gate] += item["x"].T @ gate_grad
                gradients["U" + gate] += (r * old if gate == "n" else old).T @ gate_grad
                gradients["b" + gate] += gate_grad.sum(axis=0)
            old_grad = (
                dh * (1 - z)
                + reset_hidden_grad * r
                + z_grad @ p["Uz"].T
                + r_grad @ p["Ur"].T
            )
        carry = old_grad * (1 - item["reset"][:, None])
    if kind != "elman":
        for name, signs in _SIGNS.items():
            gradients[name] *= signs
    return (
        loss,
        gradients,
        {
            "cross_entropy": float(np.sum(weights * ce)),
            "normalized_expected_regret": float(np.sum(weights * expected)),
            "teacher_action_accuracy": float(
                np.sum(
                    weights * (labels == (2 - np.argmax(scores[..., ::-1], axis=-1)))
                )
            ),
        },
    )


def fit(x, resets, q, params, kind, *, learning_rate, epochs=120, mask=None):
    """Full-batch Adam, fixed schedule, norm clip 5, coefficient bound 8."""
    if (
        not np.isfinite(learning_rate)
        or learning_rate <= 0
        or not isinstance(epochs, int)
        or epochs < 1
    ):
        raise ValueError("Invalid optimizer schedule")
    params = {name: value.copy() for name, value in params.items()}
    _validate(params, kind)
    initial = {name: value.copy() for name, value in params.items()}
    moments = [
        {name: np.zeros_like(value) for name, value in params.items()} for _ in range(2)
    ]
    seen = {name: np.zeros(value.shape, dtype=bool) for name, value in params.items()}
    losses, norm_clips, projected = [], 0, 0
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    for iteration in range(1, epochs + 1):
        loss, gradients, _ = loss_and_grad(x, resets, q, params, kind, mask)
        losses.append(loss)
        norm = np.sqrt(sum(np.sum(value**2) for value in gradients.values()))
        factor = min(1.0, 5.0 / max(float(norm), 1e-30))
        norm_clips += int(factor < 1)
        for name, value in params.items():
            seen[name] |= gradients[name] != 0
            gradient = gradients[name] * factor
            moments[0][name] = 0.9 * moments[0][name] + 0.1 * gradient
            moments[1][name] = 0.999 * moments[1][name] + 0.001 * gradient**2
            first = moments[0][name] / (1 - 0.9**iteration)
            second = moments[1][name] / (1 - 0.999**iteration)
            updated = value - learning_rate * first / (np.sqrt(second) + 1e-8)
            value[:] = np.clip(updated, -8, 8)
            if kind == "dual" and name in _SIGNS:
                if name == "Wn":
                    value[_MASK] = np.maximum(value[_MASK], 0)
                else:
                    np.maximum(value, 0, out=value)
            projected += int(np.count_nonzero(value != updated))
    final_loss, _, metrics = loss_and_grad(x, resets, q, params, kind, mask)
    receipt = {
        "architecture": architecture(kind),
        "optimizer": "full-batch projected Adam",
        "epochs": epochs,
        "gradient_evaluations": epochs + 1,
        "learning_rate": learning_rate,
        "gradient_clip_norm": 5.0,
        "gradient_clip_steps": norm_clips,
        "coefficient_bound": 8.0,
        "projected_coordinate_updates": projected,
        "epoch_loss": losses,
        "final_loss": final_loss,
        "final_metrics": metrics,
        "coordinates_with_nonzero_gradient": {
            name: int(value.sum()) for name, value in seen.items()
        },
        "parameter_change_l2": {
            name: float(np.linalg.norm(value - initial[name]))
            for name, value in params.items()
        },
        "python_cpu_seconds": time.process_time() - start_cpu,
        "wall_seconds": time.perf_counter() - start_wall,
    }
    _validate(params, kind)
    return params, receipt


def serialize(params, kind):
    _validate(params, kind)
    return {
        "schema": "hepta.continuous-boundary-policy.cell.v1",
        "architecture": architecture(kind),
        "params": {name: value.tolist() for name, value in params.items()},
        "fixed_sign_arrays": {}
        if kind == "elman"
        else {name: value.tolist() for name, value in _SIGNS.items()},
        "dual_input_constraint_rows": list(range(11, 18)) if kind != "elman" else [],
    }


def deserialize(snapshot):
    if snapshot.get("schema") != "hepta.continuous-boundary-policy.cell.v1":
        raise ValueError("Unknown recurrent checkpoint schema")
    kind = snapshot["architecture"]["kind"]
    params = {
        name: np.asarray(value, dtype=float)
        for name, value in snapshot["params"].items()
    }
    _validate(params, kind)
    if snapshot != serialize(params, kind):
        raise ValueError("Checkpoint architecture or fixed coefficients changed")
    return params, kind
