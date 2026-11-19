"""Positive uniformization for one finite CTMC first hit and phase release.

The stated bound is Poisson truncation only; FP64 roundoff is not certified.
No spectral/JF subtraction is used. This is not a delayed-renewal solver.
"""

import math
import numpy as np
from scipy.special import gammainc, gammaincc


def phase_count(down, up, reset, time, width=0.025):
    down, up, reset = (np.asarray(x, dtype=float) for x in (down, up, reset))
    n = len(down)
    if (down.shape != (n,) or up.shape != (n,) or reset.shape != (n,)
            or not n or not np.all(np.isfinite(np.r_[down, up, reset]))
            or np.min(np.r_[down, up, reset]) < 0
            or abs(reset.sum() - 1) > 1e-12
            or not math.isfinite(time) or not 0 <= time <= 0.2
            or not math.isfinite(width) or not 0 < width <= 0.2):
        raise ValueError("normalized interior reset, nonnegative rates and first-cycle domain required")
    if time == 0:
        return {"M": 0.0, "truncation_bound": 0.0, "terms": 0,
                "roundoff_certified": False}
    nu = float(np.nextafter(np.max(down + up), np.inf))
    if nu <= 0:
        return {"M": 0.0, "truncation_bound": 0.0, "terms": 0,
                "roundoff_certified": False}
    lo, hi = max(0.0, time - width), time
    lam = nu * hi
    cutoff = math.ceil(lam + 14 * math.sqrt(lam) + 100)
    if cutoff > 500000:
        raise ValueError("explicit uniformization term budget exceeded")
    k = np.arange(cutoff + 1)
    a, b = gammainc(k + 1, nu * hi), gammainc(k + 1, nu * lo)
    coeff = np.where(b > 0.5, gammaincc(k + 1, nu * lo) - gammaincc(k + 1, nu * hi), a - b)
    coeff /= nu * width
    if not np.all(np.isfinite(coeff)) or coeff.min() < 0:
        raise ArithmeticError("nonpositive phase integral coefficients")
    stay, left, right = 1 - (down + up) / nu, down / nu, up / nu
    if stay.min() < 0:
        raise ArithmeticError("uniformization transition is not positive")
    # Forward row masses include separate absorbing lower and upper coordinates.
    mass = np.r_[0.0, reset, 0.0]
    lower_sum, compensation, max_drift = 0.0, 0.0, 0.0
    for weight in coeff:
        term = weight * mass[0] - compensation
        value = lower_sum + term
        compensation = (value - lower_sum) - term
        lower_sum = value
        old = mass[1:-1]
        updated = np.zeros(n + 2)
        updated[0], updated[-1] = mass[0], mass[-1]
        updated[1:-1] = stay * old
        updated[:-2] += left * old
        updated[2:] += right * old
        mass = updated
        max_drift = max(max_drift, abs(float(mass.sum()) - 1))
    bound = hi * float(gammainc(cutoff + 1, lam)) / width
    return {"M": lower_sum, "truncation_bound": bound, "terms": cutoff + 1,
            "nu": nu, "max_power_mass_drift": max_drift,
            "minimum_transition_weight": float(stay.min()),
            "roundoff_certified": False}
