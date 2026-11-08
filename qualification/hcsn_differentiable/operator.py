"""Differentiable FP64 Q P_dt R propagation with deterministic-time phases.

The continuum model is a constant-coefficient killed log diffusion, followed
by a deterministic refractory delay and reset to an *unquantized* positive
point. This module is its fixed-basis, fixed-quadrature approximation. It is
not an exact semigroup or a full He--Xiong equity solver. No old qualification
is imported, and neither matrices nor physical parameters are detached.
"""

from dataclasses import asdict
from fractions import Fraction
from functools import lru_cache
import math

import torch
from torch.autograd.function import once_differentiable

from .contract import FlowReceipt, GridSpec, OperatorTable, PhysicalParameters


class _LogNormalCDF(torch.autograd.Function):
    """Stable Mills-ratio first derivative; higher derivatives unsupported.

    The formula follows the independently inspected old numerical primitive,
    but this new implementation and its new physical-parameter paths require
    their own tests. Native log_ndtr backward loses accuracy for large -z.
    """

    @staticmethod
    def forward(ctx, value):
        ctx.save_for_backward(value)
        return torch.special.log_ndtr(value)

    @staticmethod
    @once_differentiable
    def backward(ctx, upstream):
        value, = ctx.saved_tensors
        negative = value <= 0
        left = torch.where(negative, value, torch.zeros_like(value))
        right = torch.where(negative, torch.zeros_like(value), value)
        left_ratio = math.sqrt(2.0 / math.pi) / torch.special.erfcx(-left / math.sqrt(2.0))
        right_ratio = torch.exp(-0.5 * right.square() - 0.5 * math.log(2.0 * math.pi)
                                - torch.special.log_ndtr(right))
        result = upstream * torch.where(negative, left_ratio, right_ratio)
        if not bool(torch.isfinite(result).all()):
            raise FloatingPointError("normal-CDF derivative is unresolved in FP64")
        return result


def _logcdf(value):
    return _LogNormalCDF.apply(value)


