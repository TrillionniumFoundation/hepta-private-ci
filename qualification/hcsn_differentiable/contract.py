"""Contracts for a new FP64 differentiable, fixed-basis HCSN candidate.

These contracts do not extend an old qualification. The boundary and all
physical parameters are constant within an episode. Only probability and
content coefficients evolve between observations.
"""

from dataclasses import dataclass
import math

import torch


@dataclass(frozen=True)
class GridSpec:
    """Uniform active/remaining-time cells plus a returning exponential tail.

    ``phase_cells`` represent *remaining deterministic time*, not Erlang
    stages. Reprojection to these cells introduces a declared delay error.
    Grid geometry and all integration orders are fixed hyperparameters.
    """

    active_cells: int = 16
    endpoint: float = 2.0
    phase_cells: int = 8
    refractory: float = 0.1
    tail_rate: float = 1.0
    quadrature_order: int = 16
    initial_log_std: float = 0.08

    def __post_init__(self):
        for name in ("active_cells", "phase_cells", "quadrature_order"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be a fixed integer")
        if not 4 <= self.active_cells <= 256:
            raise ValueError("active_cells must be between 4 and 256")
        if not 2 <= self.phase_cells <= 128:
            raise ValueError("phase_cells must be between 2 and 128")
        if self.quadrature_order not in (8, 16, 32, 64):
            raise ValueError("quadrature_order must be 8, 16, 32, or 64")
        for name in ("endpoint", "refractory", "tail_rate", "initial_log_std"):
            value = getattr(self, name)
            if (isinstance(value, (bool, torch.Tensor))
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be a fixed positive finite real")
        if not self.refractory <= 2.0 or not self.endpoint <= 8.0:
            raise ValueError("this candidate requires refractory<=2 and endpoint<=8")
        if not 0.001 <= self.initial_log_std <= 1.0:
            raise ValueError("initial_log_std must be in [0.001,1]")

    @property
    def state_count(self):
        return self.active_cells + 1 + self.phase_cells

    @property
    def active_count(self):
        """Number of active coefficients, including the explicit tail."""
        return self.active_cells + 1

    @property
    def active_edges(self):
        return tuple(self.endpoint * i / self.active_cells
                     for i in range(self.active_cells + 1))

    @property
    def phase_edges(self):
        return tuple(self.refractory * i / self.phase_cells
                     for i in range(self.phase_cells + 1))


@dataclass(frozen=True)
class PhysicalParameters:
    """Scalar physical tensors shared by a layer's batch, without detaching.

    ``log_boundary`` is log(b). ``absolute_reset`` is the physical V_r,
    independently parameterized from b, with log(V_r)-log(b)>0. ``mu`` is the
    drift of log(V), not the drift of V. FP64 is the only execution dtype.
    """

    log_boundary: torch.Tensor
    mu: torch.Tensor
    sigma: torch.Tensor
    absolute_reset: torch.Tensor
    discount: torch.Tensor

    def tensors(self):
        return (self.log_boundary, self.mu, self.sigma,
                self.absolute_reset, self.discount)

    def snapshot(self):
        """Detached copies for episode identity checks, never for propagation."""
        return tuple(value.detach().clone() for value in self.tensors())

    def assert_matches_snapshot(self, snapshot):
        if len(snapshot) != 5 or any(
            old.shape != new.shape or old.dtype != new.dtype
            or old.device != new.device or not torch.equal(old, new.detach())
            for old, new in zip(snapshot, self.tensors())
        ):
            raise ValueError("physical parameters changed within an episode; initialize a new episode")


@dataclass(frozen=True)
class OperatorTable:
    matrix: torch.Tensor
    rewards: torch.Tensor
    call: torch.Tensor
    risk: torch.Tensor
    margin: torch.Tensor
    duration: float
    active_probability: torch.Tensor


@dataclass(frozen=True)
class FlowReceipt:
    probability: torch.Tensor
    content_mass: torch.Tensor
    expected_events: torch.Tensor
    discounted_events: torch.Tensor
    discounted_active_time: torch.Tensor
    call: torch.Tensor
    risk: torch.Tensor
    margin: torch.Tensor
    mass_residual: torch.Tensor
