"""Opt-in one-sided retention diagnostics and a bounded affine-tangent solver.

The published quadratic objective, Controller and run_nonlinear remain unchanged.
Squared positive-part loss is C1, piecewise quadratic, and not a global LQR.
No model, dataset, checkpoint, final-label reader or nonlinear runner is invoked.
"""

import math
import time

import numpy as np

from cell_field_control import solve_lq


PROFILE = "hepta.cell-retention.hinge-squared.v1"


class RetentionSolveError(RuntimeError):
    """An explicit failure, never a successful fallback to a different objective."""

    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


def _number(value, name, *, positive=False):
    if (isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, float, np.integer, np.floating))
            or not math.isfinite(float(value))
            or (float(value) <= 0 if positive else float(value) < 0)):
        raise ValueError(f"finite {'positive' if positive else 'nonnegative'} {name} required")
    return float(value)


def _array(value):
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError("real arrays required")
    return np.asarray(raw, dtype=np.float64)


def _scaled(values, factors):
    product = values * factors
    if (not np.isfinite(product).all()
            or np.any((values != 0) & (factors != 0) & (product == 0))):
        raise ValueError("nonfinite or underflowed weighted residual/Jacobian")
    return product


def _half_squared_norm(values):
    norm = math.hypot(*np.asarray(values).ravel())
    return (0.5 * norm) * norm


def retention_violation(old_losses, *, anchor, tolerance, weight=1.0):
    """Penalty and derivatives w.r.t. scalar old loss; anchor never drifts.

    At the threshold the derivative is zero and the second derivative does not
    exist. chosen_generalized_curvature=0 is one valid selection, not a Hessian.
    For a nonlinear L(theta), the active exact Hessian also contains
    weight * violation * Hessian(L); an affine-loss model omits that term.
    """
    anchor = _number(anchor, "frozen loss anchor")
    tolerance = _number(tolerance, "frozen loss tolerance")
    weight = _number(weight, "retention weight")
    losses = _array(old_losses)
    if not np.isfinite(losses).all():
        raise ValueError("finite old losses required")
    with np.errstate(over="ignore", invalid="ignore"):
        excess = losses - anchor - tolerance
        violation = np.maximum(excess, 0.0)
        penalty = 0.5 * np.square(math.sqrt(weight) * violation) if weight else np.zeros_like(violation)
        derivative = weight * violation
    if (not all(np.isfinite(v).all() for v in (excess, penalty, derivative))
            or (weight and np.any((violation > 0) & (penalty == 0)))):
        raise ValueError("nonfinite retention violation or penalty")
    return {"excess": excess, "violation": violation,
            "penalty": penalty, "derivative": derivative,
            "chosen_generalized_curvature": weight * (excess > 0),
            "at_threshold": excess == 0}


def retention_targets(reference_losses, current_target, *, anchor, tolerance):
    """Translate a frozen absolute old-loss bound to reference-relative fields.

    reference_losses is the original full (T+1, 2) current/old reference path.
    Build once from the registered anchor; suffix solves slice this same target.
    """
    anchor = _number(anchor, "frozen loss anchor")
    tolerance = _number(tolerance, "frozen loss tolerance")
    reference = _array(reference_losses)
    current = _array(current_target)
    if (reference.ndim != 2 or reference.shape[1] != 2 or len(reference) < 2
            or not np.isfinite(reference).all()):
        raise ValueError("finite current/old reference loss path required")
    if current.ndim == 0:
        current = np.full(len(reference), float(current))
    if current.shape != (len(reference),) or not np.isfinite(current).all():
        raise ValueError("one finite current displacement target per time required")
    with np.errstate(over="ignore", invalid="ignore"):
        target = np.column_stack((current, anchor + tolerance - reference[:, 1]))
    if not np.isfinite(target).all():
        raise ValueError("nonfinite translated retention target")
    return target


