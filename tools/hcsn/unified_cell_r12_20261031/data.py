"""Causal data and a private finite-world execution owner.

Actors receive ten raw features: seven symbol indicators, an observation mask,
elapsed physical time, and a reset flag.  Latent states, labels, random tapes and
teacher posteriors are evaluator/training data and never actor observations.
The frozen R12 implementation addendum makes READ, RESET and WAIT exclusive.
"""

from dataclasses import dataclass

import numpy as np


TRUE_ACTIVE_EMISSIONS = np.array(
    [[.32, .08, .24, .06, .22, .08], [.08, .32, .06, .24, .08, .22]],
    dtype=np.float64,
)
TRAIN_INTERVALS = (.15, .45, 1.05)
OOD_INTERVALS = (.05, .75, 2.10)
INPUT_SIZE = 10
TIME_COST = .01
RESET_COST = .04


def _array(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float64)


def _sample(probabilities, uniform):
    """Inverse CDF, accepting only stochastic rows (up to roundoff)."""
    probabilities = np.asarray(probabilities, dtype=np.float64)
    if (probabilities.ndim != 1 or not np.isfinite(probabilities).all()
            or probabilities.min() < -1e-12
            or abs(probabilities.sum() - 1.) > 1e-9):
        raise ValueError("categorical sampling requires a stochastic row")
    cumulative = np.cumsum(probabilities)
    cumulative[-1] = 1.  # Only the stochastic-row roundoff accepted above.
    return int(np.searchsorted(cumulative, uniform, side="right"))


def encode_observation(token, dt, reset=False):
    """Encode only the information made available by one completed action."""
    if token < -1 or token > 6 or dt < 0 or not np.isfinite(dt):
        raise ValueError("invalid observed symbol or elapsed time")
    if reset and token != -1:
        raise ValueError("RESET cannot simultaneously reveal an observation")
    result = np.zeros(INPUT_SIZE, dtype=np.float64)
    if token >= 0:
        result[token] = 1.
        result[7] = 1.
    result[8] = dt
    result[9] = float(reset)
    return result


def generate_sequences(cell, seed, n, length=12, intervals=TRAIN_INTERVALS,
                       read_probability=.65, reset_probability=.10):
    """Generate common raw histories with exact causal finite-model teachers.

    Every row starts from ``cell.prior``.  READ advances by T(dt) and then emits;
    WAIT only advances; RESET first applies R and then T(dt), without emitting.
    The action draw is independent of the hidden state.  ``teacher[t]`` uses
    exactly inputs through t.  ``labels`` and ``states`` are privileged targets.
    """
    intervals = np.asarray(intervals, dtype=np.float64)
    if (n < 0 or length < 1 or intervals.ndim != 1 or len(intervals) == 0
            or not np.isfinite(intervals).all() or np.any(intervals < 0)
            or not 0 <= read_probability <= 1
            or not 0 <= reset_probability <= 1 - read_probability):
        raise ValueError("invalid sequence dimensions, intervals or action probabilities")
    prior, emissions, reset = map(_array, (cell.prior, cell.E, cell.R))
    transitions = [_array(cell.transition(float(t))) for t in intervals]
    rng = np.random.default_rng(seed)
    # Fixed-index independent draws avoid action-dependent RNG consumption.
    initial_u = rng.random(n)
    interval_index = rng.integers(len(intervals), size=(n, length))
    action_u = rng.random((n, length))
    reset_u = rng.random((n, length))
    transition_u = rng.random((n, length))
    observation_u = rng.random((n, length))
    observed = action_u < read_probability
    resets = ((action_u >= read_probability)
              & (action_u < read_probability + reset_probability))
    dt = intervals[interval_index]
    inputs = np.zeros((n, length, INPUT_SIZE), dtype=np.float64)
    tokens = np.full((n, length), -1, dtype=np.int64)
    states = np.empty((n, length), dtype=np.int64)
    teacher = np.empty((n, length, len(prior)), dtype=np.float64)
    for row in range(n):
        state = _sample(prior, initial_u[row])
        posterior = prior.copy()
        for step in range(length):
            if resets[row, step]:
                state = _sample(reset[state], reset_u[row, step])
                posterior = posterior @ reset
            transition = transitions[interval_index[row, step]]
            state = _sample(transition[state], transition_u[row, step])
            posterior = posterior @ transition
            if observed[row, step]:
                token = _sample(emissions[state], observation_u[row, step])
                tokens[row, step] = token
                posterior = posterior * emissions[:, token]
            evidence = posterior.sum()
            if not np.isfinite(evidence) or evidence <= 0:
                raise ArithmeticError("generated observation has zero model evidence")
            posterior = posterior / evidence
            states[row, step] = state
            teacher[row, step] = posterior
            inputs[row, step] = encode_observation(
                tokens[row, step], dt[row, step], resets[row, step])
    return {"inputs": inputs, "tokens": tokens, "dt": dt, "resets": resets,
            "teacher": teacher, "labels": states % 2, "states": states,
            "observed": observed}


