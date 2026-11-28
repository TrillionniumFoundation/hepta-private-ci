"""A causal population spiking network whose only interlayer wire is a true default boundary."""
from dataclasses import replace
import math
from typing import NamedTuple

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .pricing import Contract, Prices


class PopulationState(NamedTuple):
    active: Tensor
    refractory: Tensor
    log_boundary: Tensor
    equity: Tensor
    credit_loss: Tensor


class PopulationCell(nn.Module):
    """Represent the surviving margin distribution by its mass on a fixed grid.

    Each interval has linear motion in log boundary, constant relative drift and
    exact absorbed Brownian bin probabilities. A fired unit waits one full step.
    """

    def __init__(
        self, input_size: int, width: int, *, atoms: int = 12, dt: float = 0.25,
        reset: float = 0.30, law: Contract | None = None,
        dtype: torch.dtype = torch.float64,
    ):
        super().__init__()
        if min(input_size, width) < 1 or atoms < 3 or not math.isfinite(dt) or dt <= 0:
            raise ValueError("Require positive dimensions and time step, with at least three atoms")
        if not 0.015 <= reset <= 1.30:
            raise ValueError("Reset must lie in the represented interval")
        if dtype not in (torch.float32, torch.float64):
            raise ValueError("Use float32 or float64 for transport probabilities")
        law = law or Contract()
        base = Prices(law)
        low = Prices(replace(law, principal=law.principal * 0.72))
        high = Prices(replace(law, principal=law.principal * 1.28))
        if min(low.boundary, high.boundary) <= 0 or not all(
            math.isfinite(v) for v in (low.boundary, high.boundary, base.boundary)
        ):
            raise ValueError("The chosen principal range requires positive finite equilibrium walls")
        self.input_size = input_size
        self.width = width
        self.dt = float(dt)
        self.reset_margin = reset
        self.sigma = law.sigma
        self.base_drift = base.mu
        self.log_wall_gain = (high.boundary - low.boundary) / (2 * base.boundary)
        grid = torch.linspace(0.015, 1.30, atoms, dtype=dtype)
        self.register_buffer("grid", grid)
        self.register_buffer("cuts", (grid[:-1] + grid[1:]) / 2)
        hi = int(torch.searchsorted(grid, torch.tensor(reset, dtype=dtype)).clamp(1, atoms-1))
        reset_weights = torch.zeros_like(grid)
        reset_weights[hi] = (reset-grid[hi-1]) / (grid[hi]-grid[hi-1])
        reset_weights[hi-1] = 1-reset_weights[hi]
        self.register_buffer("reset_weights", reset_weights)
        # At fixed relative margin, both prices and the boundary are affine in
        # principal for this contract family. Two exact endpoints suffice.
        for name, method in (("equity_quotes", "equity"), ("loss_quotes", "credit_loss")):
            quotes = [[getattr(p, method)(float(x)) for x in grid] for p in (low, high)]
            self.register_buffer(name, torch.tensor(quotes, dtype=dtype))
        self.input_projection = nn.Linear(input_size, width, dtype=dtype)
        self.recurrent = nn.Linear(width, width, bias=False, dtype=dtype)
        self.flow_feedback = nn.Parameter(torch.full((width,), 0.25, dtype=dtype))
        self.force_logits = nn.Parameter(torch.full((width, 2), -1.5, dtype=dtype))

    def initial_state(self, batch_size: int) -> PopulationState:
        if batch_size < 1:
            raise ValueError("A batch must contain at least one trajectory")
        zeros = self.grid.new_zeros(batch_size, self.width)
        active = self.reset_weights.expand(batch_size, self.width, -1)
        # Zero log boundary is the reference principal, midway between the
        # endpoint contracts. Its reset population already carries both prices.
        equity = self.reset_weights.dot(self.equity_quotes.mean(dim=0)).expand_as(zeros)
        loss = self.reset_weights.dot(self.loss_quotes.mean(dim=0)).expand_as(zeros)
        return PopulationState(active, zeros, zeros, equity, loss)

    def _bin_log_masses(self, mean: Tensor) -> Tensor:
        scale = self.sigma * math.sqrt(self.dt)
        lower = (F.pad(self.cuts[:-1], (1, 0)) - mean.unsqueeze(-1)) / scale
        upper = (self.cuts - mean.unsqueeze(-1)) / scale
        # Work in the smaller Gaussian tail to avoid subtracting two values near one.
        right = lower > 0
        near = torch.where(right, -lower, upper)
        far = torch.where(right, -upper, lower)
        log_near = torch.special.log_ndtr(near)
        gap = torch.special.log_ndtr(far) - log_near
        bins = log_near + torch.log((-torch.expm1(gap)).clamp_min(torch.finfo(mean.dtype).tiny))
        tail = torch.special.log_ndtr((mean-self.cuts[-1]) / scale).unsqueeze(-1)
        return torch.cat((bins, tail), dim=-1)

    def _transport(self, active: Tensor, drift: Tensor) -> tuple[Tensor, Tensor]:
        dtype = active.dtype
        if dtype not in (torch.float32, torch.float64):
            raise ValueError("Transport supports float32 and float64")
        # Under strong inward drift the reflection factor alone may overflow.
        # Combine its logarithm with the reflected Gaussian before exponentiation.
        mu = drift.unsqueeze(-1)
        normal = self._bin_log_masses(self.grid + mu*self.dt)
        reflected = self._bin_log_masses(-self.grid + mu*self.dt)
        log_tilt = -2*mu*self.grid / self.sigma**2
        ratio = (reflected + log_tilt.unsqueeze(-1) - normal).clamp_max(0)
        survival = torch.exp(normal) * (-torch.expm1(ratio))
        width = self.sigma*math.sqrt(self.dt)
        # Both first-passage terms can be deep in the left Gaussian tail.
        direct_hit = torch.exp(torch.special.log_ndtr((-self.grid-mu*self.dt)/width))
        reflected_hit = torch.exp(log_tilt + torch.special.log_ndtr((-self.grid+mu*self.dt)/width))
        hit = (direct_hit+reflected_hit).clamp(0, 1)
        return (active.unsqueeze(-1)*survival).sum(-2), (active*hit).sum(-1)

    def step(self, frame: Tensor, state: PopulationState) -> PopulationState:
        if frame.ndim != 2 or frame.shape != (state.refractory.shape[0], self.input_size):
            raise ValueError("A step expects [batch,input_size] matching the carried state")
        drive = self.input_projection(frame) + self.recurrent(state.log_boundary) + self.flow_feedback*state.refractory
        signal = torch.tanh(drive)
        mark = torch.log1p(self.log_wall_gain*signal)
        live = state.active.sum(-1)
        center = (state.active*self.grid).sum(-1) / live.clamp_min(torch.finfo(live.dtype).tiny)
        center = torch.where(live > 0, center, self.reset_margin)
        gain = F.softplus(self.force_logits)
        restoring = gain[:,0] * torch.tanh(state.equity.clamp_min(0)/20) * (self.reset_margin-center)
        inward = gain[:,1] * torch.tanh(state.credit_loss.clamp_min(0)/20)
        relative_drift = self.base_drift - 0.7*signal + restoring - inward + (state.log_boundary-mark)/self.dt
        active, fired = self._transport(state.active, relative_drift)
        active = active + state.refractory.unsqueeze(-1)*self.reset_weights
        fraction = ((signal+1)/2).unsqueeze(-1)
        equity = (active*torch.lerp(self.equity_quotes[0], self.equity_quotes[1], fraction)).sum(-1)
        loss = (active*torch.lerp(self.loss_quotes[0], self.loss_quotes[1], fraction)).sum(-1)
        return PopulationState(active, fired, mark, equity, loss)