def _cost(fields, actions, target, dt, effort_price, old_weight):
    with np.errstate(over="ignore", invalid="ignore"):
        errors = fields - target
        weights = np.full(len(fields), dt)
        weights[-1] = 1.0
        old = np.maximum(errors[:, 1], 0.0)
        roots = np.sqrt(weights)
        current_cost = _half_squared_norm(_scaled(errors[:, 0], roots))
        old_cost = 0.0
        if old_weight:
            old_cost = _half_squared_norm(_scaled(old, roots * math.sqrt(old_weight)))
            if np.any(old > 0) and old_cost == 0:
                raise ValueError("unrepresentable nonzero retention penalty")
        effort = _half_squared_norm(math.sqrt(dt * effort_price) * actions)
    result = {"total": current_cost + old_cost + effort,
              "current_tracking": current_cost, "retention_violation": old_cost,
              "effort": effort}
    if not all(math.isfinite(x) for x in result.values()):
        raise ValueError("nonfinite retention objective")
    return result


def retention_cost(fields, actions, target, dt, effort_price, *, old_weight=1.0):
    """Evaluate this profile explicitly; never substitute for legacy cost silently."""
    fields, actions, target = (_array(v) for v in (fields, actions, target))
    dt = _number(dt, "dt", positive=True)
    effort_price = _number(effort_price, "effort price", positive=True)
    old_weight = _number(old_weight, "retention weight")
    _number(dt * effort_price, "control curvature", positive=True)
    if (fields.ndim != 2 or fields.shape[1] != 2 or len(fields) < 2
            or target.shape != fields.shape or actions.ndim != 2
            or actions.shape[0] + 1 != len(fields) or actions.shape[1] < 1 or dt > 1
            or not all(np.isfinite(v).all() for v in (fields, actions, target))):
        raise ValueError("compatible finite fields, target and action path required")
    return _cost(fields, actions, target, dt, effort_price, old_weight)


def _problem(A, E, C, target, initial, dt, effort_price, old_weight):
    A, E, C, target, initial = (_array(v) for v in (A, E, C, target, initial))
    dt = _number(dt, "dt", positive=True)
    effort_price = _number(effort_price, "effort price", positive=True)
    old_weight = _number(old_weight, "retention weight")
    _number(dt * effort_price, "control curvature", positive=True)
    if A.ndim != 3 or E.ndim != 3:
        raise ValueError("time-indexed transition and action matrices required")
    horizon, dim = A.shape[:2]
    if (not 1 <= horizon <= 64 or not 1 <= dim <= 512 or dt > 1
            or A.shape != (horizon, dim, dim) or E.shape[:2] != (horizon, dim)
            or not 1 <= E.shape[2] <= 128 or C.shape != (horizon + 1, 2, dim)
            or target.shape != (horizon + 1, 2) or initial.shape != (dim,)
            or horizon * (dim * dim + E.shape[2] ** 2) > 2_000_000
            or not all(np.isfinite(v).all() for v in (A, E, C, target, initial))):
        raise ValueError("bounded, compatible finite affine-tangent arrays required")
    return A, E, C, target, initial, dt, effort_price, old_weight


def _evaluate(problem, actions):
    A, E, C, target, initial, dt, effort_price, old_weight = problem
    horizon = len(A)
    states = np.empty((horizon + 1, len(initial)))
    states[0] = initial
    for k in range(horizon):
        states[k + 1] = A[k] @ states[k] + E[k] @ actions[k]
    fields = np.einsum("kij,kj->ki", C, states)
    errors = fields - target
    old = np.maximum(errors[:, 1], 0.0)
    weights = np.full(horizon + 1, dt)
    weights[-1] = 1.0
    roots = np.sqrt(weights)
    current_residual = _scaled(errors[:, 0], roots)
    state_gradient = _scaled(_scaled(C[:, 0], roots[:, None]), current_residual[:, None])
    if old_weight:
        old_roots = roots * math.sqrt(old_weight)
        old_residual = _scaled(old, old_roots)
        old_jacobian = np.where(old[:, None] > 0, C[:, 1], 0.0)
        state_gradient += _scaled(_scaled(old_jacobian, old_roots[:, None]), old_residual[:, None])
    gradient = np.empty_like(actions)
    adjoint = state_gradient[-1]
    for k in range(horizon - 1, -1, -1):
        gradient[k] = dt * effort_price * actions[k] + E[k].T @ adjoint
        adjoint = state_gradient[k] + A[k].T @ adjoint
    if not all(np.isfinite(v).all() for v in (states, fields, gradient)):
        raise ValueError("nonfinite tangent rollout or gradient")
    return {"states": states, "fields": fields, "gradient": gradient,
            "old_excess": errors[:, 1],
            "cost": _cost(fields, actions, target, dt, effort_price, old_weight)}


