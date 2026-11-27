"""Finite-deadline regenerative task values, with actual future tasks.

This module is deliberately independent of the neural pressure oracle.  A task
starts with no observation.  READ costs ``price`` now and consumes one clock
tick.  FIRE scores the current prediction, ends that task, freezes the clock
for ``refractory`` ticks, and can start the next independent task.  The queue
contains at most ``tasks`` tasks, so no zero-time repeated reward is possible.

For an exact observation model this is a finite Bellman oracle.  Fitting a
coarsened Markov observation model to neural traces gives an approximation;
the solver does not turn that approximation into a theorem about the network.
"""

from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np


@dataclass
class ObservationModel:
    """Reward/transition law after each positive observation prefix.

    reward[k,z] is expected *actual* classification correctness upon firing.
    transition[k,z,z2] is the next-observation law, for 1 <= k < max_reads.
    initial[z] is the first-observation law for a fresh independent task.
    valid[k,z] is a structural reachability mask, not a fitted censoring rule.
    """

    reward: np.ndarray
    transition: np.ndarray
    initial: np.ndarray
    valid: np.ndarray

    @property
    def max_reads(self):
        return self.reward.shape[0] - 1

    @property
    def states(self):
        return self.reward.shape[1]

    def validate(self):
        k, s = self.reward.shape
        if k < 2 or s < 1:
            raise ValueError("At least one readable observation and state are required")
        if self.transition.shape != (k, s, s) or self.valid.shape != (k, s):
            raise ValueError("Observation law shapes differ")
        if self.initial.shape != (s,):
            raise ValueError("Initial law shape differs")
        if not np.isfinite(self.initial).all() or np.any(self.initial < 0):
            raise ValueError("Invalid first-observation law")
        if not np.isclose(self.initial.sum(), 1.0, atol=2e-14, rtol=0):
            raise ValueError("First-observation law must have total mass one")
        if np.any(self.initial[~self.valid[1]] != 0):
            raise ValueError("First observation enters an invalid state")
        r = self.reward[self.valid]
        if not np.isfinite(r).all() or np.any((r < 0) | (r > 1)):
            raise ValueError("Firing rewards must be expected correctness in [0,1]")
        for prefix in range(1, self.max_reads):
            p = self.transition[prefix, self.valid[prefix]]
            if not np.isfinite(p).all() or np.any(p < 0):
                raise ValueError("Invalid next-observation probabilities")
            if not np.allclose(p.sum(-1), 1, atol=2e-14, rtol=0):
                raise ValueError("Transition rows must sum to one")
            if np.any(p[:, ~self.valid[prefix + 1]] != 0):
                raise ValueError("Transition enters an invalid state")


@dataclass
class TaskValues:
    """Arrays indexed by [tasks_remaining, ticks_remaining, prefix, state]."""

    value: np.ndarray
    fire: np.ndarray
    read: np.ndarray
    future_after_reset: np.ndarray
    fresh: np.ndarray
    discounted_correct: np.ndarray
    discounted_reads: np.ndarray
    fresh_correct: np.ndarray
    fresh_reads: np.ndarray
    price: float
    discount: float
    refractory: int

    def decision(self, tasks, ticks, prefix, state):
        if prefix < 1:
            return "read" if self.fresh[tasks, ticks] > 0 else "decline"
        fire = self.fire[tasks, ticks, prefix, state]
        read = self.read[tasks, ticks, prefix, state]
        if not math.isfinite(float(fire)):
            raise ValueError("Unreachable or invalid decision state")
        return "read" if read > fire else "fire"


