"""Differentiable tensor counterpart of population.py.

Gradients pass through drive, coupling and all state tensors. Grid, reset margin
and refractory queue length are fixed hyperparameters; discrete queue length is
not advertised as differentiable. No surrogate spike gradient is needed.
"""

from dataclasses import dataclass
import math
import torch
from torch import nn
from .population import PopulationConfig, Population


@dataclass(frozen=True)
class TensorPopulationState:
    active: torch.Tensor
    refractory: torch.Tensor
    recovery: torch.Tensor
    escaped: torch.Tensor

    def total_mass(self):
        return self.active.sum(-1) + self.refractory.sum(-1) + self.escaped


@dataclass(frozen=True)
class TensorPopulationStep:
    state: TensorPopulationState
    rate: torch.Tensor
    absorbed: torch.Tensor
    escaped: torch.Tensor


def _log_interval(a, b):
    """Log Gaussian interval mass, including empty and infinite intervals.

    Evaluate every inactive branch at finite, nonsingular arguments before
    selecting it. Masking a NaN after log_ndtr(-inf) or (-inf)-(-inf) would
    still contaminate backward through a zero-times-infinity product.
    """
    regular = torch.isfinite(a) & torch.isfinite(b) & (a < b)
    safe_a = torch.where(regular, a, torch.full_like(a, -1.0))
    safe_b = torch.where(regular, b, torch.ones_like(b))
    lo = torch.where(safe_a > 0, -safe_b, safe_a)
    hi = torch.where(safe_a > 0, -safe_a, safe_b)
    log_hi = torch.special.log_ndtr(hi)
    delta = torch.minimum(torch.special.log_ndtr(lo) - log_hi,
                          torch.full_like(log_hi, -torch.finfo(a.dtype).tiny))
    log_mass = log_hi + torch.log(-torch.expm1(delta))
    finite_a = torch.where(torch.isfinite(a), a, torch.zeros_like(a))
    finite_b = torch.where(torch.isfinite(b), b, torch.zeros_like(b))
    left_open = torch.isneginf(a) & torch.isfinite(b)
    right_open = torch.isfinite(a) & torch.isposinf(b)
    full = torch.isneginf(a) & torch.isposinf(b)
    result = torch.where(regular, log_mass, torch.full_like(log_mass, -torch.inf))
    result = torch.where(left_open, torch.special.log_ndtr(finite_b), result)
    result = torch.where(right_open, torch.special.log_ndtr(-finite_a), result)
    result = torch.where(full, torch.zeros_like(result), result)
    invalid = (a > b) | torch.isnan(a) | torch.isnan(b)
    return torch.where(invalid, torch.full_like(result, torch.nan), result)


def _positive_difference(log_a, log_b):
    # The killed density is nonnegative analytically. Prevent roundoff-level
    # negative mass without normalization. A zero-minus-zero probability must
    # have a zero derivative, not a NaN produced by (-inf)-(-inf).
    zero_a, zero_b = torch.isneginf(log_a), torch.isneginf(log_b)
    safe_a = torch.where(zero_a, torch.zeros_like(log_a), log_a)
    safe_b = torch.where(zero_b, torch.zeros_like(log_b), log_b)
    delta = torch.minimum(safe_b - safe_a, torch.zeros_like(safe_a))
    difference = torch.exp(safe_a) * -torch.expm1(delta)
    difference = torch.where(zero_b, torch.exp(safe_a), difference)
    return torch.where(zero_a, torch.zeros_like(difference), difference)


def killed_transition(centres, edges, drift, sigma, dt):
    scale = sigma * math.sqrt(dt)
    reflection = -2 * drift * centres / sigma**2
    mean, image_mean = centres + drift * dt, -centres + drift * dt
    log_a = _log_interval((edges[:-1] - mean[..., None]) / scale,
                         (edges[1:] - mean[..., None]) / scale)
    log_b = reflection[..., None] + _log_interval(
        (edges[:-1] - image_mean[..., None]) / scale,
        (edges[1:] - image_mean[..., None]) / scale)
    matrix = _positive_difference(log_a, log_b)
    absorbed = 0.5 * torch.erfc((centres + drift * dt) / (scale * math.sqrt(2))) + torch.exp(
        reflection + torch.special.log_ndtr((-centres + drift * dt) / scale))
    escaped = _positive_difference(torch.special.log_ndtr((mean - edges[-1]) / scale),
                                   reflection + torch.special.log_ndtr((image_mean - edges[-1]) / scale))
    return matrix, absorbed, escaped


class TorchPopulation(nn.Module):
    """Batched population-flux module with fixed physical discretization."""

    def __init__(self, config=PopulationConfig(), *, dtype=torch.float32):
        super().__init__()
        self.config = config
        if dtype not in (torch.float32, torch.float64):
            raise ValueError("Population tensors require float32 or float64.")
        reference = Population(config)
        for name in ("edges", "centres", "reset_weights", "initial_weights"):
            self.register_buffer(name, torch.tensor(getattr(reference, name), dtype=dtype))

    def initial_state(self, shape=()):
        shape = tuple(shape)
        kwargs = {"device": self.centres.device, "dtype": self.centres.dtype}
        return TensorPopulationState(
            self.initial_weights.expand(shape + (self.config.bins,)).clone(),
            torch.zeros(shape + (self.config.refractory_steps,), **kwargs),
            torch.zeros(shape, **kwargs), torch.zeros(shape, **kwargs))

    def forward(self, state, drive=0.0, coupling=0.0):
        cfg = self.config
        drive = torch.as_tensor(drive, dtype=self.centres.dtype, device=self.centres.device)
        coupling = torch.as_tensor(coupling, dtype=self.centres.dtype, device=self.centres.device)
        drift = cfg.base_drift + cfg.leak * (cfg.rest_margin - self.centres)
        drift = drift - (drive + coupling)[..., None] + state.recovery[..., None]
        matrix, hit, escape = killed_transition(self.centres, self.edges, drift, cfg.sigma, cfg.dt)
        absorbed = (state.active * hit).sum(-1)
        escaped = (state.active * escape).sum(-1)
        active = torch.einsum("...i,...ij->...j", state.active, matrix)
        if cfg.refractory_steps:
            active = active + state.refractory[..., 0, None] * self.reset_weights
            queue = torch.cat((state.refractory[..., 1:], absorbed[..., None]), dim=-1)
        else:
            active = active + absorbed[..., None] * self.reset_weights
            queue = state.refractory
        recovery = state.recovery * math.exp(-cfg.dt / cfg.recovery_tau) + cfg.recovery_strength * absorbed
        new_state = TensorPopulationState(active, queue, recovery, state.escaped + escaped)
        return TensorPopulationStep(new_state, absorbed / cfg.dt, absorbed, escaped)

    step = forward