@dataclass(frozen=True)
class EpisodeTape:
    """Evaluator-only indexed random draws, reused across paired policies."""

    initial_uniform: float
    dt: tuple
    reset_uniform: tuple
    transition_uniform: tuple
    observation_uniform: tuple


def generate_episode_tapes(seed, n, horizon=3, intervals=TRAIN_INTERVALS):
    """Generate the world randomness without consulting a policy or its outputs."""
    intervals = np.asarray(intervals, dtype=np.float64)
    if (n < 0 or horizon < 1 or intervals.ndim != 1 or len(intervals) == 0
            or not np.isfinite(intervals).all() or np.any(intervals < 0)):
        raise ValueError("invalid episode dimensions or intervals")
    rng = np.random.default_rng(seed)
    initial_u = rng.random(n)
    dt = intervals[rng.integers(len(intervals), size=(n, horizon))]
    reset_u, transition_u, observation_u = rng.random((3, n, horizon))
    return [EpisodeTape(float(initial_u[i]), tuple(dt[i]), tuple(reset_u[i]),
                        tuple(transition_u[i]), tuple(observation_u[i]))
            for i in range(n)]


class EpisodeOwner:
    """Own hidden state, unread symbols and the actual endpoint execution costs.

    Policy callbacks must receive ``next_dt`` and ``advance`` results only, not
    this owner or its random tape.  A final ``finish`` result is for evaluation,
    after the actor has irrevocably selected its answer and the episode closes.
    """

    def __init__(self, cell, tape, read_budget=2):
        if read_budget < 0:
            raise ValueError("read budget must be nonnegative")
        self._cell = cell
        self._tape = tape
        self._state = _sample(_array(cell.prior), tape.initial_uniform)
        self._step = 0
        self._closed = False
        self._remaining_reads = int(read_budget)
        self._cost = 0.
        self._elapsed = 0.
        self._counts = {"READ": 0, "WAIT": 0, "RESET": 0}

    @property
    def next_dt(self):
        if self._closed or self._step >= len(self._tape.dt):
            raise RuntimeError("no next interval in a finished episode")
        return float(self._tape.dt[self._step])

    @property
    def remaining_reads(self):
        return self._remaining_reads

    @property
    def remaining_steps(self):
        return len(self._tape.dt) - self._step

    @property
    def remaining_schedule(self):
        """Public experiment clock, independent of all latent states/symbols."""
        if self._closed:
            raise RuntimeError("episode already finished")
        return tuple(float(x) for x in self._tape.dt[self._step:])

    def advance(self, action):
        """Execute one action atomically; expose a token only for paid READ."""
        action = str(action).upper()
        if self._closed or self._step >= len(self._tape.dt):
            raise RuntimeError("episode is closed or its decision horizon is exhausted")
        if action not in self._counts:
            raise ValueError("continuing action must be READ, WAIT or RESET")
        if action == "READ" and self._remaining_reads == 0:
            raise ValueError("READ budget exhausted")
        index = self._step
        dt = float(self._tape.dt[index])
        state = self._state
        if action == "RESET":
            state = _sample(_array(self._cell.R)[state],
                            self._tape.reset_uniform[index])
        state = _sample(_array(self._cell.transition(dt))[state],
                        self._tape.transition_uniform[index])
        token = -1
        read_fee = 0.
        if action == "READ":
            token = _sample(_array(self._cell.E)[state],
                            self._tape.observation_uniform[index])
            read_fee = float(_array(self._cell.read_cost)[state])
            self._remaining_reads -= 1
        # READ cost is hidden-state-dependent.  Revealing it to the actor would
        # leak additional phase information, so it is evaluator-only bookkeeping.
        self._cost += TIME_COST * dt + read_fee + (RESET_COST if action == "RESET" else 0.)
        self._elapsed += dt
        self._counts[action] += 1
        self._state = state
        self._step += 1
        return {"input": encode_observation(token, dt, action == "RESET"),
                "token": token, "dt": dt, "reset": action == "RESET",
                "observed": action == "READ"}

    def finish(self, answer):
        """Score a committed answer at the actual state; this closes the owner."""
        if self._closed:
            raise RuntimeError("episode already finished")
        if answer not in (0, 1):
            raise ValueError("content answer must be zero or one")
        self._closed = True
        reward = float(_array(self._cell.reward)[self._state, int(answer)])
        return {"utility": reward - self._cost, "reward": reward,
                "cost": self._cost, "correct": int(answer == self._state % 2),
                "label": self._state % 2, "state": self._state,
                "elapsed": self._elapsed, "steps": self._step,
                "counts": self._counts.copy()}
