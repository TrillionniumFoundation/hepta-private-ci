"""Separate variance-aware continuation of the retained Hoeffding experiment.

Maurer-Pontil (2009), Theorem 4, https://arxiv.org/pdf/0907.3740:
r=sqrt(2*s^2*log(2/delta)/N)+7*range*log(2/delta)/(3*(N-1)).
Use log(8/alpha) for two streams and two directions. Both methods must receive
separate family error budgets if compared or selected on the same observations.
"""

import math

from .paid_audit import PaidAudit


def empirical_radius(values, support_width, log_factor):
    n = len(values)
    if n < 2:
        raise ValueError("Empirical Bernstein needs at least two observations")
    mean = math.fsum(x/n for x in values)
    variance = math.fsum((x-mean)**2/(n-1) for x in values)
    return math.sqrt(2*variance*log_factor/n) + 7*support_width*log_factor/(3*(n-1))


class VarianceAudit(PaidAudit):
    """A fixed EB rule; it never selects the smaller of EB and Hoeffding."""

    def decide(self):
        prior = super().decide()
        prior["confidence_method"] = "empirical_bernstein_two_sided"
        if "moment_difference" not in prior:
            return prior
        p, m, n = self.plan, len(self.pairs), len(self.resets)
        maximum, minimum = (math.exp(-p.eta*x) for x in p.x_bounds)
        hspan = p.h_bounds[1]-p.h_bounds[0]
        log_factor = math.log(8)-prior["log_alpha"]
        try:
            radius = empirical_radius(self.pairs, 2*(maximum-minimum)+abs(p.beta)*hspan, log_factor)
            if p.beta != 0:
                radius += abs(p.beta)*empirical_radius(self.resets, hspan, log_factor)
        except (OverflowError, ValueError):
            return {"decision": "no-update", "reason": "unsupported_numeric_variance",
                    "spent": self.spent, "scope": prior["scope"]}
        estimate = prior["moment_difference"]
        upper, lower = estimate+radius, estimate-radius
        if not all(math.isfinite(x) for x in (upper, lower, radius)):
            return {"decision": "no-update", "reason": "unsupported_numeric_variance",
                    "spent": self.spent, "scope": prior["scope"]}
        gain = -upper/(p.eta*maximum) if upper < 0 else None
        net = None if gain is None else gain-self.spent-p.value_penalty
        adopt = net is not None and net > 0
        return {**prior, "decision": "adopt" if adopt else "no-update",
                "reason": "paid_local_gain" if adopt else "gain_not_certified_after_full_cost",
                "radius": radius, "difference_interval": [lower, upper],
                "local_gain_lower": gain, "net_gain_lower": net}