@lru_cache(maxsize=8)
def _gauss_legendre_unit(order):
    """Fixed positive Gauss rule on (0,1), using only the standard library."""
    pairs = []
    for i in range((order + 1) // 2):
        root = math.cos(math.pi * (i + 0.75) / (order + 0.5))
        for _ in range(100):
            p0, p1 = 1.0, root
            for degree in range(2, order + 1):
                p0, p1 = p1, ((2 * degree - 1) * root * p1 - (degree - 1) * p0) / degree
            derivative = order * (root * p1 - p0) / (root * root - 1.0)
            updated = root - p1 / derivative
            if abs(updated - root) <= 2e-16:
                root = updated
                break
            root = updated
        else:
            raise ArithmeticError("Gauss rule did not converge")
        p0, p1 = 1.0, root
        for degree in range(2, order + 1):
            p0, p1 = p1, ((2 * degree - 1) * root * p1 - (degree - 1) * p0) / degree
        derivative = order * (root * p1 - p0) / (root * root - 1.0)
        weight = 1.0 / ((1.0 - root * root) * derivative * derivative)
        pairs.extend((((1.0 - root) / 2.0, weight), ((1.0 + root) / 2.0, weight)))
    pairs.sort()
    # This fixes quadrature constant exactness, not a transition row's mass.
    total_weight = math.fsum(weight for _, weight in pairs)
    return (tuple(node for node, _ in pairs),
            tuple(weight / total_weight for _, weight in pairs))


def _finite(name, value):
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError(f"{name} is nonfinite")


def _nonnegative(name, value):
    _finite(name, value)
    if bool((value < 0).any()):
        raise FloatingPointError(f"{name} became negative; the numerical scale is unresolved")
    return value


def _tensor(value, like):
    if isinstance(value, torch.Tensor):
        if value.dtype != like.dtype or value.device != like.device:
            raise ValueError("continuous tensors must share FP64 dtype and device")
        return value
    return torch.as_tensor(value, dtype=like.dtype, device=like.device)


def _check_parameters(params):
    if not isinstance(params, PhysicalParameters):
        raise TypeError("params must be PhysicalParameters")
    names = ("log_boundary", "mu", "sigma", "absolute_reset", "discount")
    for name, value in zip(names, params.tensors()):
        if not isinstance(value, torch.Tensor) or value.ndim != 0 or value.dtype != torch.float64:
            raise ValueError(f"{name} must be a scalar FP64 Tensor")
        if value.device != params.mu.device:
            raise ValueError("physical tensors must share one device")
        _finite(name, value)
    if bool(params.mu.abs() > 2.0) or bool((params.sigma < 0.05) | (params.sigma > 2.0)):
        raise ValueError("declared numerical domain: |mu|<=2 and 0.05<=sigma<=2")
    if bool((params.discount < 0.001) | (params.discount > 4.0)):
        raise ValueError("declared numerical domain: 0.001<=discount<=4")
    if bool(params.absolute_reset <= 0):
        raise ValueError("absolute_reset must be positive")
    margin = torch.log(params.absolute_reset) - params.log_boundary
    if bool((margin < 1e-4) | (margin > 8.0)):
        raise ValueError("log(absolute_reset)-log_boundary must be in [1e-4,8]")
    return margin


def _first_hit(x, horizon, mu, sigma, discount=None):
    """F or G_q, with zero for nonpositive deadlines and strict x>0.

    Nonpositive deadlines arise from fixed refractory interval geometry.
    They are not replaced by trainable soft steps.
    """
    x, horizon = torch.broadcast_tensors(x, _tensor(horizon, x))
    positive = horizon > 0
    time = torch.where(positive, horizon, torch.ones_like(horizon))
    scale = sigma * torch.sqrt(time)
    if discount is None:
        first = _logcdf((-x - mu * time) / scale)
        second = -2.0 * mu * x / sigma.square() + _logcdf((-x + mu * time) / scale)
    else:
        root = torch.sqrt(mu.square() + 2.0 * discount * sigma.square())
        # Evaluate rationalized roots on the appropriate side without a
        # singular unselected denominator in the backward graph.
        positive_mu = mu > 0
        negative_mu = mu < 0
        safe_plus = torch.where(positive_mu, root + mu, torch.ones_like(root))
        safe_minus = torch.where(negative_mu, root - mu, torch.ones_like(root))
        root_minus = torch.where(positive_mu, 2.0 * discount / safe_plus,
                                 (root - mu) / sigma.square())
        root_plus = torch.where(negative_mu, 2.0 * discount / safe_minus,
                                (root + mu) / sigma.square())
        first = root_minus * x + _logcdf((-x - root * time) / scale)
        second = -root_plus * x + _logcdf((-x + root * time) / scale)
    result = torch.exp(torch.logaddexp(first, second))
    return torch.where(positive, result, torch.zeros_like(result))


def _survivor_tail(x, horizon, mu, sigma, edge):
    """P(X_T>=edge,tau_0>T), evaluated as a stable reflection difference."""
    x, horizon, edge = torch.broadcast_tensors(x, horizon, edge)
    scale = sigma * torch.sqrt(horizon)
    first = _logcdf((x + mu * horizon - edge) / scale)
    second = -2.0 * mu * x / sigma.square() + _logcdf((-x + mu * horizon - edge) / scale)
    return torch.exp(first) * (-torch.expm1(second - first))


class DifferentiableDistributionOperator(torch.nn.Module):
    """One physical propagation, 0<=dt<=d, with an unchanged parameter graph.

    Scalar parameters are shared by the batch. Distinct per-sample durations
    are fixed data, not differentiation targets. All per-call matrix builds
    preserve autograd. No cross-call matrix cache can retain stale parameters.

    ``reset_enabled=False`` is a separately declared killed control: incoming
    hit mass is permanently absorbed in the first phase slot. Other phase
    slots are unreachable from a valid initial state and remain identities.
    """

    def __init__(self, grid=None, active_reward=0.4, hit_reward=1.0,
                 terminal_reward=0.2, reset_enabled=True):
        super().__init__()
        self.grid = GridSpec() if grid is None else grid
        if not isinstance(self.grid, GridSpec):
            raise TypeError("grid must be GridSpec")
        if not isinstance(reset_enabled, bool):
            raise ValueError("reset_enabled must be a fixed boolean")
        self.reset_enabled = reset_enabled
        for name, value in (("active_reward", active_reward), ("hit_reward", hit_reward),
                            ("terminal_reward", terminal_reward)):
            if (isinstance(value, (bool, torch.Tensor)) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be a fixed nonnegative finite real")
            setattr(self, name, float(value))
        nodes, weights = _gauss_legendre_unit(self.grid.quadrature_order)
        self.register_buffer("_nodes", torch.tensor(nodes, dtype=torch.float64))
        self.register_buffer("_weights", torch.tensor(weights, dtype=torch.float64))
        self.register_buffer("_active_edges", torch.tensor(self.grid.active_edges, dtype=torch.float64))
        self._delay = Fraction(str(self.grid.refractory))
        self._phase_edges = tuple(self._delay * i / self.grid.phase_cells
                                  for i in range(self.grid.phase_cells + 1))

    @property
    def state_count(self):
        return self.grid.state_count

    def configuration(self):
        """Plain semantic configuration for retained-state/checkpoint checks.

        Fixed quadrature/edge buffers must additionally be snapshotted through
        ``state_dict`` by the enclosing network. This mapping includes the
        nonbuffer geometry actually used to transport remaining delay.
        """
        return {
            "schema": "hcsn-differentiable-deterministic-qpr-v1",
            "grid": asdict(self.grid),
            "active_reward": self.active_reward,
            "hit_reward": self.hit_reward,
            "terminal_reward": self.terminal_reward,
            "reset_enabled": self.reset_enabled,
            "mode": "regenerative" if self.reset_enabled else "killed_absorbing_control",
            "phase_semantics": "uniform_remaining_time" if self.reset_enabled else "first_phase_absorbs",
            "actual_delay_fraction": str(self._delay),
            "actual_phase_edge_fractions": [str(edge) for edge in self._phase_edges],
            "dtype": "float64",
            "normal_cdf_derivatives": "first_order_stable_mills_ratio",
            "source_quadrature": "positive_gauss_legendre_fixed_order",
            "occupation_quadrature": "positive_gauss_legendre_squared_time",
            "tail_basis": "returning_shifted_exponential",
            "initial_prior": "conditioned_physical_lognormal",
            "reset_location": "continuous_absolute_log_mapping",
            "content_reset": "identity",
            "row_normalization": False,
        }

    def _constants(self, like):
        return (self._nodes.to(device=like.device, dtype=like.dtype),
                self._weights.to(device=like.device, dtype=like.dtype),
                self._active_edges.to(device=like.device, dtype=like.dtype))

    def _margin_feature(self, like):
        _, _, edges = self._constants(like)
        return torch.cat(((edges[:-1] + edges[1:]) / 2.0,
                          like.new_tensor([self.grid.endpoint + 1.0 / self.grid.tail_rate]),
                          like.new_zeros(self.grid.phase_cells)))

    def initial_probability(self, absolute_initial, log_boundary):
        """Project a conditioned physical lognormal prior, preserving b-grad.

        log(V) ~ N(log(absolute_initial), initial_log_std**2), conditional on
        V>b. This is a declared continuous initial law, not a projected Dirac.
        The tail coefficient is its integrated mass, reconstructed thereafter
        using the fixed exponential basis. No nearest-cell placement is used.
        """
        if (not isinstance(log_boundary, torch.Tensor) or log_boundary.ndim != 0
                or log_boundary.dtype != torch.float64):
            raise ValueError("log_boundary must be a scalar FP64 Tensor")
        value = _tensor(absolute_initial, log_boundary)
        if value.ndim > 1 or bool((value <= 0).any()):
            raise ValueError("absolute_initial must be a positive scalar or batch vector")
        _finite("absolute_initial", value)
        _finite("log_boundary", log_boundary)
        mean = torch.log(value) - log_boundary
        if bool(((mean <= 0) | (mean > 8.0)).any()):
            raise ValueError("initial log-median margin must be in (0,8]")
        _, _, edges = self._constants(log_boundary)
        denominator = _logcdf(mean / self.grid.initial_log_std)
        tails = torch.exp(_logcdf((mean[..., None] - edges) / self.grid.initial_log_std)
                          - denominator[..., None])
        active = torch.cat((tails[..., :-1] - tails[..., 1:], tails[..., -1:]), dim=-1)
        _nonnegative("initial active coefficients", active)
        return torch.cat((active, active.new_zeros(active.shape[:-1] + (self.grid.phase_cells,))), dim=-1)

    def _point_row(self, x, horizon, params):
        """Exact killed probabilities plus fixed quadrature occupation reward.

        Points have x>0 and 0<T<=d. A point that hits cannot release again
        within this interval. In particular reset locations are evaluated
        directly here, not mapped to an argmin or a nearest-bin surrogate.
        """
        x, horizon = torch.broadcast_tensors(x, _tensor(horizon, x))
        nodes, weights, edges = self._constants(x)
        mu, sigma, discount = params.mu, params.sigma, params.discount
        tails = _survivor_tail(x[..., None], horizon[..., None], mu, sigma, edges)
        bins = tails[..., :-1] - tails[..., 1:]
        active = torch.cat((bins, tails[..., -1:]), dim=-1)
        hit = _first_hit(x, horizon, mu, sigma)
        discounted_hit = _first_hit(x, horizon, mu, sigma, discount)
        # Direct positive occupation quadrature avoids division of close
        # probabilities by small q. The rule is part of the candidate.
        times = horizon[..., None] * nodes.square()
        survival = _survivor_tail(x[..., None], times, mu, sigma, torch.zeros_like(times))
        occupation = (2.0 * horizon[..., None] * nodes * weights
                      * torch.exp(-discount * times) * survival).sum(-1)
        if self.reset_enabled:
            edges_r = x.new_tensor([float(edge) for edge in self._phase_edges])
            remaining = horizon[..., None] - (self.grid.refractory - edges_r)
            cumulative = _first_hit(x[..., None], remaining, mu, sigma)
            phase = cumulative[..., 1:] - cumulative[..., :-1]
        else:
            phase = torch.cat((hit[..., None], hit.new_zeros(hit.shape + (self.grid.phase_cells - 1,))), dim=-1)
        row = torch.cat((active, phase), dim=-1)
        reward = torch.stack((hit, discounted_hit, occupation), dim=-1)
        _nonnegative("point transition", row)
        _nonnegative("point rewards", reward)
        if bool(((row.sum(-1) - 1.0).abs() > 3e-11).any()):
            raise FloatingPointError("point transition mass is unresolved; no row normalization is permitted")
        if bool((discounted_hit > hit + 3e-12).any()):
            raise FloatingPointError("discounted first hit exceeds first hit beyond FP64 tolerance")
        return row, reward

    def _construct(self, params, reset_margin, duration):
        nodes, weights, edges = self._constants(params.mu)
        active_positions = edges[:-1, None] + (edges[1:] - edges[:-1])[:, None] * nodes
        tail_positions = self.grid.endpoint - torch.log1p(-nodes.square()) / self.grid.tail_rate
        positions = torch.cat((active_positions, tail_positions[None, :]), dim=0)
        source_weights = torch.cat((weights.expand(self.grid.active_cells, -1),
                                    (2.0 * nodes * weights)[None, :]), dim=0)
        active_rows, active_rewards = self._point_row(positions, duration, params)
        rows = [(active_rows * source_weights[..., None]).sum(1)]
        rewards = [(active_rewards * source_weights[..., None]).sum(1)]
        if not self.reset_enabled:
            phase_rows = params.mu.new_zeros(self.grid.phase_cells, self.grid.state_count)
            phase_rows[:, self.grid.active_count:] = torch.eye(self.grid.phase_cells, dtype=params.mu.dtype,
                                                               device=params.mu.device)
            rows.append(phase_rows)
            rewards.append(params.mu.new_zeros(self.grid.phase_cells, 3))
            return torch.cat(rows), torch.cat(rewards)
        dt = Fraction(str(duration))
        phase_rows, phase_rewards = [], []
        for lo, hi in zip(self._phase_edges[:-1], self._phase_edges[1:]):
            width = hi - lo
            lower, upper = max(lo, dt) - dt, hi - dt
            geometric = [0.0] * self.grid.active_count
            for left, right in zip(self._phase_edges[:-1], self._phase_edges[1:]):
                overlap = max(Fraction(0), min(upper, right) - max(lower, left))
                geometric.append(float(overlap / width))
            row = params.mu.new_tensor(geometric)
            reward = params.mu.new_zeros(3)
            released_to = min(hi, dt)
            if released_to > lo:
                span = float(released_to - lo)
                # r is the source's remaining delay. h=dt-r is the physical
                # active horizon after release; square transform resolves h=0.
                horizons = float(dt - released_to) + span * nodes.square()
                waits = float(dt) - horizons
                released_row, released_reward = self._point_row(reset_margin, horizons, params)
                release_weights = 2.0 * float((released_to - lo) / width) * nodes * weights
                row = row + (released_row * release_weights[:, None]).sum(0)
                discounts = torch.exp(-params.discount * waits)
                factors = torch.stack((torch.ones_like(discounts), discounts, discounts), dim=-1)
                reward = (released_reward * factors * release_weights[:, None]).sum(0)
            phase_rows.append(row)
            phase_rewards.append(reward)
        rows.append(torch.stack(phase_rows))
        rewards.append(torch.stack(phase_rewards))
        return torch.cat(rows), torch.cat(rewards)

    def forward(self, log_boundary, mu, sigma, absolute_reset, dt, discount):
        """Build one differentiable table; dt is a scalar fixed physical time."""
        params = PhysicalParameters(log_boundary, mu, sigma, absolute_reset, discount)
        margin = _check_parameters(params)
        if isinstance(dt, torch.Tensor):
            if dt.numel() != 1 or dt.requires_grad:
                raise ValueError("table dt must be scalar fixed data, without requires_grad")
            duration = float(dt.detach().cpu())
        elif isinstance(dt, bool) or not isinstance(dt, (int, float)):
            raise ValueError("table dt must be a finite real")
        else:
            duration = float(dt)
        if not math.isfinite(duration) or not 0.0 <= duration <= self.grid.refractory:
            raise ValueError("one physical propagation requires 0<=dt<=refractory")
        if duration == 0.0:
            matrix = torch.eye(self.grid.state_count, dtype=mu.dtype, device=mu.device)
            rewards = mu.new_zeros(self.grid.state_count, 3)
        else:
            matrix, rewards = self._construct(params, margin, duration)
        _nonnegative("transition matrix", matrix)
        _nonnegative("reward matrix", rewards)
        if bool(((matrix.sum(-1) - 1.0).abs() > 5e-11).any()):
            raise FloatingPointError("quadrature transition does not preserve unit mass; refine explicitly")
        active_probability = matrix[:, :self.grid.active_count].sum(-1)
        call = (self.active_reward * rewards[:, 2] + self.hit_reward * rewards[:, 1]
                + self.terminal_reward * torch.exp(-discount * duration) * active_probability)
        return OperatorTable(matrix, rewards, call, rewards[:, 0], self._margin_feature(mu),
                             duration, active_probability)

    def advance(self, probability, content_mass, dt, params):
        """Transport probability and marked content with exactly the same P.

        This method owns no clock and does not change or normalize observations.
        An enclosing network must enforce the static-parameter episode snapshot.
        """
        _check_parameters(params)
        if (not isinstance(probability, torch.Tensor) or probability.dtype != torch.float64
                or probability.ndim != 2 or probability.shape[1] != self.grid.state_count
                or probability.shape[0] < 1 or probability.device != params.mu.device):
            raise ValueError("probability must be nonempty FP64 [batch,K] on the physical parameter device")
        if (not isinstance(content_mass, torch.Tensor) or content_mass.dtype != probability.dtype
                or content_mass.device != probability.device or content_mass.ndim != 3
                or content_mass.shape[:2] != probability.shape or content_mass.shape[2] < 1):
            raise ValueError("content_mass must be matching FP64 [batch,K,content] with content>=1")
        _nonnegative("input probability", probability)
        _finite("content mass", content_mass)
        times = _tensor(dt, probability)
        if times.requires_grad:
            raise ValueError("physical elapsed times are fixed data, not differentiation targets")
        if times.ndim == 0:
            times = times.expand(probability.shape[0])
        if times.shape != (probability.shape[0],):
            raise ValueError("dt must be scalar or have shape [batch]")
        if (not bool(torch.isfinite(times).all())
                or bool(((times < 0) | (times > self.grid.refractory)).any())):
            raise ValueError("each dt must satisfy 0<=dt<=refractory")
        durations, inverse = torch.unique(times, sorted=True, return_inverse=True)
        tables = [self(params.log_boundary, params.mu, params.sigma, params.absolute_reset,
                       float(duration.detach().cpu()), params.discount) for duration in durations]
        matrices = torch.stack([table.matrix for table in tables])[inverse]
        reward_matrix = torch.stack([table.rewards for table in tables])[inverse]
        call_matrix = torch.stack([table.call for table in tables])[inverse]
        moved = torch.bmm(probability[:, None, :], matrices).squeeze(1)
        marked = torch.einsum("bkc,bkj->bjc", content_mass, matrices)
        reward = (probability[..., None] * reward_matrix).sum(1)
        call = (probability * call_matrix).sum(-1)
        residual = moved.sum(-1) - probability.sum(-1)
        _nonnegative("advanced probability", moved)
        _finite("advanced content", marked)
        return FlowReceipt(moved, marked, reward[:, 0], reward[:, 1], reward[:, 2],
                           call, reward[:, 0], moved @ tables[0].margin, residual)