def solve(model, *, horizon, tasks, price, refractory=2, discount=1.0):
    """Solve the declared finite problem, including reset continuation.

    FIRE has no additional clock charge; its positive-prefix precondition and
    finite task queue prevent reward cycling.  Ties fire (or decline a fresh
    task) to avoid gratuitous reads.  Refractory time consumes deadline but is
    not billed as an observation.  A fresh task may be declined for zero value.
    """
    model.validate()
    if (isinstance(horizon, bool) or int(horizon) != horizon or horizon < 0
            or isinstance(tasks, bool) or int(tasks) != tasks or tasks < 1
            or isinstance(refractory, bool) or int(refractory) != refractory
            or refractory < 0):
        raise ValueError("Deadline, queue and refractory durations must be nonnegative integers")
    if not math.isfinite(price) or price < 0 or not (0 < discount <= 1):
        raise ValueError("Invalid price or per-tick discount")
    horizon, tasks, refractory = map(int, (horizon, tasks, refractory))
    shape = (tasks + 1, horizon + 1, model.max_reads + 1, model.states)
    value = np.full(shape, np.nan, dtype=np.float64)
    fire = np.full(shape, np.nan, dtype=np.float64)
    read = np.full(shape, -np.inf, dtype=np.float64)
    correct = np.full(shape, np.nan, dtype=np.float64)
    reads = np.full(shape, np.nan, dtype=np.float64)
    fresh = np.zeros((tasks + 1, horizon + 1), dtype=np.float64)
    fresh_correct = np.zeros_like(fresh)
    fresh_reads = np.zeros_like(fresh)
    future = np.zeros_like(fresh)
    initial_index = np.flatnonzero(model.valid[1])
    initial_weight = model.initial[initial_index]
    for remaining_tasks in range(1, tasks + 1):
        for ticks in range(horizon + 1):
            after = max(0, ticks - refractory)
            permitted = remaining_tasks > 1 and ticks >= refractory
            future_value = (discount ** refractory * fresh[remaining_tasks - 1, after]
                            if permitted else 0.0)
            future_correct = (discount ** refractory * fresh_correct[remaining_tasks - 1, after]
                              if permitted else 0.0)
            future_reads = (discount ** refractory * fresh_reads[remaining_tasks - 1, after]
                            if permitted else 0.0)
            future[remaining_tasks, ticks] = future_value
            for prefix in range(1, model.max_reads + 1):
                index = np.flatnonzero(model.valid[prefix])
                qfire = model.reward[prefix, index] + future_value
                qcorrect = model.reward[prefix, index] + future_correct
                qreads = np.full(len(index), future_reads)
                qread = np.full(len(index), -np.inf)
                if ticks > 0 and prefix < model.max_reads:
                    nxt = np.flatnonzero(model.valid[prefix + 1])
                    p = model.transition[prefix][np.ix_(index, nxt)]
                    qread = -price + discount * (
                        p @ value[remaining_tasks, ticks - 1, prefix + 1, nxt])
                    choose_read = qread > qfire
                    read_correct = discount * (
                        p @ correct[remaining_tasks, ticks - 1, prefix + 1, nxt])
                    read_reads = 1 + discount * (
                        p @ reads[remaining_tasks, ticks - 1, prefix + 1, nxt])
                    qcorrect = np.where(choose_read, read_correct, qcorrect)
                    qreads = np.where(choose_read, read_reads, qreads)
                fire[remaining_tasks, ticks, prefix, index] = qfire
                read[remaining_tasks, ticks, prefix, index] = qread
                value[remaining_tasks, ticks, prefix, index] = np.maximum(qfire, qread)
                correct[remaining_tasks, ticks, prefix, index] = qcorrect
                reads[remaining_tasks, ticks, prefix, index] = qreads
            if ticks:
                trial = -price + discount * np.dot(
                    initial_weight, value[remaining_tasks, ticks - 1, 1, initial_index])
                if trial > 0:
                    fresh[remaining_tasks, ticks] = trial
                    fresh_correct[remaining_tasks, ticks] = discount * np.dot(
                        initial_weight, correct[remaining_tasks, ticks - 1, 1, initial_index])
                    fresh_reads[remaining_tasks, ticks] = 1 + discount * np.dot(
                        initial_weight, reads[remaining_tasks, ticks - 1, 1, initial_index])
    return TaskValues(value, fire, read, future, fresh, correct, reads,
                      fresh_correct, fresh_reads, float(price), float(discount), refractory)


def binary_observation_model(max_reads=8, reliability=0.72):
    """Exact iid binary observations of a fresh Bernoulli(1/2) task label."""
    if max_reads < 1 or not 0.5 < reliability < 1:
        raise ValueError("Need a finite observation horizon and informative noisy sensor")
    states = 2 * max_reads + 1
    reward = np.zeros((max_reads + 1, states), dtype=np.float64)
    transition = np.zeros((max_reads + 1, states, states), dtype=np.float64)
    valid = np.zeros_like(reward, dtype=bool)
    initial = np.zeros(states)
    initial[max_reads - 1] = initial[max_reads + 1] = 0.5
    log_ratio = math.log(reliability / (1 - reliability))
    for prefix in range(1, max_reads + 1):
        for imbalance in range(-prefix, prefix + 1, 2):
            state = max_reads + imbalance
            posterior = 1.0 / (1.0 + math.exp(-imbalance * log_ratio))
            reward[prefix, state] = max(posterior, 1 - posterior)
            valid[prefix, state] = True
            if prefix < max_reads:
                next_one = posterior * reliability + (1 - posterior) * (1 - reliability)
                transition[prefix, state, state + 1] = next_one
                transition[prefix, state, state - 1] = 1 - next_one
    result = ObservationModel(reward, transition, initial, valid)
    result.validate()
    return result


