"""Matched 42-coefficient affine readouts over frozen native sparse activations.

This module trains no encoder and executes no native kernel or NDU. Float loss
gradients do not pass through Q24. The separate integer diagnostic implements
the existing native model.rs readout: ties-even rounding of each product, then
ordinary addition, with no score clamp. Bounds make integer overflow impossible.
"""

import hashlib
import time

import numpy as np

WIDTH, Q, BOUND = 20, 1 << 24, 7.5
OBJECTIVES = ("q_mse", "policy_regret")


def _parameters(weights):
    weights = np.asarray(weights, dtype=float)
    if weights.shape != (WIDTH + 1, 2) or not np.isfinite(weights).all():
        raise ValueError("Expected finite 21 by 2 coefficients, final row is bias")
    if np.any(np.abs(weights) > BOUND):
        raise ValueError("Readout coefficient bound violated")
    return weights


def _data(activation, teacher):
    x, q = np.asarray(activation, dtype=float), np.asarray(teacher, dtype=float)
    if x.ndim != 2 or x.shape[1] != WIDTH or not len(x):
        raise ValueError("Expected nonempty N by 20 native activations")
    if not np.isfinite(x).all() or np.any((x < 0) | (x > 8)):
        raise ValueError("Native activation domain is [0,8]")
    if q.shape != (len(x), 3) or not np.isfinite(q).all() or np.any(q[:, 2] != 0):
        raise ValueError("Teacher is finite N by 3 physical Q with literal zero STOP")
    return np.column_stack((x, np.ones(len(x)))), q


def actions(scores):
    """Registered diagnostic tie rule: STOP, then repair, then keep."""
    scores = np.asarray(scores)
    if scores.ndim != 2 or scores.shape[1] != 3 or not np.isfinite(scores).all():
        raise ValueError("Expected finite N by 3 action scores")
    return 2 - np.argmax(scores[:, ::-1], axis=1)


def loss_and_grad(activation, teacher, weights, objective, penalty=1e-4):
    """Q-MSE or CE plus normalized expected regret, with the same L2 term.

    MSE fits physical teacher Q/8 for keep/repair. Policy CE uses affine logits
    at temperature one, with physical-Q gaps normalized per row by 1+max gap.
    The common penalty is penalty*mean(nonbias_coefficients**2).
    """
    if objective not in OBJECTIVES or not np.isfinite(penalty) or penalty < 0:
        raise ValueError("Invalid objective or regularization")
    weights = _parameters(weights)
    design, q = _data(activation, teacher)
    scores = np.column_stack((design @ weights, np.zeros(len(design))))
    labels = actions(q)
    if objective == "q_mse":
        difference = scores[:, :2] - q[:, :2] / 8
        data_loss = float(np.mean(difference**2))
        derivative = difference / len(design)
        metrics = {"q_mse": data_loss}
    else:
        shifted = scores - scores.max(axis=1, keepdims=True)
        exponent = np.exp(shifted)
        normalizer = exponent.sum(axis=1, keepdims=True)
        probability = exponent / normalizer
        gaps = q.max(axis=1, keepdims=True) - q
        if not np.isfinite(gaps).all():
            raise ValueError("Teacher regret overflow")
        regret = gaps / (1 + gaps.max(axis=1, keepdims=True))
        expected = np.sum(probability * regret, axis=1)
        ce = np.log(normalizer[:, 0]) - shifted[np.arange(len(design)), labels]
        data_loss = float(np.mean(ce + expected))
        gradient = probability - np.eye(3)[labels]
        gradient += probability * (regret - expected[:, None])
        derivative = gradient[:, :2] / len(design)
        metrics = {
            "cross_entropy": float(ce.mean()),
            "normalized_expected_regret": float(expected.mean()),
        }
    regularization = float(penalty * np.mean(weights[:-1] ** 2))
    gradient = design.T @ derivative
    gradient[:-1] += 2 * penalty * weights[:-1] / weights[:-1].size
    loss = data_loss + regularization
    if not np.isfinite(loss) or not np.isfinite(gradient).all():
        raise ValueError("Nonfinite loss or gradient")
    metrics.update(
        data_loss=data_loss,
        regularization=regularization,
        teacher_action_accuracy=float(np.mean(actions(scores) == labels)),
    )
    return loss, gradient, metrics


