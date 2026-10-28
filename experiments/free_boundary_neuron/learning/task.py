"""Visible-only sequential evidence task and finite-grid Bellman references.

An observation is purchased before it is seen. All complete evidence streams
are generated independently of the policy, so early stopping cannot change
later exogenous random numbers. Truth is used only by training/evaluation.
"""

from dataclasses import dataclass
import hashlib
import itertools
import time

import numpy as np
from scipy.special import expit, logit


ABSTAIN_REWARD = 0.05
TERMINAL_BOUND = float(logit((1 + ABSTAIN_REWARD) / 2))
SPLITS = {"train": 11, "validation": 23, "id_test": 37, "ood_test": 53, "smoke": 997}


@dataclass
class Episodes:
    """Separate truth from the features that a policy is permitted to see."""

    observations: np.ndarray
    truth: np.ndarray
    reliability: np.ndarray
    cost: np.ndarray
    deadline: np.ndarray
    features: np.ndarray
    boundary_features: np.ndarray
    posterior: np.ndarray
    digest: str

    def take(self, indices):
        return Episodes(
            *(
                getattr(self, name)[indices]
                for name in (
                    "observations",
                    "truth",
                    "reliability",
                    "cost",
                    "deadline",
                    "features",
                    "boundary_features",
                    "posterior",
                )
            ),
            self.digest,
        )


def make_episodes(seed, split, count, *, ood=False):
    """Episode-local streams keyed by seed/split/episode, not policy actions."""
    if split not in SPLITS or count < 1:
        raise ValueError("known split and positive episode count required")
    contexts = list(
        itertools.product(
            [0.55, 0.68] if ood else [0.6, 0.75],
            [0.025, 0.06] if ood else [0.01, 0.04],
            [10, 14] if ood else [8, 16],
        )
    )
    truth, obs, rows = [], [], []
    for episode in range(count):
        rng = np.random.default_rng(
            np.random.SeedSequence([seed, SPLITS[split], episode])
        )
        reliability, cost, deadline = contexts[episode % len(contexts)]
        label = 2 * rng.integers(2) - 1
        truth.append(label)
        obs.append(np.where(rng.random(16) < reliability, label, -label))
        rows.append((reliability, cost, deadline))
    observations, truth = np.asarray(obs, float), np.asarray(truth, float)
    rows = np.asarray(rows, float)
    reliability, cost, deadline = rows.T
    deadline = deadline.astype(int)
    n, horizon = observations.shape
    event = np.broadcast_to(np.arange(1, horizon + 1), (n, horizon))
    fraction = event / deadline[:, None]
    r = np.broadcast_to(reliability[:, None], (n, horizon))
    c = np.broadcast_to(cost[:, None], (n, horizon))
    h = np.broadcast_to(deadline[:, None] / 16, (n, horizon))
    likelihood_increment = observations * logit(r)
    features = np.stack(
        (observations, likelihood_increment, (r - 0.65) * 4, c / 0.04, h, fraction),
        axis=-1,
    )
    boundary_features = np.stack(
        (
            np.ones_like(r),
            c / 0.04,
            (r - 0.65) * 4,
            1 - fraction,
            h,
            fraction * c / 0.04,
        ),
        axis=-1,
    )
    posterior = expit(np.cumsum(likelihood_increment, axis=1))
    digest = hashlib.sha256()
    for array in (observations, truth, reliability, cost, deadline):
        digest.update(np.ascontiguousarray(array).tobytes())
    return Episodes(
        observations,
        truth,
        reliability,
        cost,
        deadline,
        features,
        boundary_features,
        posterior,
        digest.hexdigest(),
    )


class BellmanReference:
    """Model-informed, discrete-time/grid oracle; no smooth-fit claim.

    Every method has the same observable reliability, cost and deadline. This
    reference additionally uses the known observation model computationally.
    The raw-belief version is reported separately from the learned SNN.
    """

    def __init__(self, grid_points=1001):
        if grid_points < 5 or grid_points % 2 != 1:
            raise ValueError("an odd belief grid with at least five points is required")
        self.grid = np.linspace(0, 1, grid_points)
        self.profiles = {}
        self.build_seconds = 0.0

    def profile(self, reliability, cost, deadline):
        key = (float(reliability), float(cost), int(deadline))
        if key in self.profiles:
            return self.profiles[key]
        started = time.perf_counter()
        p, r, horizon = self.grid, key[0], key[2]
        observation_positive = r * p + (1 - r) * (1 - p)
        p_plus = r * p / observation_positive
        p_minus = (1 - r) * p / (1 - observation_positive)
        immediate = np.abs(2 * p - 1)
        value = np.maximum(immediate, ABSTAIN_REWARD)
        choose, abstain = np.empty(horizon), np.empty(horizon)
        choose[-1], abstain[-1] = TERMINAL_BOUND, TERMINAL_BOUND
        for t in range(horizon - 2, -1, -1):
            continuation = -cost + observation_positive * np.interp(p_plus, p, value)
            continuation += (1 - observation_positive) * np.interp(p_minus, p, value)
            # Explicitly verify connected symmetric action regions rather than
            # silently forcing an arbitrary Bellman policy into two thresholds.
            right = p >= 0.5
            stop = (immediate >= continuation) & (immediate >= ABSTAIN_REWARD)
            neutral = (ABSTAIN_REWARD >= continuation) & (ABSTAIN_REWARD > immediate)
            stop_right, neutral_right = stop[right], neutral[right]
            if np.any(np.diff(stop_right.astype(int)) < 0):
                raise RuntimeError("nonmonotone decision region needs a richer policy")
            if np.any(np.diff(neutral_right.astype(int)) > 0):
                raise RuntimeError("noncentral abstention region needs a richer policy")
            p_choice = p[right][np.flatnonzero(stop_right)[0]]
            choose[t] = logit(np.clip(p_choice, 1e-9, 1 - 1e-9))
            abstain[t] = (
                logit(p[right][np.flatnonzero(neutral_right)[-1]])
                if neutral_right.any()
                else -1.0
            )
            next_value = np.maximum.reduce(
                (immediate, np.full_like(p, ABSTAIN_REWARD), continuation)
            )
            value = next_value
        result = {
            "choice": choose,
            "abstain": abstain,
            "value_after_first": value,
            "grid_points": len(p),
        }
        self.profiles[key] = result
        self.build_seconds += time.perf_counter() - started
        return result

    def boundaries(self, episodes):
        n, horizon = episodes.observations.shape
        choice = np.full((n, horizon), TERMINAL_BOUND)
        abstain = choice.copy()
        for index, (r, c, h) in enumerate(
            zip(episodes.reliability, episodes.cost, episodes.deadline)
        ):
            profile = self.profile(r, c, h)
            choice[index, :h] = profile["choice"]
            abstain[index, :h] = profile["abstain"]
        return choice, abstain


