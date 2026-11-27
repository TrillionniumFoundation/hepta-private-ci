"""Finite, calibration-only risk-sensitive acquisition and output allocation.

The generator state is separate from bounded preference P. This is a finite
NDU-inspired special case, not a continuous Merton or neural FBSDE solution.
"""

from functools import lru_cache
from itertools import combinations_with_replacement, permutations
import time

import numpy as np

MODALITIES = ("text", "audio", "image", "video")
COSTS = (1, 2, 1, 4)
MISSING = 8
UNSEEN = -1


def portfolio_grid():
    rows = []
    for indices in combinations_with_replacement(range(8), 4):
        rows.append(np.bincount(indices, minlength=8) / 4.0)
    rows.append(np.full(8, 1 / 8))
    return np.asarray(rows, dtype=np.float64)


def certainty_equivalent(values, probabilities, gamma):
    """Entropic certainty equivalent, with stable log-sum-exp."""
    values = np.asarray(values, dtype=np.float64)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    if gamma == 0:
        return np.sum(values * probabilities, axis=-1)
    scaled = -gamma * values
    offset = np.max(scaled, axis=-1, keepdims=True)
    return -(np.log(np.sum(probabilities * np.exp(scaled - offset), axis=-1))
             + offset[..., 0]) / gamma


def next_preference(preference, observations, new_report):
    present = [x for x in observations if 0 <= x < MISSING]
    if new_report == MISSING:
        return preference
    conflict = any(x != new_report for x in present)
    return min(3, max(0, preference + (1 if conflict else -1)))


class CalibrationModel:
    """Full joint errors include common-mode failures; no test inputs here."""

    def __init__(self, truth, predictions, smoothing=32.0, independent=False):
        counts = np.full((8, 9, 9, 9, 9), smoothing / (8 * 9**4))
        np.add.at(counts, (truth, *predictions.T), 1.0)
        if independent:
            prior = counts.sum(axis=(1, 2, 3, 4))
            table = prior[:, None, None, None, None].copy()
            for j in range(4):
                axes = tuple(a for a in range(1, 5) if a != j + 1)
                conditional = counts.sum(axis=axes) / prior[:, None]
                shape = [8, 1, 1, 1, 1]
                shape[j + 1] = 9
                table = table * conditional.reshape(shape)
            counts = table
        self.joint = counts / counts.sum()

    @lru_cache(maxsize=None)
    def posterior(self, observations):
        index = (slice(None),) + tuple(slice(None) if x == UNSEEN else x
                                      for x in observations)
        selected = self.joint[index]
        posterior = selected.sum(axis=tuple(range(1, selected.ndim)))
        return posterior / posterior.sum()

    @lru_cache(maxsize=None)
    def predictive(self, observations, modality):
        masses = []
        for outcome in range(9):
            child = list(observations)
            child[modality] = outcome
            index = (slice(None),) + tuple(slice(None) if x == UNSEEN else x
                                          for x in child)
            masses.append(self.joint[index].sum())
        masses = np.asarray(masses)
        return masses / masses.sum()


class Planner:
    def __init__(self, model, loss_table, portfolios, gamma=2.0, mode="ndu",
                 penalty=0.025):
        self.model = model
        self.loss = loss_table  # [portfolio, possible truth], generated offline
        self.portfolios = portfolios
        self.gamma = gamma
        self.mode = mode
        self.penalty = penalty
        self.compile_seconds = 0.0

    def risk_aversion(self, preference):
        if self.mode == "neutral":
            return 0.0
        return self.gamma * (1 + preference) if self.mode in ("ndu", "myopic") else self.gamma

    @lru_cache(maxsize=None)
    def candidates(self, observations):
        present = sorted({x for x in observations if 0 <= x < 8})
        if not present:
            return np.asarray([len(self.portfolios) - 1])
        forbidden = [j for j in range(8) if j not in present]
        valid = np.all(self.portfolios[:, forbidden] == 0, axis=1)
        if self.mode == "single":
            valid &= np.max(self.portfolios, axis=1) == 1
        return np.flatnonzero(valid)

    @lru_cache(maxsize=None)
    def stop(self, observations, preference):
        candidates = self.candidates(observations)
        probabilities = self.model.posterior(observations)
        values = certainty_equivalent(-self.loss[candidates], probabilities,
                                       self.risk_aversion(preference))
        choice = int(np.argmax(values))
        return float(values[choice]), int(candidates[choice])

    @lru_cache(maxsize=None)
    def solve(self, observations, budget, preference=0):
        best_value, portfolio = self.stop(observations, preference)
        best_action = -1
        for modality in range(1, 4):
            if observations[modality] != UNSEEN or COSTS[modality] > budget:
                continue
            child_values = []
            for outcome in range(9):
                child = list(observations)
                child[modality] = outcome
                new_p = next_preference(preference, observations, outcome)
                if self.mode == "myopic":
                    value = self.stop(tuple(child), new_p)[0]
                else:
                    value = self.solve(tuple(child), budget - COSTS[modality], new_p)[0]
                child_values.append(value)
            value = float(certainty_equivalent(child_values,
                          self.model.predictive(observations, modality),
                          self.risk_aversion(preference))) - self.penalty * COSTS[modality]
            if value > best_value + 1e-12:
                best_value, best_action = value, modality
        return best_value, best_action, portfolio

    def compile(self, budgets):
        started = time.perf_counter()
        visited = set()

        def visit(observations, budget, preference):
            key = observations, budget, preference
            if key in visited:
                return
            visited.add(key)
            self.solve(observations, budget, preference)
            if self.mode != "myopic":
                return
            for modality in range(1, 4):
                if observations[modality] != UNSEEN or COSTS[modality] > budget:
                    continue
                for outcome in range(9):
                    child = list(observations)
                    child[modality] = outcome
                    visit(tuple(child), budget - COSTS[modality],
                          next_preference(preference, observations, outcome))

        for budget in budgets:
            for first in range(9):
                visit((first, UNSEEN, UNSEEN, UNSEEN), budget, 0)
        self.compile_seconds += time.perf_counter() - started


def fixed_policies(budget):
    """Static order/weights; validation chooses from the same quarter grid."""
    for length in range(4):
        for order in permutations(range(1, 4), length):
            if sum(COSTS[j] for j in order) > budget:
                continue
            seen = (0,) + order
            for allocation in combinations_with_replacement(range(len(seen)), 4):
                weights = np.bincount(allocation, minlength=len(seen)) / 4.0
                # Repeated orders with identical acquired subsets add no baseline strength.
                if tuple(sorted(order)) != order:
                    continue
                yield {"order": list(order), "modalities": list(seen), "weights": weights.tolist()}


def fixed_portfolio(observations, specification, grid):
    q = np.zeros(8)
    for modality, weight in zip(specification["modalities"], specification["weights"]):
        report = observations[modality]
        if 0 <= report < 8:
            q[report] += weight
    if q.sum() == 0:
        present = [observations[j] for j in specification["modalities"]
                   if 0 <= observations[j] < 8]
        if present:
            # If every positive-weight modality is missing, preserve the
            # registered support constraint using the other acquired reports.
            q = np.bincount(present, minlength=8).astype(np.float64)
            q /= q.sum()
        else:
            q[:] = 1 / 8
    else:
        q /= q.sum()
    # Missingness can produce thirds; projection is explicit and identical at val/test.
    return int(np.argmin(np.square(grid - q).sum(axis=1)))
