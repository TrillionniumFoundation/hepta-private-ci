"""First-order, fresh-state SmallHCSN linearization and a shared-coordinate solve.

The caller supplies a pinned real model and its native-profile state fingerprint.
Targets enter only the quadratic training problem. No second-order autograd,
incoming-state detachment, parameter update loop, or adoption authority is used.
"""

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np
import torch

MAX_COORDINATES = 32
MAX_OUTPUTS = 16


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _array_digest(value):
    value = np.ascontiguousarray(value, dtype="<f8")
    return hashlib.sha256(str((value.dtype.str, value.shape)).encode() + value.tobytes()).hexdigest()


@dataclass(frozen=True)
class Coordinate:
    name: str
    flat_index: int
    scale: float = 1.0

    def record(self):
        return {"name": self.name, "flat_index": self.flat_index, "scale": float(self.scale)}


@dataclass(frozen=True)
class Linearization:
    coordinates: tuple
    base_output: np.ndarray
    jacobian: np.ndarray
    metadata: dict


def _layout(model, coordinates):
    coordinates = tuple(coordinates)
    _require(1 <= len(coordinates) <= MAX_COORDINATES, "bounded nonempty shared coordinates required")
    parameters = dict(model.named_parameters())
    seen, selected, layout = set(), {}, []
    for c in coordinates:
        _require(isinstance(c, Coordinate) and c.name in parameters, "registered named parameter required")
        p = parameters[c.name]
        _require(type(c.flat_index) is int and 0 <= c.flat_index < p.numel(), "coordinate index outside parameter")
        _require(type(c.scale) in (int, float) and math.isfinite(c.scale) and c.scale > 0,
                 "positive finite coordinate scale required")
        _require((c.name, c.flat_index) not in seen, "duplicate shared coordinate")
        _require(p.requires_grad and p.dtype == torch.float64 and p.device.type == "cpu",
                 "first version requires trainable CPU FP64 coordinates")
        seen.add((c.name, c.flat_index))
        selected[c.name] = p
        layout.append({**c.record(), "shape": list(p.shape), "dtype": str(p.dtype)})
    return coordinates, selected, layout


def _inputs(model, x, initial_margin):
    reference = model.input_drive.weight
    _require(reference.dtype == torch.float64 and reference.device.type == "cpu", "CPU FP64 physical model required")
    x = torch.as_tensor(x, dtype=reference.dtype, device=reference.device)
    margin = torch.as_tensor(initial_margin, dtype=reference.dtype, device=reference.device)
    _require(x.ndim == 3 and 1 <= x.shape[0] <= 64 and 1 <= x.shape[1] <= MAX_OUTPUTS
             and x.shape[2] == model.config.input_size, "bounded configuration-matching input required")
    _require(not x.requires_grad and not margin.requires_grad, "observed inputs must be independent of parameters")
    if margin.ndim == 1:
        margin = margin[:, None]
    _require(margin.ndim == 2 and margin.shape[0] == x.shape[1]
             and margin.shape[1] in (1, model.config.neurons), "one broadcastable margin row per trajectory required")
    _require(bool(torch.isfinite(x).all() and torch.isfinite(margin).all()), "finite observations required")
    return x, margin


def _fresh_output(model, x, margin):
    # Rebuild the complete initial state on EVERY AD and FD call. Do not accept a
    # saved incoming state whose dependence on parameters would need a tangent.
    state = model.initial_state(x.shape[1], margin)
    logits, _, _ = model(x, state=state, return_features=True)
    output = logits[-1, :, 1] - logits[-1, :, 0]
    _require(bool(torch.isfinite(output).all()), "nonfinite physical output")
    return output


