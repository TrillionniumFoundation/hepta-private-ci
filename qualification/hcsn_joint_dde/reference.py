"""Independent serial phase-type finite-horizon reference for delay renewal.

No DDE dense interpolation or refractory histogram is used. Each nth hit is
the absorption probability of n serial killed CTMC excursions, evaluated at
T-(n-1)*delay. Upper exits are absorbing and produce no subsequent events.
This is a reference for the declared finite spatial CTMC, not a continuum
or differentiable HCSN replacement.
"""

import math

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import expm_multiply


def _validated(transient, lower_rates, upper_rates, initial, reset):
    transient = np.asarray(transient, dtype=np.float64)
    n = transient.shape[0]
    if transient.shape != (n, n):
        raise ValueError("square transient generator required")
    vectors = [
        np.asarray(v, dtype=np.float64)
        for v in (lower_rates, upper_rates, initial, reset)
    ]
    if any(v.shape != (n,) or not np.isfinite(v).all() for v in vectors):
        raise ValueError("finite matching vectors required")
    if not np.isfinite(transient).all():
        raise ValueError("finite transient generator required")
    lower_rates, upper_rates, initial, reset = vectors
    if (
        min(np.min(lower_rates), np.min(upper_rates), np.min(initial), np.min(reset))
        < 0
    ):
        raise ValueError("nonnegative rates and laws required")
    if abs(initial.sum() - 1) > 1e-13 or abs(reset.sum() - 1) > 1e-13:
        raise ValueError("normalized entirely interior initial/reset laws required")
    if np.max(abs(transient.sum(axis=1) + lower_rates + upper_rates)) > 1e-10:
        raise ValueError("exit rates disagree with transient generator")
    offdiag = transient.copy()
    np.fill_diagonal(offdiag, 0)
    if offdiag.min() < 0:
        raise ValueError("transient off-diagonal rates must be nonnegative")
    return transient, lower_rates, upper_rates, initial, reset


def nth_hit_transform(
    transient,
    lower_rates,
    upper_rates,
    initial,
    reset,
    *,
    count,
    active_deadline,
    discount,
):
    """E[exp(-q*S_count) 1(S_count<=deadline)] before adding fixed delays.

    S_count is the sum of active excursion times. At each lower exit, the
    next CTMC starts at `reset`; an upper exit permanently ends all hits.
    """
    transient, lower_rates, upper_rates, initial, reset = _validated(
        transient, lower_rates, upper_rates, initial, reset
    )
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError("count must be an integer in [1,32]")
    if (
        not math.isfinite(active_deadline)
        or not math.isfinite(discount)
        or discount < 0
    ):
        raise ValueError("finite deadline and nonnegative discount required")
    if active_deadline <= 0:
        return 0.0
    n = transient.shape[0]
    size = n * count
    if size > 4096:
        raise ValueError("reference state budget exceeded")
    # Two accumulator coordinates: final lower hit and permanent upper exit.
    generator = lil_matrix((size + 2, size + 2), dtype=np.float64)
    hit, escape = size, size + 1
    for block in range(count):
        start, end = block * n, (block + 1) * n
        generator[start:end, start:end] = transient - discount * np.eye(n)
        generator[start:end, escape] = upper_rates[:, None]
        if block + 1 < count:
            generator[start:end, end : end + n] = np.outer(lower_rates, reset)
        else:
            generator[start:end, hit] = lower_rates[:, None]
    law = np.zeros(size + 2)
    law[:n] = initial
    evolved = expm_multiply(generator.tocsr().T * active_deadline, law)
    result = float(evolved[hit])
    if not math.isfinite(result) or result < -1e-12 or result > 1 + 1e-12:
        raise ArithmeticError("unresolved phase-type absorption")
    return result


def renewal_events(
    transient, lower_rates, upper_rates, initial, reset, *, horizon, delay, discount
):
    """Expected repeated-event count M and discounted count H, initial active."""
    if (
        not math.isfinite(horizon)
        or horizon < 0
        or not math.isfinite(delay)
        or delay <= 0
    ):
        raise ValueError(
            "nonnegative horizon and positive deterministic delay required"
        )
    rows = []
    # The final potential term has zero active time when T is an exact multiple.
    for count in range(1, math.floor(horizon / delay) + 2):
        active_time = horizon - (count - 1) * delay
        if active_time <= 0:
            break
        cdf = nth_hit_transform(
            transient,
            lower_rates,
            upper_rates,
            initial,
            reset,
            count=count,
            active_deadline=active_time,
            discount=0.0,
        )
        active_discounted = nth_hit_transform(
            transient,
            lower_rates,
            upper_rates,
            initial,
            reset,
            count=count,
            active_deadline=active_time,
            discount=discount,
        )
        rows.append(
            {
                "count": count,
                "active_deadline": active_time,
                "probability": cdf,
                "discounted_probability": math.exp(-discount * (count - 1) * delay)
                * active_discounted,
            }
        )
    return {
        "expected_events": math.fsum(row["probability"] for row in rows),
        "discounted_events": math.fsum(row["discounted_probability"] for row in rows),
        "terms": rows,
    }
