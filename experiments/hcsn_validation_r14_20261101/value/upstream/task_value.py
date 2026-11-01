"""Finite-horizon task values for the frozen, joint R12 state model.

Rows are beliefs over phase-major (phase, content-bit) states. READ observes at
the interval END and pays the end-state fee. That sampled fee is evaluator-only
information; receiving it during execution would require another Bayes update.
RESET first applies R, then evolves for the complete interval. It costs 0.04
and restarts recovery without directly changing the bit. Retention belongs to
the recovery transitions in Q, so it must not be applied a second time in R.

The recursion is exact for the supplied finite model, up to floating-point
matrix exponentials. It does not solve the original He--Xiong stopping problem,
prove a continuum limit, or receive any hidden state or future observation.
"""
from functools import lru_cache
import hashlib
import math

import numpy as np
from scipy.linalg import expm


ACTIONS = ("STOP0", "STOP1", "WAIT", "READ", "RESET")
SCHEMA = "hcsn.r12.finite-belief-dp.v1"


def _array(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.array(value, dtype=np.float64, copy=True)


def choose_values(values):
    """Prefer STOP0/STOP1/WAIT/READ/RESET for ties within 1e-12 utility."""
    choice = next(action for action in ACTIONS if action in values)
    for action in ACTIONS:
        if action in values and values[action] > values[choice] + 1e-12:
            choice = action
    return choice


class ExactBeliefDP:
    """A common controller, with an immutable snapshot of the fitted model.

    ``schedule`` contains the remaining, publicly known positive time intervals;
    exhausting it forces an answer. A READ or RESET consumes an actual interval.
    All policies use this same model even when their causal belief estimates are
    produced by different cores. ``budget`` counts remaining real READ actions.
    """

    def __init__(self, cell, reset_cost=.04, latency_price=.01, read_multiplier=1.):
        self.Q, self.E, self.R = (_array(getattr(cell, name)) for name in ("Q", "E", "R"))
        self.reward, self.read_cost = (_array(getattr(cell, name)) for name in ("reward", "read_cost"))
        self.reset_cost, self.latency_price = float(reset_cost), float(latency_price)
        self.read_multiplier = float(read_multiplier)
        prices = (self.reset_cost, self.latency_price, self.read_multiplier)
        if not all(math.isfinite(x) and x >= 0 for x in prices):
            raise ValueError("Task prices must be finite and nonnegative")
        if self.Q.ndim != 2 or self.Q.shape[0] != self.Q.shape[1]:
            raise ValueError("A square row generator is required")
        self.states = self.Q.shape[0]
        if (self.states < 2 or self.R.shape != self.Q.shape or self.E.ndim != 2
                or self.E.shape[0] != self.states or self.E.shape[1] < 1
                or self.reward.shape != (self.states, 2)
                or self.read_cost.shape != (self.states,)):
            raise ValueError("Inconsistent finite-model shapes")
        matrices = (self.Q, self.E, self.R, self.reward, self.read_cost)
        if not all(np.isfinite(x).all() for x in matrices):
            raise ValueError("Nonfinite finite-model data")
        off_diagonal = self.Q.copy()
        np.fill_diagonal(off_diagonal, 0.)
        if (off_diagonal.min() < 0 or np.max(np.abs(self.Q.sum(1))) > 1e-10
                or self.read_cost.min() < 0):
            raise ValueError("Invalid generator or READ costs")
        for matrix in (self.E, self.R):
            if matrix.min() < 0 or np.max(np.abs(matrix.sum(1)-1)) > 1e-10:
                raise ValueError("Emission/reset rows must be stochastic")
        digest = hashlib.sha256(SCHEMA.encode())
        for matrix in matrices:
            digest.update(str(matrix.shape).encode())
            digest.update(matrix.tobytes())
            matrix.flags.writeable = False
        digest.update(np.asarray(prices, dtype=np.float64).tobytes())
        self.model_identity = digest.hexdigest()
        self._q_cached = lru_cache(maxsize=16384)(self._q_core)
        self._transition = lru_cache(maxsize=128)(self._make_transition)

    def _inputs(self, belief, schedule, budget):
        p = np.asarray(belief, dtype=np.float64)
        if (p.shape != (self.states,) or not np.isfinite(p).all()
                or p.min() < -2e-12 or abs(p.sum()-1) > 2e-10):
            raise ValueError("Belief must be a normalized finite-model row")
        # Accommodate only floating-point roundoff, not arbitrary input scores.
        p = np.maximum(p, 0.)
        p = p / p.sum()
        times = tuple(float(dt) for dt in schedule)
        if len(times) > 8 or any(not math.isfinite(dt) or dt <= 0 for dt in times):
            raise ValueError("At most eight finite positive intervals are supported")
        if isinstance(budget, bool) or not isinstance(budget, (int, np.integer)) or budget < 0:
            raise ValueError("READ budget must be a nonnegative integer")
        return p, times, int(budget)

    def _make_transition(self, dt):
        matrix = expm(self.Q*dt)
        if matrix.min() < -2e-12 or np.max(np.abs(matrix.sum(1)-1)) > 2e-10:
            raise ArithmeticError("Frozen generator transition lost probability")
        matrix.flags.writeable = False
        return matrix

    @staticmethod
    def legal_actions(schedule, budget):
        if not schedule:
            return ACTIONS[:2]
        return ACTIONS if budget else ("STOP0", "STOP1", "WAIT", "RESET")

    def _action_value(self, action, p, schedule, budget, continuation):
        if action in ("STOP0", "STOP1"):
            return float(p @ self.reward[:, int(action[-1])])
        dt, rest = schedule[0], schedule[1:]
        matrix = self._transition(dt)
        time_cost = self.latency_price*dt
        if action == "RESET":
            successor = p @ self.R @ matrix
            return -self.reset_cost-time_cost+continuation(successor, rest, budget)
        successor = p @ matrix
        if action == "WAIT":
            return -time_cost+continuation(successor, rest, budget)
        total = -time_cost-self.read_multiplier*float(successor @ self.read_cost)
        joint = successor[:, None]*self.E
        probabilities = joint.sum(0)
        for observation, probability in enumerate(probabilities):
            if probability > 0:
                posterior = joint[:, observation]/probability
                total += float(probability)*continuation(posterior, rest, budget-1)
        return float(total)

    def _value(self, p, schedule, budget):
        return max(value for _, value in self._q_cached(p.tobytes(), schedule, budget))

    def _q_core(self, encoded, schedule, budget):
        p = np.frombuffer(encoded, dtype=np.float64)
        return tuple((action, self._action_value(action, p, schedule, budget, self._value))
                     for action in self.legal_actions(schedule, budget))

    def action_values(self, belief, schedule, budget=2):
        p, times, budget = self._inputs(belief, schedule, budget)
        return dict(self._q_cached(p.tobytes(), times, budget))

    def choose(self, belief, schedule, budget=2):
        return choose_values(self.action_values(belief, schedule, budget))

    def value(self, belief, schedule, budget=2):
        return max(self.action_values(belief, schedule, budget).values())

    def channels(self, belief, schedule, budget=2):
        q = self.action_values(belief, schedule, budget)
        active = "WAIT" in q
        a = max(q[action] for action in ("WAIT", "READ") if action in q) if active else None
        b = q.get("RESET")
        stop = max(q["STOP0"], q["STOP1"])
        return dict(A=a, B=b, advantage=None if not active else a-b,
                    stop=stop, reset_strictly_optimal=bool(active and b > max(a, stop)+1e-12),
                    action=choose_values(q), q=q)

    def _policy_evaluator(self, policy):
        """Evaluate a deterministic belief-Markov policy, not an oracle tail.

        The callback receives only (belief, remaining schedule, READ budget).
        A recurrent policy with additional hidden memory must augment the state
        before using this evaluator; silently dropping its memory is invalid.
        """
        @lru_cache(maxsize=16384)
        def evaluate(encoded, schedule, budget):
            p = np.frombuffer(encoded, dtype=np.float64)
            action = policy(p.copy(), schedule, budget)
            if action not in self.legal_actions(schedule, budget):
                raise ValueError("Continuation policy selected an infeasible action")
            return self._action_value(action, p, schedule, budget, tail)

        def tail(p, schedule, budget):
            return evaluate(p.tobytes(), schedule, budget)

        return tail

    def evaluate_policy(self, belief, schedule, budget=2, policy=None):
        if policy is None:
            raise ValueError("An explicit deployed continuation policy is required")
        p, times, budget = self._inputs(belief, schedule, budget)
        return self._policy_evaluator(policy)(p, times, budget)

    def paired_q_pi(self, belief, schedule, budget=2, policy=None):
        """Force each first action, then execute the SAME supplied policy."""
        if policy is None:
            raise ValueError("An explicit deployed continuation policy is required")
        p, times, budget = self._inputs(belief, schedule, budget)
        tail = self._policy_evaluator(policy)
        return {action: self._action_value(action, p, times, budget, tail)
                for action in self.legal_actions(times, budget)}

    def cache_info(self):
        return dict(values=self._q_cached.cache_info()._asdict(),
                    transitions=self._transition.cache_info()._asdict())
