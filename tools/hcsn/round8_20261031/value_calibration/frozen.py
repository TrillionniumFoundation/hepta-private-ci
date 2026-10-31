"""Read-only NumPy execution of the frozen Round 7 finite cell and encoder.

This is a separately identified FP64 executor, not a fresh Torch execution or
a continuum diffusion solver. The upstream JSON remains byte-for-byte intact.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm
from scipy.special import expit, ndtr


class FrozenR7:
    def __init__(self, path):
        raw = Path(path).read_bytes()
        record = json.loads(raw)
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.configuration = record["configuration"]
        self.mode = self.configuration["mode"]
        if self.mode not in ("direct", "clocked", "first_passage"):
            raise ValueError("unsupported frozen execution contract")
        self.w = {k: np.asarray(v, dtype=np.float64) for k, v in record["state_dict"].items()}
        self.n = self.configuration["n_grid"]
        self.states = self.n + 2
        self.leak = 2 * expit(self.w["core.raw_leak"])
        self.sigma = .05 + .75 * expit(self.w["core.raw_diffusion"])
        self.boundary = .35 + 1.65 * expit(self.w["core.raw_boundary"])
        self.recovery = .05 + .90 * expit(self.w["core.raw_recovery"])
        self.grid = self.boundary * self.w["core.normalised_grid"]
        centers = .75 * np.tanh([self.w["core.raw_reset_plus"], self.w["core.raw_reset_minus"]])
        z = (self.w["core.normalised_edges"][None, 1:-1] - centers[:, None]) / .08
        cdf = ndtr(z)
        self.reset = np.column_stack((cdf[:, 0], np.diff(cdf, axis=1), ndtr(-z[:, -1])))
        first = np.r_[self.grid, self.reset @ self.grid]
        second = np.r_[self.grid ** 2, self.reset @ self.grid ** 2]
        self.basis = np.column_stack((first, second,
            np.arange(self.states) == self.n, np.arange(self.states) == self.n + 1))
        if self.mode == "direct":
            self.basis[:] = 0

    def encode(self, x):
        x = np.atleast_2d(x)
        a = np.tanh(x @ self.w["content.0.weight"].T + self.w["content.0.bias"])
        content = np.tanh(a @ self.w["content.2.weight"].T + self.w["content.2.bias"])
        drive = 1.5 * np.tanh(content @ self.w["drive.weight"].T + self.w["drive.bias"])
        return content, drive[:, 0]

    def inputs(self, public, content=None):
        public = np.atleast_2d(public)
        content = self.encode(public)[0] if content is None else content
        joined = np.column_stack((public, content))
        return np.concatenate((np.broadcast_to(joined[:, None],
            (len(public), self.states, joined.shape[-1])),
            np.broadcast_to(self.basis, (len(public), *self.basis.shape))), axis=-1)

    def old_q(self, public, content=None):
        joined = self.inputs(public, content)
        hidden = np.tanh(joined @ self.w["readout.0.weight"].T + self.w["readout.0.bias"])
        q = hidden @ self.w["readout.2.weight"].T + self.w["readout.2.bias"]
        return q.reshape(len(joined), self.states, 2, 4)[:, :, 1]

    def transition(self, drive):
        """One fixed-duration tick; old refractory mass releases only at tick end."""
        if self.mode == "direct":
            return np.eye(self.states), np.zeros(self.states)
        if self.mode == "first_passage":
            spacing = 2 * self.boundary / (self.n + 1)
            drift = drive - self.leak * self.grid
            diffusion = .5 * self.sigma ** 2 / spacing ** 2
            plus = diffusion + np.maximum(drift, 0) / spacing
            minus = diffusion + np.maximum(-drift, 0) / spacing
            generator = np.zeros((self.states, self.states))
            generator[:self.n] = (plus[:, None] * self.w["core.plus_generator_basis"]
                + minus[:, None] * self.w["core.minus_generator_basis"])
            matrix = expm(generator)
        else:
            mean = np.exp(-self.leak) * self.grid - np.expm1(-self.leak) / self.leak * drive
            sd = self.sigma * np.sqrt(-np.expm1(-2 * self.leak) / (2 * self.leak))
            z = (self.boundary * self.w["core.normalised_edges"][None] - mean[:, None]) / sd
            cdf = ndtr(z)
            matrix = np.zeros((self.states, self.states))
            matrix[:self.n] = np.column_stack((np.diff(cdf, axis=1), ndtr(-z[:, -1]), cdf[:, 0]))
        matrix[self.n:, :self.n] = self.recovery * self.reset
        matrix[self.n:, self.n:] = (1 - self.recovery) * np.eye(2)
        events = np.r_[matrix[:self.n, self.n:].sum(-1), 0., 0.]
        if matrix.min() < -1e-12 or np.max(np.abs(matrix.sum(-1) - 1)) > 1e-10:
            raise FloatingPointError("invalid finite transition")
        return matrix, events

    def kernels(self, public):
        _, drives = self.encode(public)
        matrices, rewards = zip(*(self.transition(d) for d in drives))
        return np.asarray(matrices), np.asarray(rewards)
