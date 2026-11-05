"""Bounded, paid conditional moment comparison for a frozen reset experiment.

Statistical premises are supplied by the experiment: IID pairs, IID independent
resets with the SAME conditional predictor law, and a predictor/beta fitted on
separate data. Identity checks do not prove these premises. This is a local
frozen-continuation certificate, not a live policy or whole-policy certificate.
"""

from dataclasses import dataclass
import math


def finite(x):
    return type(x) in (int, float) and math.isfinite(x)


@dataclass(frozen=True)
class Plan:
    target: str
    eta: float
    x_bounds: tuple[float, float]
    h_bounds: tuple[float, float]
    beta: float = 0.0
    delta: float = 0.05
    comparisons: int = 1
    budget: float = 1.0
    fit_cost: float = 0.0
    fit_ids: tuple[str, ...] = ()
    # Includes continuation/gradient/model error translated to local value units.
    value_penalty: float = 0.0

    def __post_init__(self):
        if (not isinstance(self.target, str) or len(self.target) != 64
                or any(c not in "0123456789abcdef" for c in self.target)):
            raise ValueError("Bind a complete frozen target by SHA-256")
        for bounds in (self.x_bounds, self.h_bounds):
            if (not isinstance(bounds, tuple) or len(bounds) != 2
                    or not all(finite(x) for x in bounds) or bounds[0] > bounds[1]):
                raise ValueError("Finite immutable support bounds required")
        if (not all(finite(x) for x in (self.eta, self.beta, self.delta,
                                       self.budget, self.fit_cost, self.value_penalty))
                or self.eta <= 0 or not 0 < self.delta < 1
                or min(self.budget, self.fit_cost, self.value_penalty) < 0
                or type(self.comparisons) is not int or self.comparisons < 1
                or not isinstance(self.fit_ids, tuple)
                or any(not isinstance(x, str) or not x for x in self.fit_ids)
                or len(set(self.fit_ids)) != len(self.fit_ids)):
            raise ValueError("Invalid risk, cost, trial family or fitting partition")
        try:
            moments = [math.exp(-self.eta * x) for x in self.x_bounds]
        except OverflowError as exc:
            raise ValueError("Unsupported exponential support; do not clip") from exc
        if not all(math.isfinite(x) and x > 0 for x in moments):
            raise ValueError("Exponential support underflows or overflows")
        span, hspan = moments[0]-moments[1], self.h_bounds[1]-self.h_bounds[0]
        derived = [hspan, 2*span+abs(self.beta)*hspan, abs(self.beta)*hspan]
        derived += [d-self.beta*h for d in (-span, span) for h in self.h_bounds]
        if not all(math.isfinite(x) for x in derived):
            raise ValueError("Derived residual/predictor support exceeds numeric range")


