"""Opt-in full-BPTT rematerialization of the unchanged population-flux encoder.

This changes activation storage and recomputation, not the grid, time step,
state transition, training batch, or gradient horizon. It is a separate
candidate until forward/gradient/optimizer parity and actual CUDA cost pass.
"""

import math

import torch
from torch.utils.checkpoint import checkpoint

from .baselines import PopulationFluxEncoder
from .population_torch import TensorPopulationState


class RematerializedPopulationFluxEncoder(PopulationFluxEncoder):
    """Keep segment-boundary tensors and recompute internal activations."""

    def __init__(self, input_size, hidden_size, *, dt=0.1, recovery=True,
                 segment_steps=1):
        if type(segment_steps) is not int or segment_steps <= 0:
            raise ValueError("segment_steps must be a positive integer")
        super().__init__(input_size, hidden_size, dt=dt, recovery=recovery)
        self.segment_steps = segment_steps

    def _advance(self, active, refractory, recovery, escaped, trace, inputs, dt):
        # All evolving state is explicit: backward must replay the same values
        # even though subsequent segments have already executed.
        state = TensorPopulationState(active, refractory, recovery, escaped)
        outputs = []
        for value in inputs.unbind(1):
            drive = 6*torch.sigmoid(self.input(value)+self.recurrent(trace))
            step = self.population(state, drive=drive)
            state = step.state
            trace = math.exp(-dt/0.5)*trace+(1-math.exp(-dt/0.5))*step.rate
            outputs.append(trace)
        return (state.active, state.refractory, state.recovery, state.escaped,
                trace, torch.stack(outputs, dim=1))

    def forward(self, x, dt=0.1):
        if not math.isclose(dt, self.population.config.dt, rel_tol=0, abs_tol=1e-12):
            raise ValueError("forward dt must equal the configured population step")
        state = self.population.initial_state((x.shape[0], self.hidden_size))
        trace = x.new_zeros(x.shape[0], self.hidden_size)
        outputs = []
        for start in range(0, x.shape[1], self.segment_steps):
            arguments = (state.active, state.refractory, state.recovery,
                         state.escaped, trace,
                         x[:, start:start+self.segment_steps], dt)
            if torch.is_grad_enabled():
                values = checkpoint(self._advance, *arguments, use_reentrant=False,
                                    preserve_rng_state=True)
            else:
                values = self._advance(*arguments)
            state = TensorPopulationState(*values[:4])
            trace = values[4]
            outputs.append(values[5])
        return torch.cat(outputs, dim=1)
