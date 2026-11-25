"""Prospective acceleration; same local QVI and finite population law.

The safeguarded Newton root retains an implicit first derivative. The optional
interval cache lives within one forward call and reuses the same autograd nodes
only when the exact drift/boundary/cost tensor objects are retained by a slow
control tick. It does not detach, approximate or cache across optimizer updates.
"""

import math
import torch
from torch.autograd.function import once_differentiable

from qualification.hcsn_adaptive.uniformized_flow import ActionBudget
from qualification.hcsn_smallnet_20261124.model import _QVI, _residual
from .models import SignedHCSN


class NewtonQVI(torch.autograd.Function):
    @staticmethod
    def forward(ctx, mu, cost, absolute, sigma, rho, eta, gain, maintenance):
        args = (sigma, rho, eta, gain, maintenance)
        low, high = absolute.expand_as(mu)-8, absolute.expand_as(mu)-1e-4
        if not bool((_residual(low, mu, cost, absolute, *args)[0] < 0).all()
                    & (_residual(high, mu, cost, absolute, *args)[0] > 0).all()):
            raise ValueError("QVI root outside bracket")
        point = low
        for _ in range(12):
            value, slope = _residual(point, mu, cost, absolute, *args)
            low = torch.where(value < 0, point, low)
            high = torch.where(value > 0, point, high)
            proposal = point - value / slope
            valid = torch.isfinite(proposal) & (proposal >= low) & (proposal <= high)
            point = torch.where(value == 0, point, torch.where(valid, proposal, (low+high)/2))
        value, slope = _residual(point, mu, cost, absolute, *args)
        tolerance = 3e-13 if mu.dtype == torch.float64 else 3e-6
        # R/R' is the Newton correction size, used here as a residual gate,
        # not a rigorous root-error bound. Independent reference checks qualify
        # its numerical error. A strict real-arithmetic bound would use a lower
        # bound on R' across the bracket (and still exclude floating roundoff).
        if not bool(torch.isfinite(point).all() & torch.isfinite(slope).all()
                    & (slope > 0).all() & ((value/slope).abs() <= tolerance).all()
                    & (point < absolute-1e-4).all()):
            raise FloatingPointError("safeguarded Newton root failed residual/domain gate")
        ctx.save_for_backward(point, mu, cost, absolute)
        ctx.args = args
        return point

    @staticmethod
    @once_differentiable
    def backward(ctx, upstream):
        boundary, mu, cost, absolute = ctx.saved_tensors
        with torch.enable_grad():
            values = tuple(x.detach().requires_grad_() for x in (mu, cost, absolute))
            residual, slope = _residual(boundary.detach(), *values, *ctx.args)
            gradients = torch.autograd.grad(residual, values, -upstream/slope.detach())
        return (*gradients, None, None, None, None, None)


@torch.jit.script
def scripted_action(matrix: torch.Tensor, vectors: torch.Tensor, rate: torch.Tensor,
                    duration: float, column: bool, substeps: int, order: int):
    transition = torch.eye(matrix.shape[-1], dtype=matrix.dtype, device=matrix.device) + matrix/rate
    duration_step = duration/substeps
    mean, initial = rate*duration_step, torch.exp(-rate*duration_step)
    result = vectors
    for _ in range(substeps):
        term, weight = result, initial
        total = weight*term
        for k in range(1, order+1):
            if column:
                term = transition @ term
            else:
                term = term @ transition
            weight = weight*mean/k
            total = total+weight*term
        result = total
    return result