def literal_binary_reference(*, horizon, tasks, price, refractory=2,
                             discount=1.0, max_reads=8, reliability=0.72):
    """Independent literal-history tree, using likelihood products.

    Intended for small horizons.  It does not call the tabular solver, use its
    state arrays, or reuse its log-odds representation.
    """
    @lru_cache(None)
    def visit(history, ticks, count):
        if not count:
            return 0.0
        if not history:
            if not ticks:
                return 0.0
            continuation = -price + discount * 0.5 * (
                visit((0,), ticks - 1, count) + visit((1,), ticks - 1, count))
            return max(0.0, continuation)
        likelihood0 = math.prod(reliability if bit == 0 else 1 - reliability for bit in history)
        likelihood1 = math.prod(reliability if bit == 1 else 1 - reliability for bit in history)
        posterior = likelihood1 / (likelihood0 + likelihood1)
        stop = max(posterior, 1 - posterior)
        if count > 1 and ticks >= refractory:
            stop += discount ** refractory * visit((), ticks - refractory, count - 1)
        if not ticks or len(history) == max_reads:
            return stop
        next_one = posterior * reliability + (1 - posterior) * (1 - reliability)
        continuation = -price + discount * (
            next_one * visit(history + (1,), ticks - 1, count)
            + (1 - next_one) * visit(history + (0,), ticks - 1, count))
        return max(stop, continuation)
    return visit((), int(horizon), int(tasks))


def binary_rollouts(solution, *, samples=20000, seed=0, reliability=0.72):
    """Independent actual-label rollouts, charging every read and scoring FIRE.

    Returned arrays are raw per-stream outcomes, including the later tasks.
    The hidden labels are used only to generate sensor bits and score FIRE.
    They are never consulted by the decision rule.
    """
    rng = np.random.default_rng(seed)
    tasks = solution.fresh.shape[0] - 1
    horizon = solution.fresh.shape[1] - 1
    max_reads = solution.value.shape[2] - 1
    remaining = np.full(samples, tasks, dtype=np.int64)
    ticks = np.full(samples, horizon, dtype=np.int64)
    prefix = np.zeros(samples, dtype=np.int64)
    imbalance = np.zeros(samples, dtype=np.int64)
    label = rng.integers(0, 2, samples)
    active = np.ones(samples, dtype=bool)
    utility = np.zeros(samples)
    discounted_correct = np.zeros(samples)
    discounted_reads = np.zeros(samples)
    actual_reads = np.zeros(samples, dtype=np.int64)
    firings = np.zeros(samples, dtype=np.int64)
    later_correct = np.zeros(samples, dtype=np.int64)
    for _ in range(tasks * (max_reads + 2) + 1):
        if not active.any():
            break
        fresh = active & (prefix == 0)
        decline = fresh & (solution.fresh[remaining, ticks] <= 0)
        active[decline] = False
        reading = active & (prefix == 0)
        existing = np.flatnonzero(active & (prefix > 0))
        if len(existing):
            ix = (remaining[existing], ticks[existing], prefix[existing],
                  max_reads + imbalance[existing])
            continuing = solution.read[ix] > solution.fire[ix]
            reading[existing[continuing]] = True
            firing = existing[~continuing]
            if len(firing):
                correct = ((imbalance[firing] >= 0).astype(np.int64) == label[firing])
                factor = solution.discount ** (horizon - ticks[firing])
                utility[firing] += factor * correct
                discounted_correct[firing] += factor * correct
                later_correct[firing] += correct * (firings[firing] > 0)
                firings[firing] += 1
                remaining[firing] -= 1
                restart = firing[(remaining[firing] > 0)
                                 & (ticks[firing] > solution.refractory)]
                active[firing] = False
                if len(restart):
                    active[restart] = True
                    ticks[restart] -= solution.refractory
                    prefix[restart] = 0
                    imbalance[restart] = 0
                    label[restart] = rng.integers(0, 2, len(restart))
        indexes = np.flatnonzero(reading)
        if len(indexes):
            if np.any(ticks[indexes] <= 0):
                raise AssertionError("Attempted a read past the deadline")
            factor = solution.discount ** (horizon - ticks[indexes])
            utility[indexes] -= solution.price * factor
            discounted_reads[indexes] += factor
            actual_reads[indexes] += 1
            probability = np.where(label[indexes] == 1, reliability, 1 - reliability)
            observation = rng.random(len(indexes)) < probability
            imbalance[indexes] += 2 * observation.astype(np.int64) - 1
            prefix[indexes] += 1
            ticks[indexes] -= 1
    if active.any():
        raise AssertionError("Finite task queue did not terminate")
    if not np.allclose(utility, discounted_correct - solution.price * discounted_reads,
                       atol=3e-14, rtol=0):
        raise AssertionError("Recorded reward ledger differs from actual scored events")
    return {"utility": utility, "discounted_correct": discounted_correct,
            "discounted_reads": discounted_reads, "actual_reads": actual_reads,
            "firings": firings, "later_task_correct": later_correct}
