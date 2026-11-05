"""Bounded Bayesian intervention identification with a simulated physical clock.

Likelihoods are known; the intervention-response hypothesis is not. Hardware
wall time is never substituted for these model durations. Objective: expected
externally scored terminal correctness minus fees, discounted at payment time.
"""
from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
import math


@dataclass(frozen=True)
class Task:
    deadline: int = 4
    fee: float = 0.025
    rho: float = 0.12
    max_probes: int = 3

    def __post_init__(self):
        if (type(self.deadline) is not int or not 0 <= self.deadline <= 8
                or type(self.max_probes) is not int or not 0 <= self.max_probes <= 4
                or not math.isfinite(self.fee) or self.fee < 0
                or not math.isfinite(self.rho) or self.rho < 0):
            raise ValueError("Require finite nonnegative prices/rate and bounded integer horizon")


PROBES = ("fast", "slow", "joint")
ARMS = ("commit_0", "commit_1")


def kernel(probe, hypothesis):
    """Full joint laws (label, duration, probability); failures are not dropped."""
    if probe not in PROBES or hypothesis not in (0, 1):
        raise ValueError("Unknown probe/hypothesis")
    if probe in ("fast", "slow"):
        accuracy, duration = (F(7, 10), 1) if probe == "fast" else (F(49, 50), 3)
        return ((str(hypothesis), duration, F(9, 10)*accuracy),
                (str(1-hypothesis), duration, F(9, 10)*(1-accuracy)),
                ("failure", duration+1, F(1, 10)))
    # Both label marginals AND duration marginals match between hypotheses.
    events = [(str(label), duration, F(2, 5) if
               ((label == 0) == (duration == 1)) == (hypothesis == 0) else F(1, 20))
              for label in (0, 1) for duration in (1, 3)]
    return tuple(events) + (("failure", 2, F(1, 10)),)


def outcomes(probe, remaining, unit_time=False):
    """Censored observable law; unavailable duration beyond timeout is not leaked.

unit_time is an intentionally incorrect planning ablation: preserves the joint
observation identifiers but assumes each probe consumes one clock unit.
"""
    if type(remaining) is not int or remaining < 1:
        raise ValueError("A probe cannot start after the deadline")
    rows = {}
    for h in (0, 1):
        for label, duration, probability in kernel(probe, h):
            event = (label, duration) if unit_time or duration <= remaining else ("timeout", remaining)
            rows.setdefault(event, [F(0), F(0)])[h] += probability
    return tuple((event, tuple(law)) for event, law in sorted(rows.items()))


def update(belief, law):
    evidence = (1-belief)*law[0] + belief*law[1]
    if evidence == 0:
        raise ValueError("Cannot condition on a zero-probability event")
    return belief*law[1]/evidence


def branches(probe, belief, remaining, unit_time=False, label_only=False):
    rows = outcomes(probe, remaining, unit_time)
    for event, law in rows:
        evidence = (1-belief)*law[0] + belief*law[1]
        if not evidence:
            continue
        inference_law = law
        if label_only:
            inference_law = tuple(sum((p[h] for e, p in rows if e[0] == event[0]), F(0)) for h in (0, 1))
        yield event, law, evidence, update(belief, inference_law)


def planner(task, mode="exact"):
    """Return a deterministic policy and cached Bellman values.

The exact planner is a strong Bayesian SMDP baseline, not a proposed new RL
algorithm. fixed_step changes only time accounting; label_only discards joint
duration information from posterior updates. myopic solves one-probe lookahead.
"""
    if mode not in ("exact", "no_probe", "fixed_step", "label_only", "myopic"):
        raise ValueError("Unknown policy")
    unit_time, label_only = mode == "fixed_step", mode == "label_only"

    @lru_cache(None)
    def solve(belief, remaining, available):
        values = {"commit_0": float(1-belief), "commit_1": float(belief)}
        if mode != "no_probe" and remaining > 0 and available > 0:
            for probe in PROBES:
                caps = (remaining,) if unit_time else range(1, remaining+1)
                for cap in caps:
                    terms = []
                    for event, law, mass, posterior in branches(probe, belief, cap, unit_time, label_only):
                        elapsed = 1 if unit_time else event[1]
                        child = solve(posterior, remaining-elapsed, available-1)[0]
                        terms.append(float(mass)*math.exp(-task.rho*elapsed)*child)
                    values[f"{probe}:{cap}"] = -task.fee + math.fsum(terms)
        action = max(values, key=values.get)
        return values[action], action, values

    def policy(belief, remaining, available):
        return solve(belief, remaining, min(available, 1) if mode == "myopic" else available)[1]

    return policy, solve


def evaluate(task, policy, label_only=False, initial=F(1, 2), keep_leaves=True):
    """Enumerate true hidden-state histories, independently of Bellman backups.

The evaluator knows h only to score and weight paths. policy receives belief,
remaining time, and remaining probes; no hidden hypothesis or counterfactual.
"""
    leaves = []

    def visit(h, mass, belief, elapsed, available, fees, history):
        action = policy(belief, task.deadline-elapsed, available)
        if action in ARMS:
            reward = float(action == f"commit_{h}")
            utility = math.exp(-task.rho*elapsed)*reward-fees
            leaves.append({"hypothesis": h, "probability": str(mass), "utility": utility,
                           "discounted_fees": fees, "simulated_clock": elapsed,
                           "decision": action, "history": history})
            return
        parts = action.split(":")
        if len(parts) != 2 or parts[0] not in PROBES or not parts[1].isdigit():
            raise ValueError("Policy attempted an unknown action")
        probe, cap = parts[0], int(parts[1])
        if elapsed >= task.deadline or available == 0 or not 1 <= cap <= task.deadline-elapsed:
            raise ValueError("Policy attempted an illegal probe")
        new_fees = fees + math.exp(-task.rho*elapsed)*task.fee
        for event, law, _, posterior in branches(probe, belief, cap, label_only=label_only):
            if law[h]:
                visit(h, mass*law[h], posterior, elapsed+event[1], available-1,
                      new_fees, history+[[action, event[0], event[1], str(posterior)]])

    for h, mass in ((0, 1-initial), (1, initial)):
        if mass:
            visit(h, mass, initial, 0, task.max_probes, 0.0, [])
    probabilities = [F(row["probability"]) for row in leaves]
    if sum(probabilities, F(0)) != 1:
        raise ArithmeticError("Enumeration lost probability mass")
    expectations = {field: math.fsum(float(p)*row[field] for p, row in zip(probabilities, leaves))
                    for field in ("utility", "discounted_fees", "simulated_clock")}
    expectations.update(expected_probes=math.fsum(float(p)*len(row["history"]) for p, row in zip(probabilities, leaves)),
                        timeout_probability=math.fsum(float(p) for p, row in zip(probabilities, leaves)
                                                     if any(e[1] == "timeout" for e in row["history"])),
                        leaf_count=len(leaves), probability_mass="1")
    if keep_leaves:
        expectations["leaves"] = leaves
    return expectations
