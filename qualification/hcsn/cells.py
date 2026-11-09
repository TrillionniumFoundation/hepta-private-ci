"""Version A: bounded recurrent memory driven by stationary HX value features.

This is an encoder with a chosen vector field, not a resetting spiking neuron.
The exponential update is exact for the rate/target frozen during one step.
Conditioning a stationary boundary supplies features; it is not a moving-boundary
first-passage law for an entire input history.
"""

from dataclasses import replace
import math

import torch
from torch import nn
from torch.nn import functional as F

from .tensor import HXParams, hx_boundary, hx_equity, first_passage_cdf, simple_equity_ratio


class ValueKernelCell(nn.Module):
    """A bounded memory and recovery state with explicitly selected ablations.

    Input/output shapes are ``[batch, time, channels]``. ``step`` accepts a
    ``(memory, recovery)`` state, both of shape ``[batch, hidden]``. Nonnegative
    scalar ``dt`` is measured in the same model-time units as HX rates.
    """

    def __init__(self, input_size, hidden_size, *, channel="dual", boundary="conditional",
                 kernel="hx", recovery=True):
        super().__init__()
        if channel not in {"call", "risk", "dual"}:
            raise ValueError("channel must be call, risk, or dual")
        if boundary not in {"fixed", "conditional"}:
            raise ValueError("boundary must be fixed or conditional")
        if kernel not in {"hx", "no_rollover", "softplus"}:
            raise ValueError("kernel must be hx, no_rollover, or softplus")
        if min(input_size, hidden_size) <= 0:
            raise ValueError("input_size and hidden_size must be positive")
        self.hidden_size, self.channel = hidden_size, channel
        self.boundary_mode, self.kernel, self.use_recovery = boundary, kernel, recovery
        # The conservative coefficient box is checked at its 64 corners;
        # wider liquidity ranges can give inadmissible negative equity near b.
        self.raw_financial = nn.Parameter(torch.zeros(6, hidden_size))
        self.margin_input = nn.Linear(input_size, hidden_size)
        self.boundary_input = nn.Linear(input_size, hidden_size, bias=False)
        self.candidate_input = nn.Linear(input_size, hidden_size)
        self.candidate_memory = nn.Linear(hidden_size, hidden_size, bias=False)
        self.rate_input = nn.Linear(input_size, hidden_size)
        self.rate_features = nn.Parameter(torch.full((2, hidden_size), 0.25))
        self.value_features = nn.Parameter(torch.full((2, hidden_size), 0.25))
        self.recovery_strength = nn.Parameter(torch.zeros(hidden_size))
        self.raw_recovery_time = nn.Parameter(torch.zeros(hidden_size))
        if boundary == "fixed":
            self.boundary_input.requires_grad_(False)
        if not recovery:
            self.recovery_strength.requires_grad_(False)
            self.raw_recovery_time.requires_grad_(False)
        if kernel == "softplus":
            self.raw_financial.requires_grad_(False)

    def financial_parameters(self):
        """Learn liquidity pressure ell directly, without redundant xi/k factors."""
        s = self.raw_financial.sigmoid()
        return HXParams(r=0.02 + 0.08*s[0], delta=0.01 + 0.04*s[1],
                        sigma=0.15 + 0.30*s[2], coupon=0.02 + 0.06*s[3],
                        principal=torch.ones_like(s[0]), maturity=0.5 + 1.5*s[4],
                        tax=0.25, recovery=0.60, ell=0.03*s[5])

    def initial_state(self, batch_size, *, like=None):
        anchor = self.raw_financial if like is None else like
        memory = anchor.new_zeros(batch_size, self.hidden_size)
        return memory, torch.zeros_like(memory)

    def _base_boundary(self, params):
        if self.kernel == "hx":
            return hx_boundary(params)
        mu = params.r - params.delta - params.sigma.square()/2
        gamma = (mu + torch.sqrt(mu.square() + 2*params.r*params.sigma.square())) / params.sigma.square()
        carry = (1-params.tax)*params.coupon
        return carry/params.r * gamma/(1+gamma)

    def _features(self, inputs, memory, params, base_boundary):
        # V is anchored to face value, independently of the learned boundary.
        # Anchoring V to base_boundary would cancel all boundary sensitivity
        # from log(V/b), including the risk channel's liquidity gradient.
        value = params.principal*(2.4 + 2.0*torch.sigmoid(self.margin_input(inputs) + 0.2*memory))
        shift = (0.25*torch.tanh(self.boundary_input(inputs))
                 if self.boundary_mode == "conditional" else torch.zeros_like(value))
        x = torch.log(value/base_boundary) - shift
        if not bool(torch.isfinite(x).all()) or bool((x < 0).any()):
            raise ValueError("Value input must remain at or above the conditioned boundary")
        call, risk = torch.zeros_like(x), torch.zeros_like(x)
        if self.kernel == "softplus":
            if self.channel != "risk":
                soft = F.softplus(2*x - 1)
                call = soft/(1+soft)
            if self.channel != "call":
                risk = torch.sigmoid(0.5-2*x)
        else:
            if self.channel != "risk":
                scale = shift.exp()
                local = replace(params, coupon=params.coupon*scale, principal=params.principal*scale)
                bound = base_boundary*scale
                if self.kernel == "hx":
                    call = hx_equity(x, local, boundary=bound, validate=False)/value
                else:
                    mu = params.r - params.delta - params.sigma.square()/2
                    gamma = (mu + torch.sqrt(mu.square()+2*params.r*params.sigma.square()))/params.sigma.square()
                    call = simple_equity_ratio(x, gamma, validate=False)
            if self.channel != "call":
                mu = params.r - params.delta - params.sigma.square()/2
                risk = first_passage_cdf(x, params.maturity, mu, params.sigma, validate=False)
        return torch.stack((call, risk), dim=0)

    def step(self, inputs, state, dt=0.1, *, params=None, base_boundary=None):
        """Advance one frozen-input interval, preserving bounded state at any dt."""
        if not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be a finite nonnegative scalar")
        memory, recovery = state
        params = self.financial_parameters() if params is None else params
        base_boundary = self._base_boundary(params) if base_boundary is None else base_boundary
        features = self._features(inputs, memory, params, base_boundary)
        rate = 0.1 + 4.9*torch.sigmoid(self.rate_input(inputs) +
                                      (features*self.rate_features[:, None, :]).sum(0))
        inhibition = (torch.sigmoid(self.recovery_strength)*recovery
                      if self.use_recovery else torch.zeros_like(memory))
        target = torch.tanh(self.candidate_input(inputs) + self.candidate_memory(memory) +
                            (features*self.value_features[:, None, :]).sum(0) - inhibition)
        weight = -torch.expm1(-rate*dt)
        memory = memory + weight*(target-memory)
        if self.use_recovery:
            tau = 0.2 + 2.8*torch.sigmoid(self.raw_recovery_time)
            recover_weight = -torch.expm1(-dt/tau)
            recovery = recovery + recover_weight*(memory.abs()-recovery)
        return memory, recovery

    def forward(self, sequence, dt=0.1):
        if sequence.ndim != 3 or sequence.shape[1] < 1:
            raise ValueError("sequence must have shape [batch, positive time, input]")
        params = self.financial_parameters()
        # Validate the learned financial domain once per sequence; subsequent
        # kernel features reuse this boundary without per-step validation.
        base_boundary = self._base_boundary(params)
        state = self.initial_state(sequence.shape[0], like=sequence)
        outputs = []
        for inputs in sequence.unbind(dim=1):
            state = self.step(inputs, state, dt, params=params, base_boundary=base_boundary)
            outputs.append(state[0])
        return torch.stack(outputs, dim=1)
