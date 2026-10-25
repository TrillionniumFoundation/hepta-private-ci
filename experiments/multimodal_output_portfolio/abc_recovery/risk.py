"""Finite conditional entropic utility; an offline known-model reference.

Node keys identify public histories, never private target realizations. A leaf
stores the conditional utility law given that history, including uncertainty
about a target that has not become observable. This module does not certify a
learned critic, a neural generator, or the provenance of caller-supplied laws.
"""

from dataclasses import dataclass
import math
from typing import Mapping, Sequence


def _probabilities(size: int, probabilities: Sequence[float] | None) -> tuple:
    if size == 0:
        raise ValueError("a finite law needs at least one outcome")
    weights = tuple(float(p) for p in probabilities) if probabilities is not None else (1.0 / size,) * size
    if len(weights) != size or any(not math.isfinite(p) or p < 0 for p in weights):
        raise ValueError("probabilities must be finite, nonnegative and match outcomes")
    total = math.fsum(weights)
    if not math.isclose(total, 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("probabilities must sum to one")
    return tuple(p / total for p in weights)


def conditional_ce(utilities: Sequence[float], probabilities: Sequence[float] | None = None, gamma: float = 2.0) -> float:
    """Return -log E[exp(-gamma * U)] / gamma; gamma=0 returns E[U].

    Inputs describe one conditional law, not unrelated tasks pooled as noise.
    Centered expm1/log1p protects the continuous zero-risk limit; the other
    branch is a shifted weighted logsumexp, so large exponentials are not taken.
    """
    gamma = float(gamma)
    if not math.isfinite(gamma) or gamma < 0:
        raise ValueError("gamma must be finite and nonnegative")
    values = tuple(float(u) for u in utilities)
    if any(not math.isfinite(u) for u in values):
        raise ValueError("utilities must be finite")
    probabilities = _probabilities(len(values), probabilities)
    support = tuple((u, p) for u, p in zip(values, probabilities) if p > 0)
    mean = math.fsum(u * p for u, p in support)
    if gamma == 0:
        return mean
    centered = tuple((-gamma * (u - mean), p) for u, p in support)
    if max(abs(z) for z, _ in centered) <= 0.5:
        correction = math.fsum(p * math.expm1(z) for z, p in centered)
        return mean - math.log1p(correction) / gamma
    minimum = min(u for u, _ in support)
    shifted_sum = math.fsum(p * math.exp(-gamma * (u - minimum)) for u, p in support)
    return minimum - math.log(shifted_sum) / gamma


@dataclass(frozen=True)
class TerminalLaw:
    """Offline conditional U law; private target atoms are not policy nodes."""

    utilities: tuple[float, ...]
    probabilities: tuple[float, ...]


@dataclass(frozen=True)
class Outcome:
    """One joint next-history/cost outcome, conditional on current history/action."""

    probability: float
    next_history: str
    cost: float = 0.0


@dataclass(frozen=True)
class Decision:
    """Feasible actions at one public history; each has a conditional joint law."""

    actions: Mapping[str, tuple[Outcome, ...]]


@dataclass(frozen=True)
class FiniteSolution:
    root_value: float
    values: Mapping[str, float]
    action_values: Mapping[str, Mapping[str, float]]
    policy: Mapping[str, str]


def solve_finite_tree(nodes: Mapping[str, TerminalLaw | Decision], root: str, gamma: float = 2.0, policy: Mapping[str, str] | None = None) -> FiniteSolution:
    """Solve a finite public-history tree, or evaluate a supplied causal policy.

    The known conditional laws must be correct and sufficient for future
    costs/utilities. Histories include any observed cost or information that
    affects those laws. Reusing a key asserts this sufficiency; it is not proved
    here. Budget constraints are represented by the feasible action sets.

    For gamma>0 this is Z(h)=min_a E[exp(gamma*c) Z(h')|h,a], evaluated
    in certainty-equivalent space without exponentiating a large log moment.
    At leaves Z(h)=E[exp(-gamma*U)|h], not exp(-gamma*E[U|h]).
    A supplied policy maps only public history keys to feasible action names.
    Ties in optimization use sorted action names. No policy randomization can
    improve the exact finite-model optimum without additional constraints.
    """
    gamma = float(gamma)
    if not math.isfinite(gamma) or gamma < 0:
        raise ValueError("gamma must be finite and nonnegative")
    values, action_values, chosen, active = {}, {}, {}, set()

    def visit(history: str) -> float:
        if history in active:
            raise ValueError("causal tree contains a cycle")
        if history in values:
            return values[history]
        if history not in nodes:
            raise ValueError(f"unknown public history: {history}")
        active.add(history)
        node = nodes[history]
        if isinstance(node, TerminalLaw):
            value = conditional_ce(node.utilities, node.probabilities, gamma)
        elif isinstance(node, Decision):
            if not node.actions or any(not isinstance(a, str) or not a for a in node.actions):
                raise ValueError("a decision needs nonempty named feasible actions")
            actions = sorted(node.actions)
            if policy is not None:
                if history not in policy or policy[history] not in node.actions:
                    raise ValueError(f"missing or infeasible policy action: {history}")
                actions = [policy[history]]
            scores = {}
            for action in actions:
                outcomes = node.actions[action]
                probabilities = _probabilities(len(outcomes), [o.probability for o in outcomes])
                if any(not math.isfinite(o.cost) or o.cost < 0 for o in outcomes):
                    raise ValueError("realized costs must be finite and nonnegative")
                # Cost and next history stay paired inside the conditional law.
                net_values = [visit(o.next_history) - o.cost for o in outcomes]
                scores[action] = conditional_ce(net_values, probabilities, gamma)
            action_values[history] = scores
            chosen[history] = max(actions, key=lambda a: scores[a])
            value = scores[chosen[history]]
        else:
            raise ValueError("nodes must be Decision or TerminalLaw")
        active.remove(history)
        values[history] = value
        return value

    root_value = visit(root)
    return FiniteSolution(root_value, values, action_values, chosen)


def conditional_policy_loss_bound(uniform_q_errors: Sequence[float]) -> float:
    """Return 2*sum(delta_t), conditional on verified uniform Q* error bounds.

    This is arithmetic for a stated theorem assumption, not a critic certificate.
    Calibration averages, replay agreement and training losses are not inputs
    that establish the required supremum error bounds.
    """
    errors = tuple(float(d) for d in uniform_q_errors)
    if any(not math.isfinite(d) or d < 0 for d in errors):
        raise ValueError("uniform errors must be finite and nonnegative")
    return 2.0 * math.fsum(errors)
