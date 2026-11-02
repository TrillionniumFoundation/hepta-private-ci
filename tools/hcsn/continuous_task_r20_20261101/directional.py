"""One-sided directional LCPs; a direction is not a Jacobian column set."""

import numpy as np
from scipy.linalg import solve_banded


def apply(a, lower, upper, value):
    return a * value + np.r_[0., lower * value[:-1]] + np.r_[upper * value[1:], 0.]


def mixed_lcp(a, lower, upper, rhs, obstacle, states=None):
    """States:0forced equation,1forced contact,2complementarity/biactive.

    A must be a strictly row-diagonally-dominant tridiagonal M-matrix.
    The returned residual checks only the constraints applicable to each row.
    """
    a, lower, upper, rhs, obstacle = (np.asarray(v, dtype=float) for v in (a, lower, upper, rhs, obstacle))
    count = len(a)
    rowsum = a + np.r_[0., lower] + np.r_[upper, 0.]
    if (a.ndim != 1 or a.shape != rhs.shape or a.shape != obstacle.shape or lower.shape != (count - 1,)
            or upper.shape != lower.shape or not all(np.isfinite(v).all() for v in (a, lower, upper, rhs, obstacle))
            or np.min(rowsum) <= 0 or np.any(lower > 0) or np.any(upper > 0)):
        raise ValueError("Expected finite strictly dominant tridiagonal M-matrix")
    states = np.full(count, 2, dtype=np.int8) if states is None else np.asarray(states)
    if states.shape != a.shape or not np.isin(states, [0, 1, 2]).all():
        raise ValueError("Invalid directional row classification")
    active = states != 0
    for iteration in range(256):
        band = np.zeros((3, count))
        band[0, 1:], band[1], band[2, :-1] = upper, a, lower
        target = rhs.copy()
        indices = np.flatnonzero(active)
        band[1, indices] = 1.
        band[0, indices[indices < count - 1] + 1] = 0.
        band[2, indices[indices > 0] - 1] = 0.
        target[indices] = obstacle[indices]
        value = solve_banded((1, 1), band, target, check_finite=False)
        contact, equation = value - obstacle, apply(a, lower, upper, value) - rhs
        next_active = (states == 1) | ((states == 2) & (contact <= equation))
        if np.array_equal(next_active, active):
            residual = np.where(states == 0, equation, np.where(states == 1, contact, np.minimum(contact, equation)))
            return value, dict(residual=float(abs(residual).max()), iterations=iteration + 1,
                               biactive_rows=int(np.sum(states == 2)))
        active = next_active
    raise RuntimeError("Mixed directional LCP policy iteration did not converge")


def derivative(a, lower, upper, value, rhs, obstacle, drhs, dobstacle, dmatrix_value,
               exact_states=None):
    """Differentiate a primal LCP, or expose unresolved numerical ties.

    exact_states is a caller-supplied mathematical classification, not inferred
    from a tolerance. Without it, residual brackets certify strict rows in exact
    arithmetic; unresolved rows are treated as ties and explicitly counted.
    Floating residual diagnostics are not outward-rounded interval certificates.
    """
    contact, equation = value - obstacle, apply(a, lower, upper, value) - rhs
    residual = float(abs(np.minimum(contact, equation)).max())
    rowsum = a + np.r_[0., lower] + np.r_[upper, 0.]
    bound = residual / min(1., float(rowsum.min()))
    norm = float(np.max(a + np.r_[0., abs(lower)] + np.r_[abs(upper), 0.]))
    padding = 64 * np.finfo(float).eps * (1 + np.max(abs(value)) + np.max(abs(rhs)))
    states = np.where(contact > bound + padding, 0,
                      np.where(equation > norm * bound + padding, 1, 2)).astype(np.int8)
    unresolved = int(np.sum(states == 2))
    if exact_states is not None:
        states = np.asarray(exact_states)
    result, record = mixed_lcp(a, lower, upper, drhs - dmatrix_value, dobstacle, states)
    record.update(primal_residual=residual, real_arithmetic_primal_error_bound=bound,
                  unresolved_numerical_rows=unresolved if exact_states is None else 0,
                  exact_classification_supplied=exact_states is not None)
    return result, record


def max_direction(left, right, dleft, dright):
    """Hadamard directional derivative of max, using max of slopes at a tie."""
    return np.where(left > right, dleft, np.where(right > left, dright, np.maximum(dleft, dright)))