def fit(activation, teacher, objective, *, learning_rate, epochs=120, penalty=1e-4):
    """Full-batch Adam from exact zero; both objectives use identical mechanics."""
    if (
        not np.isfinite(learning_rate)
        or learning_rate <= 0
        or isinstance(epochs, bool)
        or not isinstance(epochs, int)
        or epochs < 1
    ):
        raise ValueError("Invalid fixed optimizer schedule")
    design, q = _data(activation, teacher)
    x = design[:, :WIDTH]
    weights = np.zeros((WIDTH + 1, 2))
    first, second = np.zeros_like(weights), np.zeros_like(weights)
    seen = np.zeros(weights.shape, dtype=bool)
    losses, clipped_steps, projections = [], 0, 0
    started, cpu_started = time.perf_counter(), time.process_time()
    initial_loss, _, initial_metrics = loss_and_grad(x, q, weights, objective, penalty)
    for step in range(1, epochs + 1):
        loss, gradient, _ = loss_and_grad(x, q, weights, objective, penalty)
        losses.append(loss)
        seen |= gradient != 0
        factor = min(1.0, 5.0 / max(float(np.linalg.norm(gradient)), 1e-30))
        clipped_steps += int(factor < 1)
        gradient *= factor
        first = 0.9 * first + 0.1 * gradient
        second = 0.999 * second + 0.001 * gradient**2
        update = (
            learning_rate
            * (first / (1 - 0.9**step))
            / (np.sqrt(second / (1 - 0.999**step)) + 1e-8)
        )
        raw = weights - update
        weights = np.clip(raw, -BOUND, BOUND)
        projections += int(np.count_nonzero(raw != weights))
    final_loss, _, final_metrics = loss_and_grad(x, q, weights, objective, penalty)
    receipt = {
        "schema": "hepta.native-readout-objective.fit.v1",
        "objective": objective,
        "optimizer": "full-batch Adam",
        "epochs": epochs,
        "gradient_evaluations": epochs + 2,
        "learning_rate": learning_rate,
        "adam_beta1": 0.9,
        "adam_beta2": 0.999,
        "adam_epsilon": 1e-8,
        "gradient_norm_bound": 5.0,
        "gradient_clipped_steps": clipped_steps,
        "coefficient_bound": BOUND,
        "projected_coordinate_updates": projections,
        "regularization": penalty,
        "regularization_scope": "mean of 40 nonbias coefficients squared",
        "q_mse_teacher_scale": 8.0,
        "policy_temperature": 1.0,
        "initialization": "exact zero, 42 coefficients",
        "trainable_scalars": weights.size,
        "training_rows": len(x),
        "coordinates_with_nonzero_gradient": int(seen.sum()),
        "initial_loss": initial_loss,
        "initial_metrics": initial_metrics,
        "epoch_loss": losses,
        "final_loss": final_loss,
        "final_metrics": final_metrics,
        "coefficient_change_l2": float(np.linalg.norm(weights)),
        "activation_sha256": hashlib.sha256(
            np.asarray(x, dtype="<f8").tobytes()
        ).hexdigest(),
        "physical_teacher_sha256": hashlib.sha256(
            np.asarray(q, dtype="<f8").tobytes()
        ).hexdigest(),
        "python_cpu_seconds": time.process_time() - cpu_started,
        "wall_seconds": time.perf_counter() - started,
        "native_kernel_executed": False,
        "native_ndu_executed": False,
        "split_membership_verified": False,
    }
    return weights, receipt


def q24_scores(activation_q24, weights):
    """Exact bounded model.rs head arithmetic; this does not execute the NDU.

    Inputs must be actual integer activations. Profile coefficients are produced
    by Python round(float*2**24), matching make_profile. Each signed product is
    rounded to nearest, ties-even in integer arithmetic before the sum.
    """
    activation = np.asarray(activation_q24)
    if (
        activation.ndim != 2
        or activation.shape[1] != WIDTH
        or not np.issubdtype(activation.dtype, np.integer)
        or np.any(activation < 0)
        or np.any(activation > 8 * Q)
    ):
        raise ValueError("Expected bounded integer N by 20 native activations")
    weights = _parameters(weights)
    coefficients = [[round(float(value) * Q) for value in row] for row in weights]
    result = np.zeros((len(activation), 3), dtype=np.int64)
    for i, row in enumerate(activation):
        for action in range(2):
            total = coefficients[-1][action]
            for value, coefficient in zip(row, coefficients[:-1]):
                product = int(value) * coefficient[action]
                quotient, remainder = divmod(abs(product), Q)
                rounded = quotient + int(
                    2 * remainder > Q or (2 * remainder == Q and quotient % 2 != 0)
                )
                total += rounded if product >= 0 else -rounded
            result[i, action] = total
    return result
