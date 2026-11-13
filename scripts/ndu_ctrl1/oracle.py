"""Exhaustive finite-state DP reference, combinatorially exact with FP64 CE.

This is an offline theoretical upper bound, with no online controller overhead.
The finite-entropic objective is nested at public observation boundaries; it is
not a flattened terminal lottery, a formal numerical proof, or a native solver.
"""

from itertools import product
import math

from .model import backup, legal_actions, transitions


class Oracle:
    def __init__(self, scenario, profile, max_states=20_000):
        if type(max_states) is not int or not 1 <= max_states <= 1_000_000:
            raise ValueError("Invalid oracle state cap")
        self.scenario = scenario
        self.profile = profile
        self.max_states = max_states
        self.states = set()
        self.forecast_calls = 0
        self.expansion_count = 0
        self.legal_mask_calls = 0
        self._values = {}
        self._qs = {}
        self._actions = {}

    def _touch(self, state):
        if state not in self.states and len(self.states) >= self.max_states:
            raise ValueError("Oracle state cap exceeded")
        self.states.add(state)

    @property
    def stats(self):
        return {
            "visited_states": len(self.states),
            "max_states": self.max_states,
            "forecast_calls": self.forecast_calls,
            "expansion_count": self.expansion_count,
            "legal_mask_calls": self.legal_mask_calls,
        }

    def q(self, state, action):
        key = (state, action)
        if key not in self._qs:
            self._touch(state)
            outcomes = transitions(self.scenario, state, action)
            self.forecast_calls += 1
            self.expansion_count += len(outcomes)
            continuations = [
                o.reward if o.next_state is None else self.value(o.next_state)
                for o in outcomes
            ]
            self._qs[key] = backup(outcomes, continuations, self.profile)
        return self._qs[key]

    def value(self, state):
        if state not in self._values:
            self._touch(state)
            self.legal_mask_calls += 1
            # ACTIONS order makes ties deterministic, with stop preferred.
            choices = [
                (action, self.q(state, action))
                for action in legal_actions(self.scenario, state)
            ]
            action, value = max(choices, key=lambda pair: pair[1])
            self._actions[state], self._values[state] = action, value
        return self._values[state]

    def action(self, state):
        self.value(state)
        return self._actions[state]


def independent_tree_value(scenario, profile, state, max_policy_trees=100_000):
    """Enumerate complete contingent policy trees for tiny validation instances.

    Unlike DP this forms the Cartesian product of every child policy choice, using
    no maximizing continuation and no shared backup implementation. A hard cap
    rejects instances too large for this independent check.
    """
    if type(max_policy_trees) is not int or not 1 <= max_policy_trees <= 1_000_000:
        raise ValueError("Invalid policy-tree enumeration cap")
    count = 0

    def enumerate_values(current):
        nonlocal count
        values = []
        for action in legal_actions(scenario, current):
            outcomes = transitions(scenario, current, action)
            choices = [
                (o.reward,) if o.next_state is None else enumerate_values(o.next_state)
                for o in outcomes
            ]
            for continuation in product(*choices):
                count += 1
                if count > max_policy_trees:
                    raise ValueError("Policy-tree enumeration cap exceeded")
                edges = [
                    -profile.resource_weight * o.cost
                    - profile.latency_weight * o.duration
                    + profile.discount_per_second**o.duration * child
                    for o, child in zip(outcomes, continuation)
                ]
                if profile.risk == 0:
                    result = math.fsum(
                        float(o.probability) * edge for o, edge in zip(outcomes, edges)
                    )
                else:
                    shift = min(edges)
                    mass = math.fsum(
                        float(o.probability) * math.exp(-profile.risk * (edge - shift))
                        for o, edge in zip(outcomes, edges)
                    )
                    result = shift - math.log(mass) / profile.risk
                values.append(result)
        return tuple(values)

    return max(enumerate_values(state))
