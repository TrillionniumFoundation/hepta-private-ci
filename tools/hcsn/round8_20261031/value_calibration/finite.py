"""Finite known-model targets and an execution-based independent reference.

Training branches use the upstream oracle; validation enumerates private worlds
conditional on public evidence and calls the actual upstream task.step instead.
No private world enters the fitted predictor or its runtime input.
"""

from dataclasses import replace
from functools import lru_cache
from itertools import product

import numpy as np

from experiments.analytic_event_neuron.round7 import oracle, task


COMPUTE = .0005
EVENT = .0002
ACTIONS = task.ACTIONS


def configurations(regime="nominal"):
    presets = ({}, {"horizon": 3, "budget": 2}, {"horizon": 4, "budget": 4},
        {"horizon": 6, "budget": 1}, {"horizon": 2, "budget": 0},
        {"read_cost": .04, "repair_cost": .05}, {"read_cost": .004, "wait_cost": .012},
        {"ordinary_reliability": .8, "delayed_reliability": .85})
    shifts = {"nominal": {}, "drift": {"ordinary_reliability": .57,
        "delayed_reliability": .72, "prior_probability": .65},
        "missing": {"corruption_probability": .8, "arrival_tick": 3},
        "cost_shift": {"read_cost": .08, "repair_cost": .12, "latency_cost": .02}}
    return [replace(task.TaskParameters(), **(p | shifts[regime])) for p in presets]


def canonical(state):
    return replace(state, total_cost=0.)


def worlds(state):
    """Enumerate conditional hidden worlds, including already known evidence."""
    p = state.parameters
    positive = (state.reads + state.vote_sum) // 2
    prefix = (1,) * positive + (-1,) * (state.reads - positive)
    result = []
    for truth, belief in ((1, state.posterior), (-1, 1 - state.posterior)):
        for votes in product((-1, 1), repeat=p.ordinary_count - state.reads):
            mass = belief * np.prod([p.ordinary_reliability if v == truth
                else 1 - p.ordinary_reliability for v in votes])
            delayed = (state.delayed_vote,) if state.delayed_status == "observed" else (-1, 1)
            corrupts = ((True, 1.),) if state.delayed_status == "corrupt" else (
                ((False, 1.),) if state.delayed_status == "observed" else
                ((False, 1 - p.corruption_probability), (True, p.corruption_probability)))
            for delayed_vote in delayed:
                weight = 1. if state.delayed_status == "observed" else (
                    p.delayed_reliability if delayed_vote == truth else 1 - p.delayed_reliability)
                for corrupt, corruption_mass in corrupts:
                    probability = float(mass * weight * corruption_mass)
                    if probability:
                        result.append((probability, task.Episode(0, p, truth,
                            prefix + votes, delayed_vote, corrupt)))
    if abs(sum(p for p, _ in result) - 1) > 1e-12:
        raise AssertionError("conditional world mass")
    return result


def execution_branches(state, action):
    grouped = {}
    for probability, episode in worlds(state):
        result = task.step(state, action, episode)
        successor = canonical(result.state)
        key = (successor, result.reward)
        grouped[key] = grouped.get(key, 0.) + probability
    return [(p, s, r) for (s, r), p in grouped.items()]


def build_graph(configs, independent=False):
    states, ids, starts, edges = [], {}, [], {}
    def register(state):
        state = canonical(state)
        if state not in ids:
            ids[state] = len(states)
            states.append(state)
        return ids[state]
    for p in configs:
        starts.append(register(task.State(p, remaining_budget=p.budget)))
    cursor = 0
    brancher = execution_branches if independent else oracle.transition_distribution
    while cursor < len(states):
        state = states[cursor]
        for a, action in enumerate(ACTIONS):
            if action in task.legal_actions(state):
                edges[cursor, a] = [(p, -1 if s.terminated else register(s), r)
                    for p, s, r in brancher(state, action) if p]
        cursor += 1
    legal = np.array([[(i, a) in edges for a in range(4)] for i in range(len(states))])
    return {"states": states, "ids": ids, "starts": starts, "edges": edges, "legal": legal,
        "x": np.array([task.features(s) for s in states]),
        "order": sorted(range(len(states)), key=lambda i: states[i].tick, reverse=True)}


def targets(graph, matrix, events, actions=None):
    """Training solver: backward substitution, max after observing cell state."""
    count, latent = matrix.shape[:2]
    q = np.full((count, latent, 4), -np.inf)
    values = np.zeros((count, latent))
    for i in graph["order"]:
        for a in np.flatnonzero(graph["legal"][i]):
            q[i, :, a] = sum(p * (r + (values[j] if j >= 0 else 0.))
                for p, j, r in graph["edges"][i, a]) - COMPUTE
        after = q[i].max(-1) if actions is None else q[i, np.arange(latent), actions[i]]
        values[i] = matrix[i] @ after - EVENT * events[i]
    return q, values


def reference(graph, matrix, events, actions=None):
    """Separate recursive evaluator, normally on execution-enumerated edges."""
    @lru_cache(None)
    def value(i, z):
        total = -EVENT * events[i, z]
        for after, mass in enumerate(matrix[i, z]):
            if mass:
                qs = []
                for a in np.flatnonzero(graph["legal"][i]):
                    qs.append((a, -COMPUTE + sum(p * (r + (value(j, after) if j >= 0 else 0.))
                        for p, j, r in graph["edges"][i, a])))
                selected = max(v for _, v in qs) if actions is None else dict(qs)[int(actions[i, after])]
                total += mass * selected
        return total
    return np.array([[value(i, z) for z in range(matrix.shape[1])]
        for i in range(len(graph["states"]))])
