"""Single-factor interventions on the inherited, reachable renewal process.

These are interventions on a count prediction, not on the physical world,
software recovery, or a financial risk channel. Legacy simulator stays intact.
"""

import numpy as np

from experiments.hcsn_mechanism_content_v2.renewal import renewal_counts


def transform_counts(probabilities, intervention):
    p = np.asarray(probabilities, dtype=np.float64)
    if p.ndim != 1 or len(p) < 2 or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("A finite nonnegative count law is required")
    if abs(float(p.sum()) - 1) > 1e-10:
        raise ValueError("Count law must conserve probability")
    if intervention == "original":
        return p.copy()
    result = np.zeros_like(p)
    if intervention == "mean_two_point":
        mean = float(p @ np.arange(len(p)))
        lower = min(int(np.floor(mean)), len(p) - 1)
        if lower == len(p) - 1:
            result[lower] = 1
        else:
            result[lower + 1] = mean - lower
            result[lower] = 1 - result[lower + 1]
    elif intervention == "single_transition":
        result[0], result[1] = p[0], 1 - p[0]
    else:
        raise ValueError("Unknown count intervention")
    return result


class IntervenedRenewal:
    """Same estimated physics; transform only the returned count distribution."""

    def __init__(self, intervention="original", cap=32):
        self.intervention, self.cap = intervention, cap
        self.name = "analytic_" + intervention
        self.calls = self.work = self.cdf_terms = 0
        self.max_multi_mass = self.max_shape_l1 = 0.0
        self.max_mean_change = 0.0

    def counts(self, x, horizon, physics, remaining=0):
        p, work = renewal_counts(x, horizon, physics, remaining, self.cap)
        q = transform_counts(p, self.intervention)
        self.calls += 1
        self.cdf_terms += work["cdf_terms"]
        self.max_multi_mass = max(self.max_multi_mass, float(p[2:].sum()))
        self.max_shape_l1 = max(self.max_shape_l1, float(np.abs(p - q).sum()))
        self.max_mean_change = max(self.max_mean_change, abs(float((p - q) @ np.arange(self.cap))))
        return q
