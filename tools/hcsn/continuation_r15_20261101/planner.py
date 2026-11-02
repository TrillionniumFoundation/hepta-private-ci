"""Checked finite-model planning with batched unnormalized branch masses.

The accelerator preserves the inherited finite-horizon objective and public
information. It is common to every estimator, including an ordinary HMM. It
does not change an HX boundary, train a model, or claim a new exact diffusion.
"""

from functools import lru_cache
import warnings

import numpy as np
from scipy.linalg import expm

from ..unified_cell_r12_20261031.task_value import ExactBeliefDP, choose_values


class CheckedBeliefDP(ExactBeliefDP):
    """Reject invalid numerical successors instead of silently choosing STOP."""

    def _make_transition(self, dt):
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            scaled = self.Q * dt
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                try:
                    matrix = expm(scaled)
                except RuntimeWarning as error:
                    raise ArithmeticError("Transition exponential is not finite") from error
        if (not np.isfinite(matrix).all() or matrix.min() < -2e-12
                or np.max(np.abs(matrix.sum(1) - 1)) > 2e-10):
            raise ArithmeticError("Transition exponential lost finite probability")
        matrix.flags.writeable = False
        return matrix

    def action_values(self, belief, schedule, budget=2):
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            values = super().action_values(belief, schedule, budget)
        if not all(np.isfinite(value) for value in values.values()):
            raise ArithmeticError("A finite action value is required")
        return values

    def evaluate_policy(self, belief, schedule, budget=2, policy=None):
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            value = super().evaluate_policy(belief, schedule, budget, policy)
        if not np.isfinite(value):
            raise ArithmeticError("A finite actual-policy value is required")
        return value

    def paired_q_pi(self, belief, schedule, budget=2, policy=None):
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            values = super().paired_q_pi(belief, schedule, budget, policy)
        if not all(np.isfinite(value) for value in values.values()):
            raise ArithmeticError("Finite paired actual-policy values are required")
        return values

    def channels(self, belief, schedule, budget=2):
        values = self.action_values(belief, schedule, budget)
        continuation = [values[a] for a in ("WAIT", "READ") if a in values]
        a = max(continuation) if continuation else None
        b = values.get("RESET")
        stop = max(values["STOP0"], values["STOP1"])
        return dict(A=a, B=b, advantage=a-b if a is not None and b is not None else None,
                    stop=stop, reset_strictly_optimal=bool(
                        b is not None and b > max(stop, a if a is not None else stop) + 1e-12),
                    action=self.choose(belief, schedule, budget), q=values)


