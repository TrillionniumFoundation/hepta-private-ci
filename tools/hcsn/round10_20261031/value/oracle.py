"""Exact non-clairvoyant Bellman teacher and independent world enumeration."""

from functools import lru_cache
from itertools import product

import numpy as np

from task import ACTIONS, World, initial, legal, posterior, rollout, successor


def outcomes(config, state):
    p = config.packets[state.next_packet]
    belief = posterior(config, state)
    one = belief * p.reliability + (1 - belief) * (1 - p.reliability)
    return (("0", (1 - p.failure_probability) * (1 - one)),
            ("1", (1 - p.failure_probability) * one), ("x", p.failure_probability))


class Oracle:
    def __init__(self, config):
        self.config = config
        self.states = {}
        self._values = lru_cache(None)(self._compute)

    def _compute(self, state):
        c = self.config
        self.states[state.key] = state
        values = np.full(3, -1e30)
        belief = posterior(c, state)
        values[2] = max(belief, 1 - belief) - c.stop_cost
        if "WAIT" in legal(c, state):
            nxt, cost, _ = successor(c, state, "WAIT")
            values[1] = -cost + max(self.q(nxt))
        if "READ" in legal(c, state):
            values[0] = 0
            for obs, probability in outcomes(c, state):
                if not probability:
                    continue
                nxt, cost, _ = successor(c, state, "READ", obs)
                values[0] += probability * (-cost + max(self.q(nxt)))
        return tuple(float(x) for x in values)

    def q(self, state):
        # Sunk costs are not part of continuation value. Canonicalize the ledger.
        from dataclasses import replace
        return self._values(replace(state, paid_cost=0.0))

    def policy(self, config, state):
        if config != self.config:
            raise ValueError("oracle/task configuration mismatch")
        return choose(self.q(state), legal(config, state))


def choose(values, allowed):
    # Tie order is shared with Rust: STOP, WAIT, READ.
    best = max(values[ACTIONS.index(a)] for a in allowed)
    return next(a for a in ("STOP", "WAIT", "READ")
                if a in allowed and values[ACTIONS.index(a)] >= best - 1e-12)


def expected_policy_value(config, policy):
    @lru_cache(None)
    def value(state):
        action = policy(config, state)
        if action == "STOP" or action not in legal(config, state):
            belief = posterior(config, state)
            return max(belief, 1 - belief) - config.stop_cost - (
                config.invalid_cost if action not in legal(config, state) else 0)
        if action == "WAIT":
            nxt, cost, _ = successor(config, state, action)
            from dataclasses import replace
            return -cost + value(replace(nxt, paid_cost=0.0))
        total = 0
        for obs, probability in outcomes(config, state):
            if probability:
                nxt, cost, _ = successor(config, state, action, obs)
                from dataclasses import replace
                total += probability * (-cost + value(replace(nxt, paid_cost=0.0)))
        return total
    return float(value(initial(config)))


def enumerate_world_value(config, policy, forced_first=None):
    """Independent finite probability sum over latent truth and all evidence.

    This weights worlds before their votes are revealed. It never lets policy
    inputs depend on private truth, votes or success/failure indicators.
    """
    n = len(config.packets)
    utility = 0
    for truth in (0, 1):
        truth_mass = config.prior if truth else 1 - config.prior
        for votes in product((0, 1), repeat=n):
            vote_mass = truth_mass
            for vote, packet in zip(votes, config.packets):
                vote_mass *= packet.reliability if vote == truth else 1 - packet.reliability
            for failures in product((False, True), repeat=n):
                mass = vote_mass
                for fail, packet in zip(failures, config.packets):
                    mass *= packet.failure_probability if fail else 1 - packet.failure_probability
                if mass:
                    result = rollout(config, World(truth, votes, failures), policy,
                                     forced_first=forced_first)
                    utility += mass * result["utility"]
    return utility
