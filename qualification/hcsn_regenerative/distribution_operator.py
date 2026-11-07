"""Fixed-generator finite-volume continuation of a whole probability state.

Construction is explicitly FP64, followed by declared FP32 or FP64 matrix
execution. This candidate qualifies state/likelihood/readout gradients, not
trainable or observation-conditioned generator parameters. Each step is QPR;
the within-cell and tail-shape projections are part of the numerical model.
"""

from dataclasses import dataclass
import hashlib
import json
import math
import time

import torch

from .distribution import DistributionState, physical_time
from .distribution_kernel import construction_tables, gaussian_excess_upper, point_row, tail_excess_bounds
from .tensor import TensorDiffusion


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _tensor_hash(value):
    value = value.detach().cpu().contiguous()
    return hashlib.sha256(value.numpy().tobytes()).hexdigest()


@dataclass(frozen=True)
class FlowReceipt:
    state: DistributionState
    first_hit_probability: torch.Tensor
    expected_hits: torch.Tensor
    expected_discounted_hits: torch.Tensor
    discounted_active_time: torch.Tensor
    mass_residual: torch.Tensor
    active_projection_distance_upper: torch.Tensor
    phase_projection_time_upper: torch.Tensor
    tail_projection_distance_upper: torch.Tensor
    spatial_truncation_mass: float
    renewal_truncation_mass: float
    operator_identity: str