def linearize_fresh(model, x, initial_margin, coordinates, *, state_fingerprint):
    """Return d(final logit margin)/d(alpha), theta[c]=theta0[c]+scale[c]*alpha[c]."""
    coordinates, selected, layout = _layout(model, coordinates)
    x, margin = _inputs(model, x, initial_margin)
    before = state_fingerprint(model.state_dict())
    with torch.enable_grad():
        output = _fresh_output(model, x, margin)
        jacobian = np.zeros((len(output), len(coordinates)), dtype=np.float64)
        if output.requires_grad:
            for row in range(len(output)):
                gradients = torch.autograd.grad(output[row], tuple(selected.values()),
                    retain_graph=row + 1 < len(output), create_graph=False, allow_unused=True)
                by_name = dict(zip(selected, gradients))
                for column, c in enumerate(coordinates):
                    gradient = by_name[c.name]
                    if gradient is not None:
                        jacobian[row, column] = float(gradient.reshape(-1)[c.flat_index]) * c.scale
    _require(state_fingerprint(model.state_dict()) == before, "linearization changed model tensors")
    _require(bool(np.isfinite(jacobian).all()), "nonfinite first-order sensitivity")
    base = output.detach().cpu().numpy().copy()
    metadata = {
        "schema": "hepta.smallhcsn.first-order-linearization.v1",
        "parent_state_sha256": before, "coordinate_layout": layout,
        "coordinate_sha256": _digest(layout), "shared_coordinate_count": len(coordinates),
        "model_parameter_count": sum(p.numel() for p in model.parameters()),
        "trainable_model_parameter_count": sum(p.numel() for p in model.parameters() if p.requires_grad),
        "observation_count": len(base), "input_sha256": _array_digest(x.numpy()),
        "initial_margin_sha256": _array_digest(margin.numpy()),
        "base_output_sha256": _array_digest(base), "jacobian_sha256": _array_digest(jacobian),
        "objective_state": "fresh complete trajectory; initial_state rebuilt inside each forward",
        "output": "final class-1 minus class-0 logit; no target in forward",
        "derivative": "scalar first-order VJP; create_graph=False; model knot conventions retained",
        "second_order_autograd": False,
    }
    metadata["linearization_sha256"] = _digest(metadata)
    base.setflags(write=False)
    jacobian.setflags(write=False)
    return Linearization(coordinates, base, jacobian, metadata)


def weighted_system(linearization, targets, observation_weights=None):
    """Return A=sqrt(W)J and b=sqrt(W)(target-base), without any ridge term."""
    j = np.asarray(linearization.jacobian, dtype=np.float64)
    base = np.asarray(linearization.base_output, dtype=np.float64)
    _require(base.ndim == 1 and 1 <= len(base) <= MAX_OUTPUTS and j.ndim == 2
             and j.shape[0] == len(base) and 1 <= j.shape[1] <= MAX_COORDINATES
             and len(linearization.coordinates) == j.shape[1], "bounded nonempty linearization dimensions required")
    _require(bool(np.isfinite(j).all() and np.isfinite(base).all()), "finite linearization required")
    target = np.asarray(targets, dtype=np.float64)
    weights = np.ones(len(base)) if observation_weights is None else np.asarray(observation_weights, dtype=np.float64)
    _require(target.shape == base.shape and weights.shape == base.shape, "one target and weight per observation required")
    _require(bool(np.isfinite(target).all() and np.isfinite(weights).all() and (weights > 0).all()),
             "finite targets and positive observation weights required")
    return np.sqrt(weights)[:, None] * j, np.sqrt(weights) * (target - base)


