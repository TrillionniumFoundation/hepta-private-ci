"""Causal continuous-time comparators under the density model's budgets.

All control changes occur at observations. Between them the held context is
constant and each memory mode follows an exact exponential relaxation. Merely
inserting an observation-free time split does not change the state or controls.
The 20-mode comparator has 168 persistent float32 scalars, matching the default
8*(18 probability + context + drift + boundary) density model. It shares the
same 248 trainable controller parameters and common 729-parameter action head.
This is a specified continuous-time RNN, not a claimed CfC reproduction.
"""
from __future__ import annotations

import torch
from torch import nn


class CausalTimeBasisRNN(nn.Module):
    def __init__(self, input_size=22, hidden_size=8, modes=20):
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.modes = modes
        self.input_layer = nn.Linear(input_size, hidden_size)
        self.recurrent_layer = nn.Linear(hidden_size, hidden_size, bias=False)
        taus = (torch.logspace(-0.90309, 1.20412, modes)
                if modes > 1 else torch.tensor([1.25]))
        self.register_buffer('taus', taus)
        nn.init.xavier_uniform_(self.input_layer.weight, gain=.7)
        nn.init.zeros_(self.input_layer.bias)
        nn.init.orthogonal_(self.recurrent_layer.weight, gain=.25)

    def initial_state(self, batch_size, device=None, dtype=torch.float32):
        return {
            'memory': torch.zeros(batch_size, self.hidden_size, self.modes, device=device, dtype=dtype),
            'context': torch.zeros(batch_size, self.hidden_size, device=device, dtype=dtype),
        }

    def step(self, state, observation, dt_elapsed, event_mask=True):
        n = state['context'].shape[0]
        device=state['context'].device;dtype=state['context'].dtype
        dt = torch.as_tensor(dt_elapsed, device=device, dtype=dtype)
        if dt.numel() == 1:
            dt = dt.expand(n)
        dt = dt.reshape(n, 1, 1)
        if torch.any(dt < 0):
            raise ValueError('Negative elapsed time')
        # Only previously known controls govern the elapsed interval.
        context = state['context']
        memory = context[..., None] + (state['memory']-context[..., None]) * torch.exp(-dt/self.taus)
        mask = torch.as_tensor(event_mask, device=device, dtype=torch.bool)
        if mask.numel() == 1:
            mask = mask.expand(n)
        if bool(mask.any()):
            if observation is None: raise ValueError('True observations require features')
            safe_observation=torch.where(mask.reshape(n,1),observation,torch.zeros_like(observation))
            proposed = torch.tanh(self.input_layer(safe_observation)+self.recurrent_layer(context))
            context = torch.where(mask.reshape(n, 1), proposed, context)
        latent = memory.mean(dim=-1) + .25*context
        new_state = {'memory': memory, 'context': context}
        return new_state, {'latent': latent, 'spikes': torch.zeros_like(latent)}

    def forward(self, x, dt, event_mask=None, generator=None):
        n, length, _ = x.shape
        if bool((dt[:,0]!=0).any()): raise ValueError('Initial observation must have zero elapsed time')
        if event_mask is None:
            event_mask = torch.ones(n, length, device=x.device, dtype=torch.bool)
        state = self.initial_state(n, device=x.device, dtype=x.dtype)
        latent = []
        for t in range(length):
            state, out = self.step(state, x[:, t], dt[:, t], event_mask[:, t])
            latent.append(out['latent'])
        latent = torch.stack(latent, dim=1)
        return {'latent': latent, 'final_latent': latent[:, -1],
                'spikes': torch.zeros_like(latent), 'final_state': state}

    def metadata(self):
        scalars = self.hidden_size*(self.modes+1)
        return {
            'model': 'causal_time_basis_rnn', 'hidden_size': self.hidden_size,
            'modes': self.modes, 'taus': self.taus.detach().cpu().tolist(),
            'encoder_parameters': sum(p.numel() for p in self.parameters()),
            'persistent_state_scalars': scalars,
            'persistent_state_bytes_float32': 4*scalars,
            'shared_constant_buffer_bytes': self.taus.numel()*self.taus.element_size(),
            'readout': 'mean of memory modes + 0.25 of current deterministic context',
            'event_semantics': 'advance old held context, then observe and update context; first dt=0',
            'fixed_control_semigroup_exact': True,
            'state_excludes': 'parameters, shared constants, inputs, outputs, temporaries, external task state',
        }
