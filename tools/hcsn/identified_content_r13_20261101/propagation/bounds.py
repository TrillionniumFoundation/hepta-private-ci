"""Explicit tail, finite-exponential, and action certificates with honest scope."""

import math

import numpy as np
from scipy.special import ndtr, ndtri
from scipy.stats import poisson


def upper_tail_bound(upper, total_time, sigma_max, drift_upper, initial_cap,
                     reset_cap=0.8, recovery_min=0.35):
    """Coupling bound for ever reaching upper, including all renewal excursions.

    Each new excursion starts below max(initial_cap, reset_cap). Recovery phase
    jumps are dominated by a Poisson process of rate 2/recovery_min. Union bound
    over their expected count is conservative and includes arbitrary initial
    recovery phases. The result concerns continuum paths, not FV spatial error.
    """
    if total_time < 0 or sigma_max <= 0 or recovery_min <= 0:
        raise ValueError("Invalid time, volatility, or recovery bound")
    if total_time == 0:
        return float(upper <= initial_cap)
    margin = upper-max(initial_cap, reset_cap)-max(drift_upper, 0)*total_time
    if margin <= 0:
        return 1.0
    one = 2*ndtr(-margin/(sigma_max*np.sqrt(total_time)))
    return float(min(1, (1+2*total_time/recovery_min)*one))


def choose_domain(total_time, sigma_max, drift_upper, initial_cap=0.8,
                  reset_cap=0.8, recovery_min=0.35, tail_budget=1e-4):
    if not 0 < tail_budget < 1:
        raise ValueError("Tail budget must lie in (0,1)")
    factor = 1+2*total_time/recovery_min
    z = -ndtri(tail_budget/(2*factor))
    upper = (max(initial_cap, reset_cap)+max(drift_upper, 0)*total_time
             +sigma_max*np.sqrt(total_time)*z)
    return {"upper": float(upper), "tail_bound": upper_tail_bound(upper, total_time,
        sigma_max, drift_upper, initial_cap, reset_cap, recovery_min),
        "total_time": total_time, "tail_budget": tail_budget,
        "scope": "Continuous upper-exit coupling only; not spatial discretization."}


def graded_edges(upper, near_step=0.025, fine_until=0.8, growth=1.2):
    if upper < fine_until or near_step <= 0 or growth < 1:
        raise ValueError("Invalid graded grid")
    count = int(math.ceil(fine_until/near_step))
    edges = np.linspace(0, fine_until, count+1).tolist()
    step = fine_until/count
    while edges[-1] < upper:
        step *= growth
        remaining = upper-edges[-1]
        # Merge a tiny final sliver, which otherwise makes rates unnecessarily stiff.
        if remaining < 1.5*step:
            edges.append(upper)
        else:
            edges.append(edges[-1]+step)
    return np.array(edges)


def uniformization_terms(q, dt, row_l1_budget=1e-12):
    """Truncation certificate for an unrenormalized positive Poisson series."""
    rate = float(max(-np.diag(q)))
    lam = rate*dt
    k = int(poisson.isf(row_l1_budget, lam)) if lam else 0
    while poisson.sf(k, lam) > row_l1_budget:
        k += 1
    return {"rate": rate, "terms": k+1, "omitted_row_mass": float(poisson.sf(k, lam)),
            "scope": "Series truncation only; floating-point error is separate."}


def action_certificate(qvalues, component_value_errors, tolerance=0.0):
    """Accept only complete certified error budgets; absent spatial bound rejects.

    Each component is a nonnegative uniform action-value error or None for an
    unresolved component. A grid-refinement difference is not such a certificate.
    """
    qvalues = np.asarray(qvalues, dtype=np.float64)
    finite = np.flatnonzero(np.isfinite(qvalues))
    best = int(finite[np.argmax(qvalues[finite])])
    others = finite[finite != best]
    gap = float(qvalues[best]-qvalues[others].max()) if len(others) else math.inf
    missing = [name for name, value in component_value_errors.items() if value is None]
    if any(value is not None and value < 0 for value in component_value_errors.values()):
        raise ValueError("Error bounds must be nonnegative")
    error = None if missing else sum(component_value_errors.values())
    certified = not missing and gap > 2*error+tolerance
    return {"action": best, "gap": gap, "value_error": error, "missing_bounds": missing,
        "action_certified": bool(certified),
        "regret_bound": None if error is None else 2*error+tolerance,
        "next_step": "accept" if certified else "refine_or_obtain_missing_bound; do_not_claim_certified_optimal_action"}


def finite_horizon_value_error(horizon, kernel_tv, reward_error, reward_bound,
                               terminal_bound=0.0, terminal_error=0.0):
    return (terminal_error+horizon*reward_error
            +(reward_bound*horizon*(horizon-1)+2*terminal_bound*horizon)*kernel_tv)