def _active_quadratic(C, target, active, dt, old_weight):
    """Conservative per-row admission for legacy Riccati's unscaled products.

    Cost/gradient diagnostics support some scales this quadratic solver rejects.
    A larger current term must not hide an erased active-old Gram contribution.
    """
    scaled_C, scaled_target = C.copy(), target.copy()
    factors = math.sqrt(old_weight) * active
    scaled_C[:, 1] = _scaled(C[:, 1], factors[:, None])
    scaled_target[:, 1] = _scaled(target[:, 1], factors)
    tiny = np.finfo(np.float64).tiny
    for k, beta in enumerate([dt] * (len(C) - 1) + [1.0]):
        for row in range(2):
            values = np.r_[scaled_C[k, row], scaled_target[k, row]]
            nonzero = values != 0
            squared = np.square(values)
            weighted = beta * squared
            diagonal = (beta * scaled_C[k, row]) * scaled_C[k, row]
            linear = (beta * scaled_C[k, row]) * scaled_target[k, row]
            linear_nonzero = (scaled_C[k, row] != 0) & (scaled_target[k, row] != 0)
            if (not all(np.isfinite(v).all() for v in (squared, weighted, diagonal, linear))
                    or np.any(nonzero & ((squared < tiny) | (weighted < tiny)))
                    or np.any((scaled_C[k, row] != 0) & (diagonal < tiny))
                    or np.any(linear_nonzero & (np.abs(linear) < tiny))):
                raise ValueError("unsupported active quadratic scale")
    return scaled_C, scaled_target


def retention_tangent_evaluate(A, E, C, target, initial, actions, dt, effort_price,
                               *, old_weight=1.0):
    """Explicit affine rollout and exact control-sequence gradient for diagnostics."""
    problem = _problem(A, E, C, target, initial, dt, effort_price, old_weight)
    actions = _array(actions)
    if actions.shape != (len(problem[0]), problem[1].shape[2]) or not np.isfinite(actions).all():
        raise ValueError("compatible finite action path required")
    return _evaluate(problem, actions)


