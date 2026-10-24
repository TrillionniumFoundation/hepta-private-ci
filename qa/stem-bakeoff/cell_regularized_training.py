"""Bounded regularized head paths with tuning-only checkpoint selection.

The common parameter ceiling is a cap, not a matched compute allocation.
Costs include discarded updates and checkpoint selection work.
"""

import time

import numpy as np

from cell_calibration_v2 import prior_corrected_logits, smoothed_prior, weighted_nll
from cell_learning_models import NumpyCellHead, normalize_features


def matmul_flops(width, classes, rank, mode, rows, backward=False):
    """Executed dense matrix products, two scalar FLOPs per multiply-add."""
    base = (6 if backward else 2) * rows * width * classes
    return int(base + ((10 if backward else 4) * rows * width * rank if mode == "residual" else 0))


def fit_path(features, labels, tuning_features, tuning_labels, tuning_weights, *,
             mode, seed, l2, checkpoints=(10, 40, 100), rank=4,
             max_parameters=100000, learning_rate=0.02, min_delta=0.0001):
    """Return the best tuning checkpoint, stopping at the first plateau.

    Selection uses group-weighted NLL after analytic balanced-train to tuning
    prior correction. The later calibration fit receives a disjoint cohort.
    """
    if (not isinstance(checkpoints, (tuple, list)) or not checkpoints
            or tuple(sorted(set(checkpoints))) != tuple(checkpoints)
            or any(type(n) is not int or not 1 <= n <= 100 for n in checkpoints)
            or type(l2) not in (int, float) or not np.isfinite(l2) or not 0 < l2 <= 1
            or not 0 < learning_rate <= .1 or not 0 <= min_delta <= .01):
        raise ValueError("invalid bounded path configuration")
    x, tx = normalize_features(features), normalize_features(tuning_features)
    y, ty = np.asarray(labels), np.asarray(tuning_labels)
    if (y.dtype.kind not in "iu" or y.shape != (len(x),)
            or set(np.unique(y)) != {0, 1} or tx.shape[1] != x.shape[1]):
        raise ValueError("binary training labels with both classes and matching features required")
    target_prior = smoothed_prior(ty, tuning_weights)
    head = NumpyCellHead(x.shape[1], 2, mode, rank, seed, max_parameters - 4)
    start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
    before = head.digest()
    first = second = None
    m = {name: np.zeros_like(value) for name, value in head.params.items()}
    v = {name: np.zeros_like(value) for name, value in head.params.items()}
    best_params, best_loss, best_step, history = None, float("inf"), None, []
    initial_loss = None
    for step in range(1, max(checkpoints) + 1):
        loss, gradient = head.loss_gradients(x, y, l2)
        if initial_loss is None:
            initial_loss = loss
        norm = np.sqrt(sum(float(np.square(g).sum()) for g in gradient.values()))
        if not np.isfinite(loss) or not np.isfinite(norm):
            raise ValueError("nonfinite training state")
        clip = min(1.0, 5 / max(norm, 1e-12))
        for name in head.params:
            g = gradient[name] * clip
            m[name] = .9 * m[name] + .1 * g
            v[name] = .999 * v[name] + .001 * g*g
            first, second = m[name]/(1-.9**step), v[name]/(1-.999**step)
            head.params[name] -= learning_rate * first / (np.sqrt(second) + 1e-8)
        if step in checkpoints:
            logits, _ = head._forward(tx)
            score = weighted_nll(prior_corrected_logits(logits, [.5, .5], target_prior),
                                 ty, tuning_weights)
            improvement = score < best_loss - min_delta
            history.append({"step": step, "tuning_nll": score, "improved": improvement,
                            "tensor_sha256": head.digest()})
            if improvement:
                best_params = {name: value.copy() for name, value in head.params.items()}
                best_loss, best_step = score, step
            else:
                break
    last_digest = head.digest()
    head.params = best_params
    final_logits, _ = head._forward(x)
    train_weight = 1/np.bincount(y, minlength=2)[y]
    final_loss = weighted_nll(final_logits, y, train_weight)
    final_loss += .5*l2*sum(float(np.square(value).sum()) for name, value in head.params.items()
                             if name not in ("b", "g"))
    dense_flops = (step * matmul_flops(head.width, 2, rank, mode, len(x), True)
                   + len(history) * matmul_flops(head.width, 2, rank, mode, len(tx))
                   + matmul_flops(head.width, 2, rank, mode, len(x)))
    elementwise_estimate = step * (40*head.parameter_count + 20*len(x)*2
        + (28*len(x)*head.width if mode != "linear" else 0)
        + (6*len(x)*rank if mode == "residual" else 0))
    head.report = {"optimizer": "adam", "initial_loss": initial_loss, "final_loss": final_loss,
        "optimizer_steps": step, "maximum_steps": max(checkpoints),
        "selected_checkpoint_step": best_step, "discarded_updates_after_selected": step-best_step,
        "checkpoint_history": history, "early_stopped": step < max(checkpoints),
        "stop_rule": f"first checkpoint without tuning NLL improvement of at least {min_delta}",
        "early_stop_min_delta": min_delta,
        "selection_score": best_loss, "selection_metric": "group_weighted_prior_corrected_tuning_nll",
        "training_rows": len(y), "example_updates": step*len(y),
        "tuning_rows": len(ty), "tuning_group_mass": float(np.sum(tuning_weights)),
        "tuning_prior": target_prior.tolist(), "learning_rate": learning_rate, "l2": l2,
        "class_reweighting": "inverse_training_frequency", "effective_training_prior": [.5, .5],
        "trainable_parameters": head.parameter_count, "common_private_parameter_ceiling": max_parameters,
        "calibration_stored_scalars_reserved": 4, "parameter_bytes": head.tensor_bytes,
        "optimizer_state_bytes": 2*head.tensor_bytes, "gradient_bytes": head.tensor_bytes,
        "checkpoint_buffer_bytes": head.tensor_bytes,
        "normalized_input_bytes": x.nbytes + tx.nbytes,
        "persistent_tensor_bytes_accounted": 5*head.tensor_bytes+x.nbytes+tx.nbytes,
        "transient_array_peak_and_process_rss_measured": False,
        "executed_dense_matmul_flops": dense_flops,
        "estimated_elementwise_flops": int(elementwise_estimate),
        "flop_scope": "matrix products counted from executed shapes; elementwise arithmetic estimated; transcendentals excluded",
        "wall_ns": time.perf_counter_ns()-start, "cpu_ns": time.process_time_ns()-cpu_start,
        "initial_tensor_sha256": before, "last_update_tensor_sha256": last_digest,
        "trained_tensor_sha256": head.digest(), "encoder_updates": 0,
        "calibration_or_holdout_labels_in_gradients": False,
        "equal_steps_or_parameter_caps_claim_equal_cost": False}
    return head, dict(head.report)