class PaidAudit:
    """Charge all attempts; compare only supported complete observations.

Fees are declared utility-unit charges, not hardware measurements. Deduct the
FULL fitting/reset/pair fee from one use; no amortization is presumed. Deployment
time/state change during validation needs a separate protocol and is not covered.
"""

    def __init__(self, plan):
        if not isinstance(plan, Plan):
            raise ValueError("A validated frozen plan is required")
        self.plan = plan
        self.spent = plan.fit_cost
        self.ids = set(plan.fit_ids)
        self.pairs, self.resets, self.events, self.invalid = [], [], [], []
        self.looks = 0

    def _record(self, sample_id, target, fee, kind):
        if not finite(fee) or fee < 0:
            raise ValueError("Actual fees must be finite and nonnegative")
        self.spent += fee
        self.events.append({"sample_id": sample_id, "target": target,
                            "fee": fee, "kind": kind})
        if (not isinstance(sample_id, str) or not sample_id
                or sample_id in self.ids or target != self.plan.target):
            self.invalid.append("duplicate_or_wrong_partition_or_target")
            return False
        self.ids.add(sample_id)
        return True

    def pair(self, sample_id, target, candidate, baseline, predictor, fee):
        """A missing/failed observation is charged and blocks certification."""
        if not self._record(sample_id, target, fee, "pair"):
            return
        lo, hi = self.plan.x_bounds
        hlo, hhi = self.plan.h_bounds
        if (not all(finite(x) for x in (candidate, baseline, predictor))
                or not lo <= candidate <= hi or not lo <= baseline <= hi
                or not hlo <= predictor <= hhi):
            self.invalid.append("missing_or_out_of_support_pair")
            return
        d = math.exp(-self.plan.eta * candidate) - math.exp(-self.plan.eta * baseline)
        residual = d - self.plan.beta * predictor
        if not math.isfinite(residual):
            self.invalid.append("nonfinite_residual")
            return
        self.pairs.append(residual)

    def reset(self, sample_id, target, predictor, fee):
        if not self._record(sample_id, target, fee, "reset"):
            return
        lo, hi = self.plan.h_bounds
        if not finite(predictor) or not lo <= predictor <= hi:
            self.invalid.append("missing_or_out_of_support_reset")
            return
        self.resets.append(predictor)

    def decide(self):
        """Union-bound valid at every look, conditional on the stated premises.

For K registered comparisons allocate delta/[K m(m+1)] to pair prefix m,
and additionally divide by n(n+1) when a reset prefix n is used. A union
bound over ALL prefix sizes permits adaptive sample counts and repeated
looks. Look-number spending alone would not justify adaptive counts.
Hoeffding bounds on independent A=D-beta H and H' give an interval for
E[D]. Unbounded/unjustified tails are unsupported.
"""
        self.looks += 1
        p, m, n = self.plan, len(self.pairs), len(self.resets)
        out = {"decision": "no-update", "pairs": m, "resets": n,
               "attempts": len(self.events), "spent": self.spent,
               "look": self.looks, "target": p.target,
               "scope": "local_frozen_target_only"}
        if self.invalid:
            return {**out, "reason": "invalid_evidence", "errors": list(self.invalid)}
        if not math.isfinite(self.spent) or self.spent > p.budget:
            return {**out, "reason": "validation_budget_exhausted"}
        if m < 2 or p.beta != 0 and n < 2:
            return {**out, "reason": "insufficient_independent_samples"}
        max_moment = math.exp(-p.eta * p.x_bounds[0])
        min_moment = math.exp(-p.eta * p.x_bounds[1])
        h_range = p.h_bounds[1] - p.h_bounds[0]
        a_range = 2 * (max_moment - min_moment) + abs(p.beta) * h_range
        log_alpha = math.log(p.delta)-math.log(p.comparisons)-math.log(m)-math.log(m+1)
        if p.beta != 0:
            log_alpha -= math.log(n)+math.log(n+1)
        log_factor = math.log(4)-log_alpha
        radius = a_range * math.sqrt(log_factor / (2 * m))
        estimate = math.fsum(x/m for x in self.pairs)
        if p.beta != 0:
            estimate += p.beta * math.fsum(x/n for x in self.resets)
            radius += abs(p.beta) * h_range * math.sqrt(log_factor / (2 * n))
        upper = estimate + radius
        if not all(math.isfinite(x) for x in (estimate, radius, upper, estimate-radius)):
            return {**out, "reason": "unsupported_numeric_range"}
        # For d<0, -log(1+d/M0)/eta >= -d/(eta*Mmax).
        lower_gain = -upper / (p.eta * max_moment) if upper < 0 else None
        net = None if lower_gain is None else lower_gain - self.spent - p.value_penalty
        adopt = net is not None and net > 0
        return {**out, "decision": "adopt" if adopt else "no-update",
                "reason": "paid_local_gain" if adopt else "gain_not_certified_after_full_cost",
                "moment_difference": estimate, "radius": radius,
                "difference_interval": [estimate - radius, upper],
                "local_gain_lower": lower_gain, "net_gain_lower": net,
                "look_alpha": math.exp(log_alpha), "log_alpha": log_alpha,
                "value_penalty": p.value_penalty}