def solve_retention_tangent(A, E, C, target, dt, effort_price, *, initial,
                            old_weight=1.0, max_iterations=64, gradient_tolerance=1e-9):
    """Solve the unconstrained deterministic piecewise-quadratic tangent problem.

    Each active piece is solved by the existing Riccati implementation; the
    resulting Newton direction is accepted against the TRUE hinge objective.
    Returned actions meet the declared numerical gradient tolerance for the
    supplied initial tangent state; a floating-point error bound is reported.
    No globally affine K, nonlinear policy, hard retention guarantee or task
    benefit is claimed. E already contains the physical action's dt, if any.
    """
    problem = _problem(A, E, C, target, initial, dt, effort_price, old_weight)
    A, E, C, target, initial, dt, effort_price, old_weight = problem
    gradient_tolerance = _number(gradient_tolerance, "gradient tolerance", positive=True)
    if (type(max_iterations) is not int or not 1 <= max_iterations <= 128
            or not 1e-14 <= gradient_tolerance <= 1e-4):
        raise ValueError("bounded iteration and residual settings required")
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    horizon, act = len(A), E.shape[2]
    actions = np.zeros((horizon, act))
    trace, solves, trials = [], 0, 0
    receipt = {"profile": PROFILE, "scope": "fixed unconstrained affine tangent only",
               "global_affine_feedback": False, "hard_retention_constraint": False,
               "gradient_tolerance": gradient_tolerance}

    def finish(**status):
        receipt.update(status, riccati_solve_attempts=solves, line_search_evaluations=trials,
                       wall_ns=time.perf_counter_ns() - started,
                       cpu_ns=time.process_time_ns() - cpu_started, trace=trace)
        return receipt

    for iteration in range(max_iterations + 1):
        receipt["iterations"] = iteration
        try:
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                result = _evaluate(problem, actions)
        except ValueError as error:
            raise RetentionSolveError("nonfinite current iterate", finish(
                converged=False, reason="nonfinite current iterate", failure_stage="rollout")) from error
        gradient = result["gradient"]
        residual = float(np.max(np.abs(gradient)))
        active = result["old_excess"] > 0
        trace.append({"iteration": iteration, "cost": result["cost"]["total"],
                      "gradient_inf": residual, "active_old_times": int(active.sum())})
        receipt["gradient_inf"] = residual
        try:
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                scaled_C, scaled_target = _active_quadratic(C, target, active, dt, old_weight)
        except ValueError as error:
            raise RetentionSolveError("unsupported active quadratic scale", finish(
                converged=False, reason="unsupported active quadratic scale",
                failure_stage="quadratic_scale")) from error
        if residual <= gradient_tolerance:
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                bound = _half_squared_norm(gradient / math.sqrt(dt * effort_price))
            if residual > 0 and bound == 0:
                bound = float(np.nextafter(0.0, 1.0))
            if not math.isfinite(bound):
                raise RetentionSolveError("nonfinite optimality bound", finish(
                    converged=False, reason="nonfinite optimality bound", failure_stage="certificate"))
            return {"actions": actions, **result, "active_old_times": active, "receipt": finish(
                converged=True, control_strong_convexity=dt * effort_price,
                numerical_suboptimality_bound=bound,
                certificate_arithmetic="floating point, not interval verification")}
        if iteration == max_iterations:
            break
        solves += 1
        try:
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                piece = solve_lq(A, E, scaled_C, scaled_target, dt, effort_price)
        except (np.linalg.LinAlgError, ValueError) as error:
            raise RetentionSolveError("active-piece linear solve failed", finish(
                converged=False, reason="active-piece linear solve failed", failure_stage="riccati")) from error
        candidate, state = np.empty_like(actions), initial.copy()
        with np.errstate(over="ignore", invalid="ignore"):
            for k in range(horizon):
                candidate[k] = -piece["K"][k] @ state + piece["offset"][k]
                state = A[k] @ state + E[k] @ candidate[k]
            direction = candidate - actions
            slope = float(np.sum(gradient * direction))
        if not np.isfinite(direction).all() or not math.isfinite(slope) or slope >= 0:
            raise RetentionSolveError("no finite descent direction", finish(
                converged=False, reason="no finite descent direction", failure_stage="newton_direction"))
        alpha, accepted = 1.0, False
        for _ in range(40):
            trials += 1
            try:
                with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                    trial = actions + alpha * direction
                    trial_cost = _evaluate(problem, trial)["cost"]["total"]
            except ValueError:
                alpha *= 0.5
                continue
            if trial_cost <= result["cost"]["total"] + 1e-4 * alpha * slope:
                actions, accepted = trial, True
                break
            alpha *= 0.5
        if not accepted:
            raise RetentionSolveError("true-objective line search exhausted", finish(
                converged=False, reason="true-objective line search exhausted", failure_stage="line_search"))
    raise RetentionSolveError("iteration budget exhausted", finish(
        converged=False, reason="iteration budget exhausted", failure_stage="iteration_budget"))
