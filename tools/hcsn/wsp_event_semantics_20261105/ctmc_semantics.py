"""Finite-CTMC numerical event reference, not a neural efficacy evaluator.

Stored generators are authoritative. A strict upper-threshold event is
tau_K = inf{t >= 0: u(X_t) > K}; initial event mass counts at t=0.
The state coordinates, finite spatial approximation and piecewise public drive
are retained. These are not continuum Brownian first-passage certificates.
"""
import math

import numpy as np
from scipy.linalg import expm
from scipy.special import gammainc


def validate_generator(generator, tolerance=2e-10):
    q = np.asarray(generator, dtype=np.float64)
    if q.ndim != 2 or q.shape[0] != q.shape[1] or not 1 <= len(q) <= 128:
        raise ValueError("bounded square generator required")
    if not np.isfinite(q).all():
        raise ValueError("finite generator required")
    off = q.copy()
    np.fill_diagonal(off, 0.)
    if off.min() < 0 or np.diag(q).max() > 0:
        raise ValueError("generator sign contract failed")
    error = float(np.max(np.abs(q.sum(axis=1))))
    if error > tolerance:
        raise ValueError("generator rows do not sum to zero")
    return q, error


def stopped_generator(generator, event_mask):
    """Absorb all event states; stopping cannot alter any pre-event rate."""
    q = np.array(generator, copy=True)
    event = np.asarray(event_mask, dtype=bool)
    if event.shape != (len(q),):
        raise ValueError("event mask shape mismatch")
    q[event, :] = 0.
    return q


def uniformized_transition_and_integral(generator, duration, tail_target=1e-15):
    """Independent positive-series numerical reference to Pade expm.

    P = sum_k Pr(Poisson(lambda*t)=k) R^k.
    L = int_0^t P(s) ds = sum_k Pr(Poisson(lambda*t)>k) R^k/lambda.
    Reported truncation bounds do not enclose floating-point arithmetic.
    """
    q, _ = validate_generator(generator)
    t = float(duration)
    if not np.isfinite(t) or t < 0 or t > 2:
        raise ValueError("duration outside declared [0,2] contract")
    n = len(q)
    eye = np.eye(n)
    rate = float(np.max(-np.diag(q)))
    if rate == 0 or t == 0:
        return eye, eye * t, dict(terms=1, poisson_tail=0., integral_tail_bound=0.)
    mu = rate * t
    if mu > 600:
        raise ValueError("uniformization budget exceeded, no adaptive method substitution")
    r = eye + q / rate
    if r.min() < 0:
        raise ArithmeticError("uniformization is not a nonnegative kernel")
    power = eye.copy()
    probability = math.exp(-mu)
    p = np.zeros_like(q)
    integral = np.zeros_like(q)
    for k in range(4096):
        tail = float(gammainc(k + 1, mu))
        p += probability * power
        integral += (tail / rate) * power
        if tail <= tail_target:
            return p, integral, dict(terms=k + 1, poisson_tail=tail,
                                     integral_tail_bound=t * tail)
        power = power @ r
        probability *= mu / (k + 1)
    raise ArithmeticError("uniformization term cap exceeded")


def transition_pair(generator, duration, tolerance):
    q, generator_error = validate_generator(generator, tolerance)
    a = expm(float(duration) * q)
    b, integral, info = uniformized_transition_and_integral(q, duration)
    disagreement = float(np.max(np.abs(a - b)))
    mass_error = float(np.max(np.abs(a.sum(axis=1) - 1.)))
    if disagreement > tolerance or mass_error > tolerance or float(a.min()) < -tolerance:
        raise ArithmeticError("independent transition reference failed")
    return a, b, integral, dict(generator_row_error=generator_error,
                                expm_vs_uniformization_max=disagreement,
                                probability_row_error=mass_error,
                                minimum_probability=float(a.min()), **info)


def reward_kernel(generator, entry_rates, reset_rates, duration, integral, tolerance):
    """Expected entry/reset jump counts via Van Loan block and series integral."""
    q = np.asarray(generator)
    rates = np.column_stack((entry_rates, reset_rates))
    if rates.shape != (len(q), 2) or not np.isfinite(rates).all() or rates.min() < 0:
        raise ValueError("nonnegative finite event rates required")
    augmented = np.zeros((len(q) + 2, len(q) + 2))
    augmented[:len(q), :len(q)] = q
    augmented[:len(q), len(q):] = rates
    direct = expm(float(duration) * augmented)[:len(q), len(q):]
    series = integral @ rates
    residual = float(np.max(np.abs(direct - series)))
    if residual > tolerance or direct.min() < -tolerance:
        raise ArithmeticError("independent jump-count integral failed")
    return direct, series, residual


def known_answer_checks(tolerance):
    """A resettable two-state chain distinguishes occupancy and first passage."""
    a, b, t = 1.2, .7, 1.5
    q = np.array([[-a, a], [b, -b]])
    ordinary, _, integral, audit = transition_pair(q, t, tolerance)
    killed, _, _, killed_audit = transition_pair(stopped_generator(q, [False, True]), t, tolerance)
    entry, reset = np.array([a, 0.]), np.array([0., b])
    rewards, _, reward_residual = reward_kernel(q, entry, reset, t, integral, tolerance)
    total = a + b
    decay = 1 - math.exp(-total * t)
    exact_endpoint = a / total * decay
    exact_first = 1 - math.exp(-a * t)
    exact_entries = a * (b / total * t + a / total ** 2 * decay)
    exact_resets = b * (a / total * t - a / total ** 2 * decay)
    errors = [abs(ordinary[0, 1] - exact_endpoint), abs(killed[0, 1] - exact_first),
              abs(rewards[0, 0] - exact_entries), abs(rewards[0, 1] - exact_resets)]
    if max(errors) > tolerance or not exact_first > exact_endpoint:
        raise ArithmeticError("closed-form reset-chain controls failed")
    identity, _, _, _ = transition_pair(q, 0., tolerance)
    if not np.array_equal(identity, np.eye(2)):
        raise ArithmeticError("zero-time identity failed")
    no_reset = stopped_generator(q, [False, True])
    nr, _, _, _ = transition_pair(no_reset, t, tolerance)
    if abs(nr[0, 1] - exact_first) > tolerance:
        raise ArithmeticError("no-reset endpoint/first-hit control failed")
    return dict(endpoint=exact_endpoint, first_hit=exact_first, expected_entries=exact_entries,
                expected_resets=exact_resets, max_closed_form_error=max(errors),
                reward_integral_disagreement=reward_residual,
                ordinary=audit, killed=killed_audit,
                scope="Numerical known-answer controls; no outward-rounded proof")
