"""Explicit probability state for the separate distribution-FV candidate.

Finite active and refractory cells have uniform density; the upper half-line
has an explicit exponential density. Dirac atoms remain separate. Grid,
positions and physical clocks are fixed data; coefficients can be trained.
"""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math

import torch


def physical_time(value):
    """Exact decimal-data clock, not a uniform tick or a trainable tensor."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, (bool, torch.Tensor)) or not isinstance(value, (int, float, str)):
        raise ValueError("physical time must be fixed finite scalar data")
    if not math.isfinite(float(value)):
        raise ValueError("physical time must be finite")
    return Fraction(str(value))


def _edges(value, name, maximum):
    if isinstance(value, torch.Tensor):
        raise ValueError(f"{name} are fixed real configuration, not tensors")
    sequence = tuple(value)
    if any(isinstance(v, (bool, torch.Tensor)) for v in sequence):
        raise ValueError(f"{name} are fixed real configuration, not tensors")
    result = tuple(float(v) for v in sequence)
    if (len(result) < 2 or len(result) > maximum+1 or result[0] != 0
            or any(not math.isfinite(v) for v in result)
            or any(b <= a for a, b in zip(result[:-1], result[1:]))):
        raise ValueError(f"{name} must have 1..{maximum} finite cells increasing from zero")
    return result


@dataclass(frozen=True)
class DistributionGrid:
    active_edges: tuple
    refractory_edges: tuple
    tail_rate: float = 1.

    def __post_init__(self):
        object.__setattr__(self, "active_edges", _edges(self.active_edges, "active edges", 256))
        object.__setattr__(self, "refractory_edges", _edges(self.refractory_edges, "refractory edges", 64))
        if not .25 <= self.active_edges[-1] <= 8:
            raise ValueError("finite active endpoint must be in [.25,8]")
        if not 1e-4 <= self.refractory_edges[-1] <= 8:
            raise ValueError("this FV candidate requires refractory duration in [1e-4,8]")
        if (isinstance(self.tail_rate, (bool, torch.Tensor)) or not isinstance(self.tail_rate, (int, float))
                or not math.isfinite(self.tail_rate) or not .25 <= self.tail_rate <= 8):
            raise ValueError("fixed exponential tail rate must be in [.25,8]")

    @property
    def active_size(self):
        return len(self.active_edges)-1

    @property
    def refractory_size(self):
        return len(self.refractory_edges)-1

    @property
    def size(self):
        return self.active_size+1+self.refractory_size

    def specification(self):
        return dict(active_edges=self.active_edges, refractory_edges=self.refractory_edges,
                    tail_rate=self.tail_rate, tail_density="lambda*exp(-lambda*(x-L)) on [L,infinity)")

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(self.specification(), sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class DistributionState:
    """Whole probability measure, with a shared batch clock and explicit atoms.

    mass[..., :N], mass[..., N], mass[..., N+1:] are active, tail, phase.
    An x=0 atom denotes an initial instantaneous hit still to process. A phase
    atom at zero instead belongs to active reset a. Nothing renormalizes here.
    """
    grid: DistributionGrid
    mass: torch.Tensor
    active_atoms: tuple = ()
    active_atom_mass: torch.Tensor | None = None
    refractory_atoms: tuple = ()
    refractory_atom_mass: torch.Tensor | None = None
    elapsed: Fraction = Fraction(0)
    steps: int = 0
    generator_identity: str | None = None
    projection_active_distance_sum: torch.Tensor | None = None
    projection_phase_time_sum: torch.Tensor | None = None

    def __post_init__(self):
        if (not isinstance(self.mass, torch.Tensor) or self.mass.dtype not in (torch.float32, torch.float64)
                or self.mass.ndim < 1 or self.mass.shape[-1] != self.grid.size):
            raise ValueError("mass must be FP32/FP64 with the exact grid dimension")
        if any(isinstance(x, (bool, torch.Tensor)) for x in self.active_atoms):
            raise ValueError("Dirac positions are fixed state metadata")
        positions = tuple(float(x) for x in self.active_atoms)
        if any(not math.isfinite(x) or x < 0 for x in positions):
            raise ValueError("active Dirac positions must be finite and nonnegative")
        remaining = tuple(physical_time(r) for r in self.refractory_atoms)
        duration = physical_time(self.grid.refractory_edges[-1])
        if any(r <= 0 or r > duration for r in remaining):
            raise ValueError("refractory Dirac remaining times must be in (0,d]")
        object.__setattr__(self, "active_atoms", positions)
        object.__setattr__(self, "refractory_atoms", remaining)
        for field, count in (("active_atom_mass", len(positions)), ("refractory_atom_mass", len(remaining))):
            value = getattr(self, field)
            if value is None:
                value = self.mass.new_zeros(self.mass.shape[:-1]+(count,))
                object.__setattr__(self, field, value)
            if (not isinstance(value, torch.Tensor) or value.dtype != self.mass.dtype or value.device != self.mass.device
                    or value.shape != self.mass.shape[:-1]+(count,)):
                raise ValueError("atom masses must share batch shape, dtype and device")
        elapsed = physical_time(self.elapsed)
        if elapsed < 0 or isinstance(self.steps, bool) or not isinstance(self.steps, int) or self.steps < 0:
            raise ValueError("elapsed physical time and completed steps must be nonnegative")
        object.__setattr__(self, "elapsed", elapsed)
        if self.steps > 0 and not self.generator_identity:
            raise ValueError("an advanced state must retain its fixed generator identity")
        for name in ("projection_active_distance_sum", "projection_phase_time_sum"):
            diagnostic = getattr(self, name)
            if diagnostic is None:
                diagnostic = self.mass.new_zeros(self.batch_shape)
            if (not isinstance(diagnostic, torch.Tensor) or diagnostic.dtype != self.dtype or diagnostic.device != self.device
                    or diagnostic.shape != self.batch_shape or not bool(torch.isfinite(diagnostic).all())
                    or bool((diagnostic < 0).any())):
                raise ValueError("projection diagnostics must match the state batch and dtype")
            object.__setattr__(self, name, diagnostic.detach())
        for value in (self.mass, self.active_atom_mass, self.refractory_atom_mass):
            if not bool(torch.isfinite(value).all()) or bool((value < 0).any()):
                raise FloatingPointError("state coefficients must be finite and nonnegative")
        tolerance = 5e-5 if self.mass.dtype == torch.float32 else 5e-10
        if bool(((self.total_mass-1).abs() > tolerance).any()):
            raise FloatingPointError("state mass unresolved; no normalization is applied")

    @property
    def active(self):
        return self.mass[..., :self.grid.active_size]

    @property
    def tail(self):
        return self.mass[..., self.grid.active_size]

    @property
    def refractory(self):
        return self.mass[..., self.grid.active_size+1:]

    @property
    def total_mass(self):
        return self.mass.sum(-1)+self.active_atom_mass.sum(-1)+self.refractory_atom_mass.sum(-1)

    @property
    def active_probability(self):
        atom = self.mass.new_tensor([float(x > 0) for x in self.active_atoms])
        return self.active.sum(-1)+self.tail+(self.active_atom_mass*atom).sum(-1)

    @property
    def physical_elapsed(self):
        return float(self.elapsed)

    @property
    def dtype(self):
        return self.mass.dtype

    @property
    def device(self):
        return self.mass.device

    @property
    def batch_shape(self):
        return self.mass.shape[:-1]

    @property
    def packed(self):
        return torch.cat((self.mass, self.active_atom_mass, self.refractory_atom_mass), dim=-1)

    @classmethod
    def point(cls, grid, x, *, dtype=torch.float32, device="cpu", elapsed=0.):
        mass = torch.zeros(grid.size, dtype=dtype, device=device)
        return cls(grid, mass, (x,), mass.new_ones(1), elapsed=physical_time(elapsed))

    @classmethod
    def phase_point(cls, grid, remaining, *, dtype=torch.float32, device="cpu", elapsed=0.):
        mass = torch.zeros(grid.size, dtype=dtype, device=device)
        return cls(grid, mass, refractory_atoms=(remaining,), refractory_atom_mass=mass.new_ones(1),
                   elapsed=physical_time(elapsed))

    def detached(self):
        return DistributionState(self.grid, self.mass.detach(), self.active_atoms, self.active_atom_mass.detach(),
                                 self.refractory_atoms, self.refractory_atom_mass.detach(), self.elapsed, self.steps,
                                 self.generator_identity, self.projection_active_distance_sum,
                                 self.projection_phase_time_sum)

    def state_dict(self):
        return dict(schema="hcsn.distribution-state.v1", grid_identity=self.grid.identity,
                    mass=self.mass.detach().cpu(), active_atoms=self.active_atoms,
                    active_atom_mass=self.active_atom_mass.detach().cpu(),
                    refractory_atoms=[(r.numerator, r.denominator) for r in self.refractory_atoms],
                    refractory_atom_mass=self.refractory_atom_mass.detach().cpu(),
                    elapsed=(self.elapsed.numerator, self.elapsed.denominator), steps=self.steps,
                    generator_identity=self.generator_identity,
                    projection_active_distance_sum=self.projection_active_distance_sum.detach().cpu(),
                    projection_phase_time_sum=self.projection_phase_time_sum.detach().cpu())

    @classmethod
    def from_state_dict(cls, grid, payload, *, device="cpu"):
        if payload["schema"] != "hcsn.distribution-state.v1" or payload["grid_identity"] != grid.identity:
            raise ValueError("state schema/grid identity mismatch")
        return cls(grid, payload["mass"].to(device), tuple(payload["active_atoms"]),
                   payload["active_atom_mass"].to(device), tuple(Fraction(*r) for r in payload["refractory_atoms"]),
                   payload["refractory_atom_mass"].to(device), Fraction(*payload["elapsed"]), payload["steps"],
                   payload["generator_identity"], payload["projection_active_distance_sum"].to(device),
                   payload["projection_phase_time_sum"].to(device))


@dataclass(frozen=True)
class ConditioningReceipt:
    state: DistributionState
    evidence: torch.Tensor
    observation_id: str


def condition_on_likelihood(state, likelihood, *, observation_id):
    """Explicit Bayes update with cellwise/atomwise constant likelihood.

    This normalization has observational semantics, exposes its evidence, and
    is never used by the transition operator to conceal mass errors.
    """
    if not isinstance(observation_id, str) or not observation_id:
        raise ValueError("conditioning needs an explicit observation identity")
    if (not isinstance(likelihood, torch.Tensor) or likelihood.dtype != state.dtype
            or likelihood.device != state.device or likelihood.shape != state.packed.shape
            or not bool(torch.isfinite(likelihood).all()) or bool((likelihood < 0).any())):
        raise ValueError("likelihood must be finite nonnegative and match the full state dimension")
    weighted = state.packed*likelihood
    evidence = weighted.sum(-1)
    if not bool(torch.isfinite(evidence).all()) or bool((evidence <= 0).any()):
        raise FloatingPointError("observation has zero or nonfinite evidence")
    posterior = weighted/evidence[..., None]
    n, k = state.grid.size, len(state.active_atoms)
    result = DistributionState(state.grid, posterior[..., :n], state.active_atoms, posterior[..., n:n+k],
                               state.refractory_atoms, posterior[..., n+k:], state.elapsed, state.steps,
                               state.generator_identity, state.projection_active_distance_sum,
                               state.projection_phase_time_sum)
    return ConditioningReceipt(result, evidence, observation_id)
