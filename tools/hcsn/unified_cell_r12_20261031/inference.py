"""Causal runtime adapters; the HX candidate actually calls the Rust operator."""

import numpy as np
from scipy.linalg import expm
import torch

from contract import DTYPE
from contract import bayes_step
from native.adapter import NativeOperator
from training import load_fit


class Estimator:
    def __init__(self, name, count, shared, times, checkpoint=None):
        self.name, self.shared = name, shared
        self.p = np.tile(shared["prior"], (count, 1))
        self.transitions = [expm(shared["Q"] * t) for t in times]
        self.native = NativeOperator() if name == "hx_distribution" else None
        self.model = None
        if name in ("gru", "continuous_diagonal_ssm"):
            self.model, _ = load_fit(checkpoint)
            self.hidden = self.model.initial(count)

    def update(self, rows, dt_index, dt, tokens, observed):
        if self.model is not None:
            with torch.no_grad():
                hidden, posterior = self.model.step(
                    self.hidden[rows], torch.full((len(rows),), dt, dtype=DTYPE),
                    torch.tensor(tokens), torch.tensor(observed),
                )
                self.hidden[rows] = hidden
                self.p[rows] = posterior.numpy()
            return
        if self.native is None:
            self.p[rows] = bayes_step(self.p[rows], self.transitions[dt_index],
                                     self.shared["emission"], tokens, observed)
            return
        for j, row in enumerate(rows):
            state = self.native.propagate(self.shared["Q"], self.p[row], dt)
            if observed[j]:
                state = self.native.observe(state, self.shared["emission"][:, tokens[j]])
            self.p[row] = state


def sequence_predictions(name, data, shared, times, checkpoint=None):
    if name in ("gru", "continuous_diagonal_ssm", "hx_distribution"):
        model, _ = load_fit(checkpoint)
        with torch.no_grad():
            return model(torch.tensor(data["dt"], dtype=DTYPE),
                         torch.tensor(data["tokens"]),
                         torch.tensor(data["observed"])).numpy()
    state = Estimator(name, len(data["dt"]), shared, times)
    outputs = []
    for step in range(data["dt"].shape[1]):
        for j, dt in enumerate(times):
            rows = np.flatnonzero(data["dt"][:, step] == dt)
            if len(rows):
                state.update(rows, j, dt, data["tokens"][rows, step],
                             data["observed"][rows, step])
        outputs.append(state.p.copy())
    return np.stack(outputs, axis=1)
