"""A causal bridge between the affine Brownian QVI and the finite population flow.

The QVI optimizes a frozen-coefficient Brownian forecast. The executed flow
has a truncated spatial grid and Erlang refractory phases. Each new observation
can change the next forecast. Absolute release/reset state stays fixed in all
arms, including when the threshold changes at an observation edge.
"""

import math

import torch
from torch import nn

from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig, FlowState
from qualification.hcsn_adaptive.flow_semantics import FlowSemantics
from qualification.hcsn_differentiable.neural_control import (
    boundary_residual,
    optimal_boundary,
)


def _batched_boundary(task):
    """Same #6739 residual and bisection, broadcast across frozen forecasts."""
    if task.numel() == 8:
        return optimal_boundary(task.reshape(8)).reshape(task.shape[1:])
    with torch.no_grad():
        lo, hi = task[3] - 8, task[3] - 1e-4
        if not bool(((boundary_residual(lo, task) < 0) & (boundary_residual(hi, task) > 0)).all()):
            raise ValueError("QVI optimum outside the original interior bracket")
        for _ in range(64):
            mid = (lo + hi) / 2
            below = boundary_residual(mid, task) < 0
            lo, hi = torch.where(below, mid, lo), torch.where(below, hi, mid)
        root = (lo + hi) / 2
    if not torch.is_grad_enabled() or not task.requires_grad:
        return root
    # The residual is componentwise in independent examples. R_b is positive
    # at every allowed root; this produces the same first derivative as #6739.
    point = root.detach().requires_grad_()
    residual = boundary_residual(point, task)
    derivative = torch.autograd.grad(residual.sum(), point, retain_graph=True)[0]
    if not bool((torch.isfinite(derivative) & (derivative > 0)).all()):
        raise FloatingPointError("unresolved QVI boundary gradient")
    return root - (residual - residual.detach()) / derivative.detach()


class _AbsoluteResetInterval:
    """Step-local, reentrant view of the original #6958 physical flow."""

    def __init__(self, flow, boundary, absolute_reset):
        self.flow = flow
        self.relative_reset = absolute_reset - boundary

    def __getattr__(self, name):
        return getattr(self.flow, name)

    def reset_weights(self):
        c = self.flow.config
        centers = self.flow.centers
        gap = self.relative_reset
        if not bool(((gap >= centers[0]) & (gap <= centers[-1])).all()):
            raise ValueError("absolute reset outside supported interpolation centers")
        weights = torch.relu(1 - (centers - gap[:, None]).abs() / (c.extent / c.bins))
        return weights / weights.sum(-1, keepdim=True)

    def _generator(self, drift):
        generator, event, spatial = self.flow._generator(drift)
        c = self.flow.config
        reset = self.reset_weights()
        # Only the last refractory phase's release destination changes; all
        # other rates, first-passage transitions and write laws remain upstream.
        row = c.bins + c.stages - 1
        exit_row = torch.cat((reset * (c.stages / c.refractory), generator[:, row, c.bins:]), -1)
        revised = torch.cat((generator[:, :row], exit_row[:, None], generator[:, row + 1:]), 1)
        return revised, event, spatial


