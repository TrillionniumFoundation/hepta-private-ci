"""Exact finite-state DP for task.py, with an independently written transition law.

No Episode, realized truth, future votes, task.step, or task.legal_actions is used.
This is a discrete evidence-task oracle, not a solution of a continuous QVI.
"""

from functools import lru_cache
import itertools
import math

from .task import ACTIONS, State, TaskParameters


def _parameters(state, parameters):
    if isinstance(parameters, dict):
        parameters = TaskParameters(**parameters)
    if parameters is not None and parameters != state.parameters:
        raise ValueError("oracle parameters must match the public task configuration")
    return state.parameters


def _key(state):
    return (state.tick, state.remaining_budget, state.reads, state.vote_sum,
            state.delayed_status, state.delayed_vote, state.terminated)


def _belief(k, p):
    logodds = math.log(p.prior_probability / (1 - p.prior_probability))
    logodds += k[3] * math.log(p.ordinary_reliability / (1 - p.ordinary_reliability))
    if k[4] == "observed":
        logodds += k[5] * math.log(p.delayed_reliability / (1 - p.delayed_reliability))
    return 1 / (1 + math.exp(-logodds)) if logodds >= 0 else math.exp(logodds) / (1 + math.exp(logodds))


def _permitted(k, action, p):
    t, budget, reads, _, status, _, terminated = k
    if terminated:
        return False
    if action == "STOP":
        return True
    if t + 1 >= p.horizon:
        return False
    if action == "READ":
        return reads < p.ordinary_count and budget >= p.read_budget
    if action == "WAIT":
        return True
    return status == "corrupt" and budget >= p.repair_budget


def _branches(k, requested, p):
    """Yield (probability, successor-key, immediate expected/realized reward)."""
    if k[6]:
        return ((1.0, k, 0.0),)
    action = requested if _permitted(k, requested, p) else "STOP"
    cost = getattr(p, action.lower() + "_cost") + p.latency_cost
    if action != requested:
        cost += p.invalid_attempt_cost
    t, budget, reads, vote_sum, status, delayed_vote, _ = k
    posterior = _belief(k, p)
    if action == "STOP":
        terminal = (t + 1, budget, reads, vote_sum, status, delayed_vote, True)
        return ((1.0, terminal, abs(2 * posterior - 1) - cost),)
    debit = p.read_budget if action == "READ" else p.repair_budget if action == "REPAIR" else 0
    arrives = status == "pending" and t < p.arrival_tick <= t + 1
    corruption_cases = ((False, 1 - p.corruption_probability), (True, p.corruption_probability)) if arrives else ((False, 1.0),)
    outcomes = []
    for corrupt, corruption_mass in corruption_cases:
        if corruption_mass == 0:
            continue
        reveal_delayed = action == "REPAIR" or (arrives and not corrupt)
        normal_values = (-1, 1) if action == "READ" else (0,)
        delayed_values = (-1, 1) if reveal_delayed else (0,)
        for normal_vote, new_delayed in itertools.product(normal_values, delayed_values):
            # Evidence sources are independent conditional on H, not marginally.
            mass = 0.0
            for truth, prior_mass in ((1, posterior), (-1, 1 - posterior)):
                likelihood = 1.0
                if action == "READ":
                    likelihood *= p.ordinary_reliability if normal_vote == truth else 1 - p.ordinary_reliability
                if reveal_delayed:
                    likelihood *= p.delayed_reliability if new_delayed == truth else 1 - p.delayed_reliability
                mass += prior_mass * likelihood
            new_status = "observed" if reveal_delayed else "corrupt" if arrives and corrupt else status
            successor = (t + 1, budget - debit, reads + int(action == "READ"),
                         vote_sum + normal_vote, new_status,
                         new_delayed if reveal_delayed else delayed_vote, False)
            outcomes.append((corruption_mass * mass, successor, -cost))
    return tuple(outcomes)


@lru_cache(maxsize=200000)
def _value(k, p):
    if k[6]:
        return 0.0
    return max(_q(k, action, p, False) for action in ACTIONS if _permitted(k, action, p))


def _q(k, action, p, myopic):
    result = 0.0
    for probability, successor, reward in _branches(k, action, p):
        continuation = 0.0
        if not successor[6]:
            continuation = (_branches(successor, "STOP", p)[0][2] if myopic
                            else _value(successor, p))
        result += probability * (reward + continuation)
    return result


def action_values(state, parameters=None):
    """Q* after each requested action, followed by optimal public-state actions.

    Values exclude sunk prefix costs. Unavailable requested actions execute STOP
    plus a real failed-attempt charge; callers must mask them during training.
    """
    p = _parameters(state, parameters)
    return {action: _q(_key(state), action, p, False) for action in ACTIONS}


def myopic_action_values(state, parameters=None):
    """Take the requested action, then submit immediately, using identical costs."""
    p = _parameters(state, parameters)
    return {action: _q(_key(state), action, p, True) for action in ACTIONS}


def value(state, parameters=None):
    return _value(_key(state), _parameters(state, parameters))


def best_action(state, parameters=None):
    p = _parameters(state, parameters)
    if state.terminated:
        raise ValueError("terminal state has no policy action")
    values = action_values(state, p)
    return max((a for a in ACTIONS if _permitted(_key(state), a, p)), key=values.get)


def transition_distribution(state, action, parameters=None):
    """Conditional outcomes for audit; no private episode is required."""
    if action not in ACTIONS:
        raise ValueError("action must be one of ACTIONS")
    p = _parameters(state, parameters)
    if state.terminated:
        return ((1.0, state, 0.0),)
    actual = action if _permitted(_key(state), action, p) else "STOP"
    cost = getattr(p, actual.lower() + "_cost") + p.latency_cost
    if actual != action:
        cost += p.invalid_attempt_cost
    outcomes = []
    for probability, k, reward in _branches(_key(state), action, p):
        answer = (1 if state.posterior >= 0.5 else -1) if k[6] else 0
        successor = State(p, k[0], k[1], k[2], k[3], k[4], k[5], k[6], answer,
                          state.total_cost + cost)
        outcomes.append((probability, successor, reward))
    return tuple(outcomes)


def cache_info():
    return _value.cache_info()._asdict()