class DistributionOperator:
    """Immutable physical configuration and fixed transition/reward matrices.

    All batches share a physical duration and a clock. dt is real fixed data,
    with 1e-4<=dt<=refractory; it is not an integer tick. The exponential tail
    is reinjected through its declared density on every call, including paths
    returning below the finite endpoint. No operator call normalizes mass.
    """

    def __init__(self, process, reset, grid, dt, *, dtype=torch.float32, device="cpu", quadrature_order=32):
        started = time.monotonic()
        if dtype not in (torch.float32, torch.float64):
            raise ValueError("execution dtype must be explicitly FP32 or FP64")
        if (isinstance(quadrature_order, bool) or not isinstance(quadrature_order, int)
                or quadrature_order not in (8, 16, 32, 64)):
            raise ValueError("fixed outer quadrature order must be 8,16,32,64")
        duration = physical_time(dt)
        refractory = physical_time(reset.refractory)
        if not physical_time(1e-4) <= duration <= refractory:
            raise ValueError("this candidate requires real 1e-4<=dt<=refractory")
        if physical_time(grid.refractory_edges[-1]) != refractory:
            raise ValueError("phase grid endpoint must equal the physical refractory duration")
        parameters = (process.mu, process.sigma, process.discount)
        if any(v.numel() != 1 or v.requires_grad for v in parameters):
            raise ValueError("the whole rollout uses one fixed scalar generator; it is not trainable here")
        values = tuple(float(v.detach().cpu()) for v in parameters)
        self._process = TensorDiffusion(*(torch.tensor(v, dtype=torch.float64, device=device) for v in values))
        self._grid, self._reset, self._dt = grid, reset, duration
        self._generator_spec = dict(mu=values[0], sigma=values[1], discount=values[2],
                                    reset_margin=reset.margin, refractory=reset.refractory,
                                    hit_reward=reset.hit_reward, model="fixed-log-generator-fixed-reset")
        self._generator_identity = _identity(self._generator_spec)
        with torch.no_grad():
            coarse, coarse_reward = construction_tables(self._process, reset, grid, float(duration), quadrature_order)
            fine, fine_reward = construction_tables(self._process, reset, grid, float(duration), 2*quadrature_order)
            row_difference = (fine-coarse).abs().sum(-1)
            reward_scale = fine.new_tensor([1., 1., float(duration)])
            reward_difference = ((fine_reward-coarse_reward)/reward_scale).abs().amax(-1)
            if (not bool(torch.isfinite(fine).all()) or not bool(torch.isfinite(fine_reward).all())
                    or bool((fine < 0).any()) or bool((fine_reward < 0).any())):
                raise FloatingPointError("fixed-operator quadrature produced invalid coefficients")
            residual = (fine.sum(-1)-1).abs()
            if (bool((row_difference > 2e-7).any()) or bool((reward_difference > 2e-7).any())
                    or bool((residual > 3e-10).any())):
                raise FloatingPointError("fixed-operator quadrature is unresolved; refine the declared configuration")
            self._matrix = fine.to(dtype).detach()
            self._rewards = fine_reward.to(dtype).detach()
            self._tail_excess = tail_excess_bounds(self._process, reset, grid, float(duration)).to(dtype).detach()
            cast_residual = (self._matrix.double().sum(-1)-1).abs().max()
            if float(cast_residual) > (3e-6 if dtype == torch.float32 else 3e-10):
                raise FloatingPointError("materialized execution matrix fails probability conservation")
        self._spec = dict(candidate="hcsn-regenerative-distribution-fv-v1", generator=self._generator_spec,
                          grid=grid.specification(), duration=(duration.numerator, duration.denominator),
                          construction_dtype="torch.float64", execution_dtype=str(dtype),
                          device=str(self._matrix.device), quadrature_order=quadrature_order)
        self._identity = _identity(self._spec)
        self._diagnostics = dict(source_row_l1_order_difference=float(row_difference.max()),
                                scaled_reward_order_difference=float(reward_difference.max()),
                                construction_mass_residual=float(residual.max()),
                                materialized_mass_residual=float(cast_residual),
                                matrix_sha256=_tensor_hash(self._matrix),
                                reward_sha256=_tensor_hash(self._rewards),
                                construction_wall_seconds=time.monotonic()-started,
                                materialization_zeroed_positive_matrix_entries=int(((fine > 0)&(self._matrix == 0)).sum()),
                                materialization_zeroed_probability_mass_max_row=float(
                                    torch.where((fine > 0)&(self._matrix == 0), fine, torch.zeros_like(fine)).sum(-1).max()),
                                relative_tail_probability_qualified=False,
                                spatial_truncation_mass=0., renewal_truncation_mass=0.,
                                projection_is_part_of_model=True, whole_trajectory_error_bound_qualified=False)
        self._atom_cache = {}

    @property
    def grid(self):
        return self._grid

    @property
    def reset(self):
        return self._reset

    @property
    def dt(self):
        return self._dt

    @property
    def identity(self):
        return self._identity

    @property
    def generator_identity(self):
        return self._generator_identity

    @property
    def diagnostics(self):
        return dict(self._diagnostics)

    @property
    def dtype(self):
        return self._matrix.dtype

    @property
    def device(self):
        return self._matrix.device

    @property
    def matrix(self):
        return self._matrix.clone()

    @property
    def reward_matrix(self):
        """Columns: first-hit probability, discounted hits, active occupation."""
        return self._rewards.clone()

    def specification(self):
        return json.loads(json.dumps(self._spec))

    def checkpoint_identity(self):
        return dict(operator_identity=self.identity, generator_identity=self.generator_identity,
                    matrix_sha256=self.diagnostics["matrix_sha256"], reward_sha256=self.diagnostics["reward_sha256"])

    def _atom_row(self, position, duration):
        key = (position, duration.numerator, duration.denominator)
        if key not in self._atom_cache:
            with torch.no_grad():
                mass, rewards = point_row(self._process, self.reset, self.grid, position, float(duration))
                self._atom_cache[key] = (mass.to(self.dtype).detach(), rewards.to(self.dtype).detach())
        return self._atom_cache[key]

    def _atom_tail_bound(self, position, duration):
        mu, sigma = float(self._process.mu), float(self._process.sigma)
        t = float(duration)
        return gaussian_excess_upper(position+mu*t-self.grid.active_edges[-1], sigma*math.sqrt(t))

    def advance(self, state):
        if state.grid.identity != self.grid.identity or state.dtype != self.dtype or state.device != self.device:
            raise ValueError("state and operator must have identical grid, execution dtype and device")
        if state.generator_identity not in (None, self.generator_identity):
            raise ValueError("changing the generator between continuation blocks is outside this candidate")
        mass = state.mass@self._matrix
        reward = state.mass@self._rewards
        tail_excess = state.mass@self._tail_excess
        active_atoms, phase_atoms = {}, {}

        def add_atom(bucket, key, weight):
            bucket[key] = bucket[key]+weight if key in bucket else weight

        for i, position in enumerate(state.active_atoms):
            weight = state.active_atom_mass[..., i]
            if position == 0:
                event = reward.new_tensor([1., 1., 0.])
                reward = reward+weight[..., None]*event
                remaining = physical_time(self.reset.refractory)-self.dt
                if remaining > 0:
                    add_atom(phase_atoms, remaining, weight)
                else:
                    add_atom(active_atoms, self.reset.margin, weight)
            else:
                row, values = self._atom_row(position, self.dt)
                mass = mass+weight[..., None]*row
                reward = reward+weight[..., None]*values
                tail_excess = tail_excess+weight*self._atom_tail_bound(position, self.dt)
        for i, remaining in enumerate(state.refractory_atoms):
            weight = state.refractory_atom_mass[..., i]
            if remaining > self.dt:
                add_atom(phase_atoms, remaining-self.dt, weight)
            elif remaining == self.dt:
                add_atom(active_atoms, self.reset.margin, weight)
            else:
                released_time = self.dt-remaining
                row, values = self._atom_row(self.reset.margin, released_time)
                discount = math.exp(-float(self._process.discount)*float(remaining))
                local = values*values.new_tensor([1., discount, discount])
                mass = mass+weight[..., None]*row
                reward = reward+weight[..., None]*local
                tail_excess = tail_excess+weight*self._atom_tail_bound(self.reset.margin, released_time)

        def pack(bucket):
            positions = tuple(sorted(bucket))
            weights = (torch.stack([bucket[p] for p in positions], dim=-1) if positions
                       else mass.new_zeros(state.batch_shape+(0,)))
            return positions, weights

        active_positions, active_weights = pack(active_atoms)
        remaining_times, phase_weights = pack(phase_atoms)
        n = self.grid.active_size
        width = mass.new_tensor([b-a for a, b in zip(self.grid.active_edges[:-1], self.grid.active_edges[1:])])
        phase_width = mass.new_tensor([b-a for a, b in zip(self.grid.refractory_edges[:-1], self.grid.refractory_edges[1:])])
        tail_projection = tail_excess+mass[..., n]/self.grid.tail_rate
        active_projection = (mass[..., :n]*width/2).sum(-1)+tail_projection
        phase_projection = (mass[..., n+1:]*phase_width/2).sum(-1)
        result = DistributionState(self.grid, mass, active_positions, active_weights, remaining_times, phase_weights,
                                   state.elapsed+self.dt, state.steps+1, self.generator_identity,
                                   state.projection_active_distance_sum+active_projection.detach(),
                                   state.projection_phase_time_sum+phase_projection.detach())
        residual = result.total_mass-state.total_mass
        if not bool(torch.isfinite(reward).all()) or bool((reward < 0).any()):
            raise FloatingPointError("flow reward channels became invalid")
        return FlowReceipt(result, reward[..., 0], reward[..., 0], reward[..., 1], reward[..., 2], residual,
                           active_projection.detach(), phase_projection.detach(), tail_projection.detach(),
                           0., 0., self.identity)