class BatchedBeliefDP(CheckedBeliefDP):
    """Batch branch masses for horizons <= 3; retain the reference otherwise.

Homogeneity gives V(u)=sum(u)*V(u/sum(u)). Thus observation branches can
retain their joint masses and avoid posterior division and Python per-symbol
recursion. No policy-vector cross product or approximation cutoff is used.
Near the inherited tie tolerance, choose() evaluates the checked reference.
"""

    def __init__(self, cell, reset_cost=.04, latency_price=.01, read_multiplier=1.):
        super().__init__(cell, reset_cost, latency_price, read_multiplier)
        self._operators = lru_cache(maxsize=128)(self._make_operators)
        self._reference = None
        self.reference_fallbacks = 0

    def _make_operators(self, dt):
        matrix = self._transition(dt)
        reset_matrix = self.R @ matrix
        # Each column is a reward for a particular observation and terminal bit.
        marked_reward = (self.E[:, :, None] * self.reward[:, None, :]).reshape(self.states, -1)
        return (matrix, reset_matrix, matrix @ self.reward,
                reset_matrix @ self.reward, matrix @ marked_reward,
                matrix @ self.read_cost)

    def _batch_q(self, masses, schedule, budget):
        terminal = masses @ self.reward
        values = {"STOP0": terminal[:, 0], "STOP1": terminal[:, 1]}
        if not schedule:
            return values
        legal = self.legal_actions(schedule, budget)
        dt, rest = schedule[0], schedule[1:]
        matrix, reset_matrix, wait_reward, reset_reward, marked_reward, read_fee = self._operators(dt)
        mass = masses.sum(axis=1)
        time_fee = self.latency_price * dt * mass
        if not rest:
            if "WAIT" in legal:
                values["WAIT"] = (masses @ wait_reward).max(axis=1) - time_fee
            if "RESET" in legal:
                values["RESET"] = ((masses @ reset_reward).max(axis=1)
                                   - self.reset_cost * mass - time_fee)
            if "READ" in legal:
                rewards = (masses @ marked_reward).reshape(len(masses), self.E.shape[1], 2)
                values["READ"] = (rewards.max(axis=2).sum(axis=1) - time_fee
                                  - self.read_multiplier * (masses @ read_fee))
            return values
        propagated = masses @ matrix
        continuations, labels = [], []
        if "WAIT" in legal:
            continuations.append(propagated)
            labels.append("WAIT")
        if "RESET" in legal:
            continuations.append(masses @ reset_matrix)
            labels.append("RESET")
        if continuations:
            tails = self._batch_value(np.concatenate(continuations), rest, budget)
            for label, tail in zip(labels, np.split(tails, len(labels))):
                values[label] = tail - time_fee - (self.reset_cost * mass if label == "RESET" else 0.)
        if "READ" in legal:
            branches = (propagated[:, None, :] * self.E.T[None, :, :]).reshape(-1, self.states)
            tails = self._batch_value(branches, rest, budget-1).reshape(len(masses), self.E.shape[1])
            values["READ"] = (tails.sum(axis=1) - time_fee
                              - self.read_multiplier * (propagated @ self.read_cost))
        return values

    def _batch_value(self, masses, schedule, budget):
        return np.maximum.reduce(list(self._batch_q(masses, schedule, budget).values()))

    def _q_core(self, encoded, schedule, budget):
        if len(schedule) > 3 or self.E.shape[1] > 8:
            return super()._q_core(encoded, schedule, budget)
        if any(self._transition(dt).min() < 0 for dt in schedule):
            # The reference skips zero/negative observation masses. Do not
            # extend homogeneity to accepted negative floating-point roundoff.
            return super()._q_core(encoded, schedule, budget)
        belief = np.frombuffer(encoded, dtype=np.float64)
        values = self._batch_q(belief[None, :], schedule, budget)
        return tuple((a, float(values[a][0])) for a in self.legal_actions(schedule, budget))

    def choose(self, belief, schedule, budget=2):
        schedule = tuple(schedule)
        values = self.action_values(belief, schedule, budget)
        ordered = sorted(values.values(), reverse=True)
        # Include intermediate rewards/fees, not just a possibly cancelled Q.
        # This is a conservative fallback trigger, not an interval certificate.
        scale = (max(1., float(np.max(np.abs(self.reward))))
                 + len(schedule) * self.reset_cost
                 + min(budget, len(schedule)) * self.read_multiplier * self.read_cost.max()
                 + self.latency_price * sum(schedule))
        residual = max((float(np.max(np.abs(self._transition(dt).sum(1) - 1)))
                        for dt in schedule), default=0.)
        guard = scale * (128 * np.finfo(float).eps * self.states
                         * self.E.shape[1] * (len(schedule) + 1)
                         + 16 * len(schedule) * residual)
        if len(ordered) > 1 and ordered[0] - ordered[1] <= 1e-12 + guard:
            if self._reference is None:
                self._reference = CheckedBeliefDP(
                    self, reset_cost=self.reset_cost, latency_price=self.latency_price,
                    read_multiplier=self.read_multiplier)
                # A subclass may restrict legal actions, as in the no-reset arm.
                self._reference.legal_actions = self.legal_actions
            self.reference_fallbacks += 1
            return self._reference.choose(belief, schedule, budget)
        return choose_values(values)