def action_arrays(voltage, choice, abstain, deadlines, *, smooth=None):
    """Three mutually exclusive hard terminal actions plus the wait action."""
    activation = (lambda z: (z > 0).astype(float)) if smooth is None else smooth
    positive, negative = activation(voltage - choice), activation(-voltage - choice)
    neutral = activation(abstain - np.abs(voltage))
    final = np.arange(voltage.shape[1])[None, :] == deadlines[:, None] - 1
    positive = np.where(final, activation(voltage - TERMINAL_BOUND), positive)
    negative = np.where(final, activation(-voltage - TERMINAL_BOUND), negative)
    neutral = np.where(final, 1 - positive - negative, neutral)
    return positive, negative, neutral, final


def evaluate(voltage, choice, abstain, episodes, *, spikes=None, cells=0):
    """Count abstention, all purchased observations, and complete serial time."""
    started = time.perf_counter()
    if not all(np.all(np.isfinite(array)) for array in (voltage, choice, abstain)):
        raise FloatingPointError(
            "invalid policy values must not become silent abstentions"
        )
    positive, negative, neutral, _ = action_arrays(
        voltage, choice, abstain, episodes.deadline
    )
    terminal = positive + negative + neutral
    if not np.all((terminal == 0) | (terminal == 1)):
        raise RuntimeError("hard action probabilities are not exclusive")
    first = np.argmax(terminal, axis=1)
    row = np.arange(len(first))
    decision = positive[row, first] - negative[row, first]
    covered = decision != 0
    correct = decision == episodes.truth
    observations = first + 1
    reward = np.where(covered, decision * episodes.truth, ABSTAIN_REWARD)
    utility = reward - observations * episodes.cost
    duration = observations + 0.2 + 0.2
    probability = expit(voltage[row, first])
    target = (episodes.truth + 1) / 2
    valid = np.arange(voltage.shape[1])[None, :] <= first[:, None]
    count = len(first)
    result = {
        "episodes": count,
        "mean_utility": float(np.mean(utility)),
        "utility_sum": float(np.sum(utility)),
        "utility_squared_sum": float(utility @ utility),
        "accuracy_all": float(np.mean(correct)),
        "conditional_accuracy": float(np.mean(correct[covered]))
        if covered.any()
        else None,
        "coverage": float(np.mean(covered)),
        "abstentions": int(np.sum(~covered)),
        "brier_at_decision": float(np.mean((probability - target) ** 2)),
        "log_loss_at_decision": float(
            np.mean(np.logaddexp(0, voltage[row, first]) - target * voltage[row, first])
        ),
        "mean_observations": float(np.mean(observations)),
        "observations": int(np.sum(observations)),
        "serial_duration": float(np.sum(duration)),
        "utility_per_serial_second": float(np.sum(utility) / np.sum(duration)),
        "active_cell_updates_until_decision": int(cells * np.sum(observations)),
        "actual_dense_neural_cell_updates": int(cells * voltage.size),
        "active_spikes_until_decision": int(np.sum(np.asarray(spikes) * valid))
        if spikes is not None
        else 0,
        "actual_dense_spikes": int(np.sum(spikes)) if spikes is not None else 0,
        "applied_decision_count": count,
        "fallback_count": 0,
        "action_evaluation_seconds": time.perf_counter() - started,
    }
    return result


def myopic_boundaries(episodes, grid_points=1001):
    """Same-model one-observation value-of-computation reference."""
    p = np.linspace(0.5, 1 - 1e-9, grid_points)
    choice, abstain = (
        np.zeros_like(episodes.observations),
        np.zeros_like(episodes.observations),
    )
    cache = {}
    for i, (r, cost) in enumerate(zip(episodes.reliability, episodes.cost)):
        key = (r, cost)
        if key not in cache:
            prob = r * p + (1 - r) * (1 - p)
            pp, pm = r * p / prob, (1 - r) * p / (1 - prob)
            stop = np.maximum(2 * p - 1, ABSTAIN_REWARD)
            future = prob * np.maximum(np.abs(2 * pp - 1), ABSTAIN_REWARD)
            future += (1 - prob) * np.maximum(np.abs(2 * pm - 1), ABSTAIN_REWARD)
            decide = (2 * p - 1 >= ABSTAIN_REWARD) & (stop >= future - cost)
            abst = (ABSTAIN_REWARD > 2 * p - 1) & (stop >= future - cost)
            cache[key] = (
                logit(p[np.flatnonzero(decide)[0]]),
                logit(p[np.flatnonzero(abst)[-1]]) if abst.any() else -1.0,
            )
        choice[i], abstain[i] = cache[key]
    return choice, abstain
