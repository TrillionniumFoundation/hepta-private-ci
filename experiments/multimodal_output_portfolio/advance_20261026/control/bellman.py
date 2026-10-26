"""Finite risk-sensitive control with explicit rejection, budget and state.

This solver is exact only for its supplied finite transition model. Passing a
learned posterior or an approximate owner transition does not certify it. A
state identifier must distinguish all owner/history variables that affect the
future law or admissible set. Costs stay inside the transition expectation.
"""

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np


GAMMA = 2.0
REJECTION_UTILITY = -1.0


@dataclass(frozen=True)
class Branch:
    """One observable outcome branch, including its realized incremental cost."""

    probability: float
    cost: float
    next_state: str | None = None
    terminal_utility: float | None = None


@dataclass(frozen=True)
class State:
    """A complete supplied control state with its current feasible actions."""

    horizon: int
    actions: Mapping[str, tuple[Branch, ...]]
    stop_moment: float | None = None
    rejection_utility: float = REJECTION_UTILITY


@dataclass(frozen=True)
class Solution:
    """Chosen nonanticipating action and moment for each reached model state."""

    root_moment: float
    root_certainty_equivalent: float
    actions: Mapping[str, str | None]
    moments: Mapping[str, float]
    action_moments: Mapping[str, Mapping[str, float]]


def solve(states: Mapping[str, State], initial: str, gamma=GAMMA):
    if not math.isfinite(gamma) or gamma <= 0 or initial not in states:
        raise ValueError("Positive risk coefficient and existing initial state required")
    chosen, values, action_values = {}, {}, {}

    def visit(name):
        if name in values:
            return values[name]
        state = states[name]
        if state.horizon < 0 or not math.isfinite(state.rejection_utility):
            raise ValueError("Invalid horizon or rejection terminal")
        scores = {}
        if state.stop_moment is not None:
            if not math.isfinite(state.stop_moment) or state.stop_moment <= 0:
                raise ValueError("Stop requires its conditional positive terminal moment")
            scores['stop'] = float(state.stop_moment)
        if state.horizon == 0 and state.actions:
            raise ValueError("A zero-horizon state cannot start another action")
        for action, branches in state.actions.items():
            if action == 'stop' or not action or not branches:
                raise ValueError("Nonempty named continuation branches required")
            if any(not math.isfinite(b.probability) or b.probability < 0 for b in branches):
                raise ValueError("Invalid branch probability")
            if not math.isclose(math.fsum(b.probability for b in branches), 1., abs_tol=1e-12):
                raise ValueError("Every conditional action law must sum to one")
            terms = []
            for branch in branches:
                if not math.isfinite(branch.cost) or branch.cost < 0:
                    raise ValueError("Explicit finite nonnegative cost required")
                terminal = branch.terminal_utility is not None
                if terminal == (branch.next_state is not None):
                    raise ValueError("A branch ends at exactly one terminal or next state")
                if terminal:
                    if not math.isfinite(branch.terminal_utility):
                        raise ValueError("Finite terminal utility required")
                    continuation = math.exp(-gamma * branch.terminal_utility)
                else:
                    if branch.next_state not in states:
                        raise ValueError("Missing successor state")
                    if states[branch.next_state].horizon >= state.horizon:
                        raise ValueError("Horizon must strictly decrease; no hidden cycles")
                    continuation = visit(branch.next_state)
                terms.append(branch.probability * math.exp(gamma * branch.cost) * continuation)
            scores[action] = math.fsum(terms)
        if not scores:
            chosen[name], values[name] = None, math.exp(-gamma * state.rejection_utility)
        else:
            # Stable lexical ties put 'stop' first through an explicit key.
            selected = min(scores, key=lambda a: (scores[a], a != 'stop', a))
            chosen[name], values[name] = selected, scores[selected]
        action_values[name] = scores
        return values[name]

    root = visit(initial)
    return Solution(root, -math.log(root) / gamma, chosen, values, action_values)


def terminal_portfolio(utility, belief, admitted, *, costs=None,
                       rejection_probability=None, gamma=GAMMA,
                       rejection_utility=REJECTION_UTILITY, stop_code=None):
    """Expected finite-code moments from public belief and measured endpoint U.

utility[action,target] is a frozen endpoint observation table. belief is a
public target probability vector, not an actual target. Optional target-wise
cost/rejection arrays preserve their dependence inside the expectation. The
caller supplies the actual current admission mask; no false admission is
silently treated as an ordinary stop. stop_code retains the same known endpoint
with zero incremental action cost and does not receive a new output draw.
"""
    utility = np.asarray(utility, dtype=np.float64)
    belief = np.asarray(belief, dtype=np.float64)
    admitted = np.asarray(admitted, dtype=bool)
    if (utility.ndim != 2 or belief.shape != (utility.shape[1],)
            or admitted.shape != (utility.shape[0],)
            or not np.isfinite(utility).all() or not np.isfinite(belief).all()
            or (belief < 0).any() or not np.isclose(belief.sum(), 1., atol=1e-12)
            or not math.isfinite(gamma) or gamma <= 0):
        raise ValueError("Finite utility matrix, normalized public belief and exact mask required")
    cost = np.zeros_like(utility) if costs is None else np.broadcast_to(np.asarray(costs, dtype=np.float64), utility.shape)
    reject = np.zeros_like(utility) if rejection_probability is None else np.broadcast_to(
        np.asarray(rejection_probability, dtype=np.float64), utility.shape)
    if (not np.isfinite(cost).all() or (cost < 0).any() or not np.isfinite(reject).all()
            or (reject < 0).any() or (reject > 1).any()):
        raise ValueError("Valid joint costs and rejection law required")
    moments = (np.exp(gamma * cost) * ((1 - reject) * np.exp(-gamma * utility)
               + reject * math.exp(-gamma * rejection_utility))) @ belief
    options = {int(a): float(moments[a]) for a in np.flatnonzero(admitted)}
    if stop_code is not None:
        if not isinstance(stop_code, int) or not 0 <= stop_code < len(utility):
            raise ValueError("Stop must retain an actual existing endpoint code")
        options['stop'] = float(np.exp(-gamma * utility[stop_code]) @ belief)
    if not options:
        return {'action': None, 'moment': math.exp(-gamma * rejection_utility),
                'moments': moments, 'status': 'actual_no_admitted_action'}
    choice = min(options, key=lambda a: (options[a], a != 'stop', str(a)))
    return {'action': choice, 'moment': options[choice], 'moments': moments,
            'status': 'selected_from_supplied_current_feasible_set'}
