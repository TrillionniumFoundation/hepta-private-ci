"""Controlled latent dynamics with actual acquired text; no unread token generation."""

import numpy as np
import torch
from scipy.linalg import expm

from contract import DTYPE
from contract import PROTOCOL
from contract import bayes_step


def draw_rows(probabilities, uniforms):
    if len(probabilities) == 0:
        return np.empty(0, dtype=np.int64)
    cumulative = np.cumsum(probabilities, axis=-1)
    # The last endpoint absorbs only roundoff, not substantive missing mass.
    if np.max(np.abs(cumulative[..., -1] - 1)) > 1e-10:
        raise ValueError("Non-stochastic categorical probabilities")
    cumulative[..., -1] = 1
    return (uniforms[:, None] > cumulative).sum(axis=-1)


def sequences(seed, count, model, times, sensor, length=12):
    rng = np.random.default_rng(seed)
    dim = len(model["prior"])
    p = np.tile(model["prior"], (count, 1))
    hidden = draw_rows(p, rng.random(count))
    transitions = np.array([expm(model["Q"] * t) for t in times])
    indices = rng.integers(0, len(times), (count, length))
    observed = rng.random((count, length)) < PROTOCOL["training_observation_probability"]
    tokens = np.zeros((count, length), dtype=np.int64)
    labels = np.zeros_like(tokens)
    posterior = np.empty((count, length, dim))
    for t in range(length):
        for j in range(len(times)):
            rows = np.flatnonzero(indices[:, t] == j)
            hidden[rows] = draw_rows(transitions[j][hidden[rows]], rng.random(len(rows)))
        # No unrequested payload is generated: missing slots keep a dummy zero.
        rows = np.flatnonzero(observed[:, t])
        tokens[rows, t] = sensor.read(hidden[rows], rng.random(len(rows)))
        labels[:, t] = hidden // (dim // 2)
        for j in range(len(times)):
            rows = np.flatnonzero(indices[:, t] == j)
            p[rows] = bayes_step(p[rows], transitions[j], model["emission"],
                                 tokens[rows, t], observed[rows, t])
        posterior[:, t] = p
    return {"dt": np.asarray(times)[indices], "tokens": tokens,
            "observed": observed, "posterior": posterior, "labels": labels}


def tensors(data):
    return {key: torch.as_tensor(value, dtype=(torch.long if key in
            ("tokens", "labels") else torch.bool if key == "observed" else DTYPE))
            for key, value in data.items()}


class EvidenceWorld:
    """Counterfactual randomness is paired; payload generation occurs on READ."""

    def __init__(self, seed, count, model, times, sensor):
        self.sensor = sensor
        self.rng = np.random.default_rng(seed)
        self.model = model
        self.count = count
        self.times = np.asarray(times)
        self.transitions = [expm(model["Q"] * t) for t in times]
        self.initial_u = self.rng.random(count)
        self.transition_u = self.rng.random((3, count))
        self.observation_u = self.rng.random((3, count))
        # Decision episodes announce one interval for their whole short horizon.
        # Sequence evaluation above separately tests varying intervals in history.
        self.dt_indices = np.tile(self.rng.integers(0, len(times), count), (3, 1))
        self.reset()

    def reset(self):
        p = np.tile(self.model["prior"], (self.count, 1))
        self.hidden = draw_rows(p, self.initial_u)
        self.sensor.reset_counters()
        self.read_calls = 0
        self.recovery_read_calls = 0
        self.advance_calls = 0

    def advance(self, step, rows):
        self.advance_calls += len(rows)
        for j in range(len(self.times)):
            selected = rows[self.dt_indices[step, rows] == j]
            self.hidden[selected] = draw_rows(
                self.transitions[j][self.hidden[selected]],
                self.transition_u[step, selected],
            )

    def read(self, step, rows):
        self.read_calls += len(rows)
        tokens = self.sensor.read(self.hidden[rows], self.observation_u[step, rows])
        self.recovery_read_calls += int(np.sum(tokens == 6))
        return tokens

    def answer(self, rows, answers):
        states = self.hidden[rows]
        reward = self.model["answer_rewards"][states, answers]
        correct = states // (len(self.model["prior"]) // 2) == answers
        return reward, correct