def solve_gauss_newton(linearization, targets, *, ridge, observation_weights=None):
    """Solve 1/2 sum_i w_i (J alpha - (target-base))² + ridge/2 ||alpha||².

    Augmented SVD least squares avoids forming normal equations for the solve.
    Data rank is measured before regularization. A ridge-selected solution does
    not identify an otherwise unobserved coordinate.
    """
    _require(type(ridge) in (int, float) and math.isfinite(ridge) and ridge >= 0, "finite nonnegative ridge required")
    weighted, right = weighted_system(linearization, targets, observation_weights)
    observations, coordinate_count = weighted.shape
    singular = np.linalg.svd(weighted, compute_uv=False)
    tolerance = np.finfo(np.float64).eps * max(weighted.shape) * singular[0]
    rank = int(np.count_nonzero(singular > tolerance))
    operator = np.vstack((weighted, math.sqrt(ridge) * np.eye(coordinate_count))) if ridge else weighted
    rhs = np.concatenate((right, np.zeros(coordinate_count))) if ridge else right
    delta, _, solved_rank, _ = np.linalg.lstsq(operator, rhs, rcond=None)
    _require(bool(np.isfinite(delta).all()), "nonfinite Gauss-Newton solution")
    error = weighted @ delta - right
    stationarity = weighted.T @ error + ridge * delta
    return {
        "schema": "hepta.smallhcsn.shared-gauss-newton-step.v1",
        "linearization_sha256": linearization.metadata["linearization_sha256"],
        "parent_state_sha256": linearization.metadata["parent_state_sha256"],
        "coordinate_sha256": linearization.metadata["coordinate_sha256"],
        "delta": delta.tolist(), "delta_sha256": _array_digest(delta),
        "observation_count": observations, "shared_coordinate_count": coordinate_count,
        "data_rank": rank, "data_nullity": coordinate_count - rank,
        "data_full_column_rank": rank == coordinate_count, "singular_values": singular.tolist(),
        "rank_tolerance": float(tolerance),
        "nonzero_condition_number": float(singular[0] / singular[rank - 1]) if rank else None,
        "ridge": float(ridge), "ridge_is_data_identification": False,
        "regularized_problem_unique": bool(ridge > 0 or rank == coordinate_count),
        "solver_numerical_rank": int(solved_rank),
        "unregularized_rule": "minimum Euclidean norm in the declared alpha coordinates",
        "objective_at_zero": float(0.5 * (right @ right)),
        "linearized_data_objective": float(0.5 * (error @ error)),
        "regularized_objective": float(0.5 * (error @ error) + 0.5 * ridge * (delta @ delta)),
        "stationarity_max_abs": float(np.abs(stationarity).max()),
        "actual_nonlinear_improvement_measured": False,
    }


def apply_coordinate_step(model, coordinates, delta, *, expected_parent_state_sha256,
                          expected_coordinate_sha256, learning_receipt_sha256,
                          state_fingerprint, max_step_norm):
    """Construct tensors from a verified local OR aggregate receipt; never adopt.

    Receipt verification belongs to the caller. Its identity is preserved here,
    without inventing a local linearization identity for an aggregate update.
    """
    coordinates, _, layout = _layout(model, coordinates)
    _require(type(max_step_norm) in (int, float) and math.isfinite(max_step_norm) and max_step_norm > 0,
             "positive finite prespecified step bound required")
    _require(state_fingerprint(model.state_dict()) == expected_parent_state_sha256, "stale physical parent")
    _require(_digest(layout) == expected_coordinate_sha256, "shared coordinate layout changed")
    _require(isinstance(learning_receipt_sha256, str) and len(learning_receipt_sha256) == 64
             and learning_receipt_sha256 != "0" * 64
             and all(c in "0123456789abcdef" for c in learning_receipt_sha256), "learning receipt hash required")
    delta = np.asarray(delta, dtype=np.float64)
    _require(delta.shape == (len(coordinates),) and bool(np.isfinite(delta).all()), "invalid coordinate step")
    _require(float(np.linalg.norm(delta)) <= max_step_norm, "step exceeds prespecified radius; no clipping or refit")
    state = {name: value.detach().clone() for name, value in model.state_dict().items()}
    for c, value in zip(coordinates, delta):
        state[c.name][np.unravel_index(c.flat_index, state[c.name].shape)] += float(c.scale * value)
    _require(all(bool(torch.isfinite(value).all()) for value in state.values()), "nonfinite candidate tensor")
    return state, {
        "schema": "hepta.smallhcsn.coordinate-edit.v1",
        "parent_state_sha256": expected_parent_state_sha256,
        "candidate_state_sha256": state_fingerprint(state),
        "coordinate_sha256": expected_coordinate_sha256,
        "coordinates": [c.record() for c in coordinates],
        "learning_receipt_sha256": learning_receipt_sha256,
        "delta_sha256": _array_digest(delta), "max_step_norm": float(max_step_norm),
        "changed": state_fingerprint(state) != expected_parent_state_sha256,
        "actual_nonlinear_improvement_measured": False, "adopted": False,
    }