class HeptaContinuousSpikingNetwork(nn.Module):
    """Return logits at each time and a resumable state for every recurrent layer."""

    def __init__(self, input_size: int, width: int, outputs: int, *, layers: int = 2, **cell_kwargs):
        super().__init__()
        if layers < 1 or outputs < 1:
            raise ValueError("Require at least one hidden layer and one output")
        self.cells = nn.ModuleList(
            PopulationCell(input_size if index == 0 else width, width, **cell_kwargs)
            for index in range(layers)
        )
        self.head = nn.Linear(4*width, outputs, dtype=self.cells[0].grid.dtype)

    def forward(self, frames: Tensor, state: tuple[PopulationState, ...] | None = None):
        if frames.ndim != 3 or frames.size(0) == 0 or frames.size(1) == 0:
            raise ValueError("Expected nonempty [time,batch,input] frames")
        if state is None:
            state = tuple(cell.initial_state(frames.size(1)) for cell in self.cells)
        if len(state) != len(self.cells):
            raise ValueError("Pass one carried state for each layer")
        states = list(state)
        scores = []
        for frame in frames.unbind(0):
            wire = frame
            for index, cell in enumerate(self.cells):
                states[index] = cell.step(wire, states[index])
                wire = states[index].log_boundary
            last = states[-1]
            scores.append(self.head(torch.cat((wire, last.refractory, last.equity/20, last.credit_loss/20), dim=-1)))
        return torch.stack(scores), tuple(states)