class FastSignedHCSN(SignedHCSN):
    def __init__(self, config, *, scripted=False, interval_cache=True):
        self.scripted = scripted
        self.interval_cache = interval_cache
        self._interval = None
        super().__init__(config)

    def qvi_boundary(self, drift, cost):
        c = self.config
        eta = math.exp(-c.stages*math.log1p(c.discount*c.refractory/c.stages))
        args = (drift, cost, self.reset_absolute, c.sigma, c.discount,
                eta, c.gain, c.maintenance)
        if not hasattr(self, "fixed_boundary"):
            return _QVI.apply(*args)
        result = NewtonQVI.apply(*args)
        nominal = (drift == c.base_drift) & (cost == c.cost)
        # Equal nominal laws must preserve the exact stored boundary. An ulp
        # drift across a zero remap can otherwise choose a one-sided derivative
        # instead of the declared symmetric knot derivative. Only the forward
        # representation is canonicalized; the implicit root derivative stays.
        canonical = result+(self.fixed_boundary.expand_as(result)-result).detach()
        return torch.where(nominal, canonical, result)

    def forward(self, *args, **kwargs):
        if self._interval is not None:
            raise RuntimeError("concurrent or reentrant forward on one cached model is unsupported")
        self._interval = {}
        try:
            return super().forward(*args, **kwargs)
        finally:
            self._interval = None

    def _generator(self, drift, boundary):
        if self._interval is None:
            return super()._generator(drift, boundary)
        key = (id(drift), id(boundary))
        if self.interval_cache and self._interval.get("generator_key") == key:
            return self._interval["generator"]
        value = super()._generator(drift, boundary)
        if self.interval_cache:
            self._interval.update(generator_key=key, generator=value,
                                  generator_inputs=(drift, boundary))
        return value

    def _action(self, matrix, vectors, rate, duration, column=False):
        if not self.scripted or self.config.backend != "uniformized":
            return super()._action(matrix, vectors, rate, duration, column)
        plan = ActionBudget().plan(float(rate.detach()), duration, max(1., float(rate.detach())))
        return scripted_action(matrix, vectors, rate, duration, column,
                               plan["substeps"], plan["order"])

    def _flow(self, density, jump, generator, event, boundary, cost):
        if not self.interval_cache or self._interval is None:
            return super()._flow(density, jump, generator, event, boundary, cost)
        c, size = self.config, generator.shape[-1]
        key = (id(generator), id(event), id(boundary), id(cost))
        if self._interval.get("flow_key") != key:
            active = torch.cat((event.new_ones(c.bins), event.new_zeros(c.stages+1)))
            rewards = torch.stack((event, active.expand_as(event)), -1)
            augmented = torch.cat((torch.cat((generator, rewards), -1),
                                   event.new_zeros(*event.shape[:-1], 2, size+2)), -2)
            h = c.extent/c.bins
            rate = event.new_tensor(max(c.stages/c.refractory,
                3*c.sigma**2/(2*h*h)+(abs(c.base_drift)+c.drift_scale)/h))
            destination = torch.eye(size, dtype=event.dtype, device=event.device)[c.bins]
            killed = generator-event[..., None]*destination
            first = torch.cat((torch.cat((killed, event[..., None]), -1),
                               event.new_zeros(*event.shape[:-1], 1, size+1)), -2)
            terminal = event.new_zeros(*event.shape[:-1], size+1, 1)
            terminal[..., -1, 0] = 1
            first_probability = self._action(first, terminal, rate, c.dt, column=True)[..., :size, 0]
            _, centers = self._geometry(event)
            reward = torch.cat((c.gain*(boundary[..., None]+centers)-c.maintenance,
                                event.new_zeros(*event.shape[:-1], c.stages+1)), -1)-cost[..., None]*event
            value = torch.linalg.solve(c.discount*torch.eye(size, dtype=event.dtype, device=event.device)-generator,
                                       reward[..., None])[..., 0]
            self._interval.update(flow_key=key, flow_inputs=(generator, event, boundary, cost),
                flow=(augmented, rate, destination, first_probability, centers, value))
        augmented, rate, destination, first_probability, centers, value = self._interval["flow"]
        padded = torch.cat((density, density.new_zeros(*density.shape[:-1], 2)), -1)
        result = self._action(augmented, padded, rate, c.dt)
        next_density, increments = result[..., :size], result[..., size:]
        never_hit = density[..., 0, :]-jump[..., :1]*destination
        risk = jump[..., 0]+(never_hit*first_probability).sum(-1)
        continuation = (next_density[..., 0, :]*value).sum(-1)
        margin = (next_density[..., 0, :c.bins]*centers).sum(-1)/c.extent
        return next_density, jump+increments[..., 0], continuation, risk, margin