def candidate_state(model, linearization, step, *, state_fingerprint, max_step_norm):
    """Validate a central step identity, then use the common construction path."""
    _require(step["linearization_sha256"] == linearization.metadata["linearization_sha256"], "step belongs to another linearization")
    _require(step["parent_state_sha256"] == linearization.metadata["parent_state_sha256"]
             and step["coordinate_sha256"] == linearization.metadata["coordinate_sha256"], "step parent or coordinates changed")
    _require(_array_digest(step["delta"]) == step["delta_sha256"], "coordinate step changed")
    state, receipt = apply_coordinate_step(model, linearization.coordinates, step["delta"],
        expected_parent_state_sha256=linearization.metadata["parent_state_sha256"],
        expected_coordinate_sha256=linearization.metadata["coordinate_sha256"],
        learning_receipt_sha256=_digest(step), state_fingerprint=state_fingerprint,
        max_step_norm=max_step_norm)
    return state, {**receipt, "linearization_sha256": linearization.metadata["linearization_sha256"]}


def controlled_finite_difference(model, x, initial_margin, linearization, *, state_fingerprint,
                                 h=1e-5, atol=1e-7, rtol=3e-5):
    """Fixed two-scale engineering check; unresolved nonsmooth stencils fail.

    One-sided slope gaps must be small or shrink when the radius halves. This
    is a finite-stencil diagnostic, not a global smoothness proof. No tolerance
    adjustment, parameter selection, or optimization occurs after the check.
    """
    _require(all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (h, atol, rtol)), "positive fixed FD settings required")
    x, margin = _inputs(model, x, initial_margin)
    coordinates, parameters, _ = _layout(model, linearization.coordinates)
    before = state_fingerprint(model.state_dict())
    _require(before == linearization.metadata["parent_state_sha256"], "FD parent changed")
    rows = []
    with torch.no_grad():
        base = _fresh_output(model, x, margin).numpy().copy()
        _require(np.array_equal(base, linearization.base_output), "FD base prediction differs")
        for column, c in enumerate(coordinates):
            parameter = parameters[c.name]
            index = np.unravel_index(c.flat_index, parameter.shape)
            original = float(parameter[index])
            approximations, gaps = [], []
            try:
                for radius in (h, h / 2):
                    values = []
                    for sign in (1, -1):
                        parameter[index] = original + sign * radius * c.scale
                        values.append(_fresh_output(model, x, margin).numpy().copy())
                    approximations.append((values[0] - values[1]) / (2 * radius))
                    gaps.append(float(np.max(np.abs((values[0] - base) / radius - (base - values[1]) / radius))))
            finally:
                parameter[index] = original
            fine, analytic = approximations[1], linearization.jacobian[:, column]
            scale = max(float(np.abs(fine).max()), float(np.abs(analytic).max()))
            gap_floor = 4 * (atol + rtol * scale)
            resolved = gaps[1] <= gap_floor or gaps[1] <= 0.75 * gaps[0]
            stable = bool(np.all(np.abs(approximations[0] - fine) <= atol + rtol * np.maximum(np.abs(approximations[0]), np.abs(fine))))
            matched = bool(np.all(np.abs(analytic - fine) <= atol + rtol * np.maximum(np.abs(analytic), np.abs(fine))))
            rows.append({**c.record(), "h": h, "half_h": h / 2, "one_sided_gaps": gaps,
                         "stencil_resolved": bool(resolved), "gap_floor": gap_floor,
                         "central_scales_agree": stable,
                         "vjp_matches_fd": matched, "max_abs_error": float(np.abs(analytic - fine).max()),
                         "analytic_max_abs": float(np.abs(analytic).max()),
                         "status": "PASSED" if resolved and stable and matched else "INCONCLUSIVE_OR_FAILED"})
    _require(state_fingerprint(model.state_dict()) == before, "FD did not restore original parameters")
    return {"schema": "hepta.smallhcsn.controlled-fd-check.v1", "rows": rows,
            "atol": atol, "rtol": rtol, "physical_forward_calls": 1 + 4 * len(coordinates),
            "passed": all(row["status"] == "PASSED" for row in rows),
            "scope": "fixed fresh-state engineering derivative check; no training or model advantage claim"}
