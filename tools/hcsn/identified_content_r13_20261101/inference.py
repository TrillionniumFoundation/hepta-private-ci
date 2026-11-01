"""Causal batch runtime: native and generic Bayes share the same finite model."""

import numpy as np
import torch

from contract import DTYPE, bayes_step
from native.adapter import PreparedModel
from training import load_fit


class Estimator:
    def __init__(self, name, count, shared, times, checkpoint=None):
        self.name, self.shared = name, shared
        self.p = np.tile(shared['prior'], (count, 1))
        # Every actor's value planner uses these same prepared transition matrices.
        self.prepared = PreparedModel(shared['Q'], mode='dense')
        self.transitions = [self.prepared.transition(dt) for dt in times]
        self.model = None
        if name in ('gru', 'continuous_diagonal_ssm'):
            self.model, _ = load_fit(checkpoint)
            self.hidden = self.model.initial(count)

    def update(self, rows, dt_index, dt, tokens, observed):
        if not len(rows):
            return
        if self.model is not None:
            with torch.no_grad():
                hidden, posterior = self.model.step(self.hidden[rows],
                    torch.full((len(rows),), dt, dtype=DTYPE), torch.tensor(tokens),
                    torch.tensor(observed))
                self.hidden[rows] = hidden
                self.p[rows] = posterior.numpy()
        elif self.name == 'hx_distribution':
            predicted = self.prepared.propagate(self.p[rows], dt)
            likelihood = np.where(observed[:, None], self.shared['emission'][:, tokens].T, 1.0)
            self.p[rows] = self.prepared.observe(predicted, likelihood)
        else:
            self.p[rows] = bayes_step(self.p[rows], self.transitions[dt_index],
                                     self.shared['emission'], tokens, observed)

    def close(self):
        self.prepared.close()


def sequence_predictions(name, data, shared, times, checkpoint=None):
    state = Estimator(name, len(data['dt']), shared, times, checkpoint)
    outputs = []
    for step in range(data['dt'].shape[1]):
        for j, dt in enumerate(times):
            rows = np.flatnonzero(data['dt'][:, step] == dt)
            state.update(rows, j, dt, data['tokens'][rows, step], data['observed'][rows, step])
        outputs.append(state.p.copy())
    cache = state.prepared.cache_info()
    state.close()
    return np.stack(outputs, axis=1), cache