class RetrievalFlow(nn.Module):
    """Return #6958's named physical channels at every prefix, in FP64."""

    def __init__(self, input_size, content_size=4, mode="qvi", *, maintenance=0.4,
                 spike_cost=0.3, rho=0.2, reset=1.0, delay=0.25):
        super().__init__()
        if mode not in ("fixed", "learned", "qvi"):
            raise ValueError("mode must be fixed, learned or qvi")
        if not all(math.isfinite(v) for v in (maintenance, spike_cost, rho, reset, delay)):
            raise ValueError("finite task parameters required")
        self.mode = mode
        self.register_buffer("task", torch.tensor(
            [-0.15, 0.35, rho, reset, delay, 1.0, maintenance, spike_cost],
            dtype=torch.float64,
        ))
        self.register_buffer("nominal_boundary", optimal_boundary(self.task).detach())
        self.flow = BatchedFlow(FlowConfig(
            input_size=input_size, content_size=content_size, bins=6, stages=3, extent=2.,
            sigma=0.35, base_drift=-0.15, drift_scale=0.20,
            reset_margin=float(reset-self.nominal_boundary), refractory=float(delay),
            discount=float(rho), gain=1., maintenance=float(maintenance), spike_cost=float(spike_cost),
            upper_mode="reflecting",
        ))
        self.semantics = FlowSemantics("event_mask")
        self.feature_names = self.flow.physical_feature_names
        self.edit_names = ("drive_bias", "mark_bias")
        if mode == "learned":
            self.boundary_logit = nn.Parameter(torch.zeros((), dtype=torch.float64))
            self.edit_names += ("boundary_logit",)
        self.register_buffer("mark_direction", self.task.new_tensor(
            [(-1.) ** i for i in range(content_size)]
        ))

    def initial_edit_vector(self):
        return self.task.new_zeros(len(self.edit_names))

    def features_with_edit(self, theta, x, dt):
        """Functional edits to actual nonlinear weights; incumbent stays reusable."""
        if theta.shape != (len(self.edit_names),) or theta.dtype != self.task.dtype:
            raise ValueError("edit coordinates require one FP64 scalar per named direction")
        selected = {
            "flow.drive.bias": self.flow.drive.bias + theta[0],
            "flow.writer.bias": self.flow.writer.bias + self.mark_direction * theta[1],
        }
        if self.mode == "learned":
            selected["boundary_logit"] = self.boundary_logit + theta[2]
        return torch.func.functional_call(self, selected, (x, dt))

    def boundaries(self, drift):
        if self.mode == "fixed":
            return self.nominal_boundary.expand_as(drift)
        if self.mode == "learned":
            # Match nominal policy at zero while keeping reset interpolation interior.
            gap = self.task[3] - self.nominal_boundary
            distance = torch.minimum(gap-self.flow.centers[0], self.flow.centers[-1]-gap)
            return (self.nominal_boundary + 0.9*distance*self.boundary_logit.tanh()).expand_as(drift)
        rest = self.task[1:].reshape((7,) + (1,) * drift.ndim).expand((7,) + drift.shape)
        return _batched_boundary(torch.cat((drift.unsqueeze(0), rest)))

    def forward(self, x, dt):
        if (x.ndim != 3 or min(x.shape) < 1 or x.shape[2] != self.flow.config.input_size
                or x.dtype != torch.float64 or x.device != self.task.device
                or not bool(torch.isfinite(x).all())):
            raise ValueError("finite FP64 [batch,time,declared input size] required")
        if (dt.shape != x.shape[:2] or not dt.is_floating_point() or dt.requires_grad
                or not bool(torch.isfinite(dt).all())):
            raise ValueError("timestamps require finite, observed [batch,time] durations")
        seconds = dt.detach().to(device="cpu", dtype=torch.float64)
        micros = torch.round(seconds * 1e6).to(torch.int64)
        if (not bool(((micros >= 1) & (micros <= 10**9)).all())
                or not torch.allclose((micros.double() / 1e6).to(dt.dtype),
                                      dt.detach().cpu(), rtol=0, atol=1e-12)):
            raise ValueError("durations must be integer microseconds within [1, 10^9]")

        batch, steps = x.shape[:2]
        drift = self.flow.config.base_drift + self.flow.config.drift_scale * self.flow.drive(x).squeeze(-1).tanh()
        boundaries = self.boundaries(drift)
        # Project the same absolute initial point onto each arm's own grid;
        # moving a pre-binned initial density would add an extra remap error.
        previous = boundaries[:, 0]
        reset_weights = _AbsoluteResetInterval(self.flow, previous, self.task[3]).reset_weights()
        probability = torch.cat((reset_weights, x.new_zeros(batch, self.flow.config.stages + 1)), 1)
        density = torch.cat((probability[:, None], x.new_zeros(
            batch, self.flow.config.content_size, probability.shape[-1]
        )), 1)
        elapsed = torch.zeros(batch, dtype=torch.int64)
        results = []
        for t in range(steps):
            # A FlowState has one physical clock. Group by both elapsed time
            # and this step's duration; restore the original sample order.
            clocks = torch.stack((elapsed, micros[:, t]), 1)
            unique, groups = torch.unique(clocks, dim=0, return_inverse=True)
            positions, features, densities = [], [], []
            for i, (clock, interval) in enumerate(unique.tolist()):
                members = torch.where(groups == i)[0]
                for indices in members.split(self.flow.config.max_batch):
                    idx = indices.to(x.device)
                    b = boundaries[idx, t]
                    held = _AbsoluteResetInterval(self.flow, b, self.task[3])
                    state = FlowState(density[idx], previous[idx], clock, self.flow.config)
                    values, updated, _ = BatchedFlow.step_physical(
                        held, x[idx, t], state, semantics=self.semantics,
                        dt=interval / 1e6, write_mask=torch.ones_like(b),
                        boundary_override=b, drift_override=drift[idx, t],
                    )
                    positions.append(idx)
                    features.append(values)
                    densities.append(updated.density)
            order = torch.argsort(torch.cat(positions))
            results.append(torch.cat(features)[order])
            density = torch.cat(densities)[order]
            previous = boundaries[:, t]
            elapsed = elapsed + micros[:, t]
        return torch.stack(results, 1)
