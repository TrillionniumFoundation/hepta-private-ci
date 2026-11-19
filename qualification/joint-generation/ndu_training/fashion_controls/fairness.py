"""Prospective fairness/admission and multiplicity interfaces; no execution."""

from dataclasses import dataclass
import math

from .objectives import ARMS


@dataclass(frozen=True)
class Opportunity:
    model_binding: str
    seed: int
    data_split: str
    encoder: str
    optimizer: str
    sampling: str
    optimization_opportunities: tuple
    static_decoder_opportunities: tuple
    cpu_cap_ns: int
    work_cap: int
    executor: str


def require_matched(plans):
    if set(plans) != set(ARMS) or any(not isinstance(p, Opportunity) for p in plans.values()):
        raise ValueError("all three H/A/N opportunities are required")
    if any(plans[arm] != plans["H"] for arm in ARMS):
        raise ValueError("unmatched model/data/seed/budget/optimization/decoder opportunity")
    plan = plans["H"]
    if any(type(v) is not int or v <= 0 for v in (plan.cpu_cap_ns, plan.work_cap)):
        raise ValueError("positive integer complete-method caps required")
    if not plan.executor:
        raise ValueError("executor identity is required; never mix cloud/dot CPU")
    return plan


class BudgetBook:
    """Charge actual complete-method costs, including full shared-use attribution.

    This is an accounting interface, not a timer or a sandbox. A future runner
    must supply observed process/descendant CPU and validated work counts, from
    process birth through final receipt/export/service. Quotes are not charges.
    Equal caps do NOT require equal update counts or wasteful baseline padding.
    """

    def __init__(self, plans):
        self.plan = require_matched(plans)
        self.used = {a: [0, 0] for a in ARMS}
        self.rows = []
        self.over_cap = False

    def charge(self, consumers, phase, cpu_ns, work, *, executor):
        consumers = tuple(consumers)
        if (not consumers or len(set(consumers)) != len(consumers)
                or not set(consumers) <= set(ARMS) or not phase
                or any(type(v) is not int or v < 0 for v in (cpu_ns, work))):
            raise ValueError("invalid complete-method cost")
        if executor != self.plan.executor:
            raise ValueError("CPU executor identity mismatch")
        for arm in consumers:
            self.used[arm][0] += cpu_ns
            self.used[arm][1] += work
        self.rows.append({"consumers": consumers, "phase": phase, "cpu_ns": cpu_ns,
                          "work": work, "executor": executor})
        self.over_cap |= any(c > self.plan.cpu_cap_ns or w > self.plan.work_cap
                             for c, w in self.used.values())
        if self.over_cap:
            raise RuntimeError("actual cap exceeded; failed row retained, comparison invalid")

    def fits(self, arm, quote_cpu_ns, quote_work, *, tail_cpu_ns, tail_work):
        if arm not in ARMS or any(type(v) is not int or v < 0 for v in
                                 (quote_cpu_ns, quote_work, tail_cpu_ns, tail_work)):
            raise ValueError("invalid next-operation/tail reservation")
        cpu, work = self.used[arm]
        return (not self.over_cap and cpu + quote_cpu_ns + tail_cpu_ns <= self.plan.cpu_cap_ns
                and work + quote_work + tail_work <= self.plan.work_cap)


def holm_gate(pvalues, *, family, alpha):
    """All predeclared claims must be present; missing/selected claims fail closed.

    Requires independently valid prospective p-values, not development results
    or image-row pseudoreplicates. This helper does not manufacture such values.
    """
    family = tuple(family)
    if (not family or len(set(family)) != len(family) or set(pvalues) != set(family)
            or not math.isfinite(alpha) or not 0 < alpha < 1
            or any(not math.isfinite(p) or not 0 <= p <= 1 for p in pvalues.values())):
        raise ValueError("complete predeclared family and valid alpha/p-values required")
    rejected = {name: False for name in family}
    for index, name in enumerate(sorted(family, key=lambda name: (pvalues[name], name))):
        if pvalues[name] > alpha / (len(family) - index):
            break
        rejected[name] = True
    return rejected
