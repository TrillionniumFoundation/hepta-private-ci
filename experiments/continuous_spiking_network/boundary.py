"""Causal finite-horizon task stopping, separate from a cell's natural barrier.

The observations obey y|H=+/-1 ~ N(+/-signal, noise^2). Every policy receives
the same current log odds, known signal/noise ratio, cost and remaining horizon.
The value solver uses the model's predictive mixture, never a realized label.
"""

import math

import numpy as np
import torch
from torch import Tensor, nn


def _interpolate(grid: Tensor, values: Tensor, points: Tensor) -> Tensor:
    """Batched piecewise-linear interpolation; values [B,G], points [B,...]."""
    shape = points.shape
    flat = points.reshape(points.shape[0], -1).clamp(grid[0], grid[-1])
    high = torch.searchsorted(grid, flat.contiguous()).clamp(1, grid.numel() - 1)
    low = high - 1
    weight = (flat - grid[low]) / (grid[high] - grid[low])
    result = values.gather(1, low) * (1 - weight) + values.gather(1, high) * weight
    return result.reshape(shape)


def _normal_interpolation_weights(grid: Tensor, mean: Tensor, std: Tensor) -> Tensor:
    """Integrate each linear interpolation basis exactly against a Gaussian."""
    std = std[:, None, None]
    z = (grid[None, None, :] - mean[..., None]) / std.clamp_min(1e-8)
    cdf = torch.special.ndtr(z)
    density = torch.exp(-0.5 * z.square()) / math.sqrt(2 * math.pi)
    mass = cdf[..., 1:] - cdf[..., :-1]
    moment = mean[..., None] * mass + std * (density[..., :-1] - density[..., 1:])
    spacing = grid[1:] - grid[:-1]
    left = (grid[1:] * mass - moment) / spacing
    right = (moment - grid[:-1] * mass) / spacing
    weights = torch.nn.functional.pad(left, (0, 1)) + torch.nn.functional.pad(
        right, (1, 0)
    )
    tails = torch.cat(
        (cdf[..., :1], torch.zeros_like(cdf[..., 1:-1]), 1 - cdf[..., -1:]), dim=-1
    )
    weights = (weights + tails).clamp_min(0)
    weights = weights / weights.sum(-1, keepdim=True)
    return torch.where(
        std > 0, weights, torch.eye(grid.numel(), device=grid.device, dtype=grid.dtype)
    )


class FiniteHorizonStoppingBoundary(nn.Module):
    """Differentiable Bellman reference with cached, explicit transition tables."""

    def __init__(
        self,
        grid_size: int = 129,
        log_odds_limit: float = 12.0,
        quadrature_points: int = 15,
        integration: str = "analytic",
    ):
        super().__init__()
        if grid_size < 3 or quadrature_points < 2:
            raise ValueError("grid and quadrature are too small")
        if integration not in {"analytic", "quadrature"}:
            raise ValueError("integration must be analytic or quadrature")
        self.integration = integration
        nodes, weights = np.polynomial.hermite.hermgauss(quadrature_points)
        self.register_buffer(
            "grid", torch.linspace(-log_odds_limit, log_odds_limit, grid_size)
        )
        self.register_buffer(
            "nodes", torch.tensor(nodes * math.sqrt(2), dtype=torch.float32)
        )
        self.register_buffer(
            "weights", torch.tensor(weights / math.sqrt(math.pi), dtype=torch.float32)
        )

    def table(self, snr: Tensor, cost: Tensor, max_steps: int) -> dict[str, Tensor]:
        """Precompute once per cost/SNR batch; no observations or labels needed.

        The returned tensors retain their autograd graph. Reuse a table for
        inference; rebuild it after parameter changes or before a new backward.
        Row n permits n additional paid observations. The first observation's
        cost is external if this table is evaluated after that observation.
        """
        snr, cost = torch.broadcast_tensors(snr.reshape(-1), cost.reshape(-1))
        if max_steps < 0 or bool((snr < 0).any()) or bool((cost < 0).any()):
            raise ValueError("steps, SNR and cost must be nonnegative")
        grid = self.grid.to(snr)
        nodes, weights = self.nodes.to(snr), self.weights.to(snr)
        probability = grid.sigmoid().unsqueeze(0).expand(snr.numel(), -1)
        stop = torch.maximum(probability, 1 - probability)
        increment = 2 * snr.square()
        noise = 2 * snr[:, None, None] * nodes
        plus = grid[None, :, None] + increment[:, None, None] + noise
        minus = grid[None, :, None] - increment[:, None, None] + noise
        transition = None
        if self.integration == "analytic":
            plus_weights = _normal_interpolation_weights(
                grid, grid[None, :] + increment[:, None], 2 * snr
            )
            minus_weights = _normal_interpolation_weights(
                grid, grid[None, :] - increment[:, None], 2 * snr
            )
            transition = (
                probability[..., None] * plus_weights
                + (1 - probability[..., None]) * minus_weights
            )
        values, waits = [stop], [torch.full_like(stop, -torch.inf)]
        for _ in range(max_steps):
            if transition is None:
                plus_value = (_interpolate(grid, values[-1], plus) * weights).sum(-1)
                minus_value = (_interpolate(grid, values[-1], minus) * weights).sum(-1)
                expected = probability * plus_value + (1 - probability) * minus_value
            else:
                expected = torch.bmm(transition, values[-1].unsqueeze(-1)).squeeze(-1)
            wait = -cost[:, None] + expected
            waits.append(wait)
            values.append(torch.maximum(stop, wait))
        return {
            "grid": grid,
            "values": torch.stack(values),
            "waits": torch.stack(waits),
        }

    def evaluate(
        self,
        log_odds: Tensor,
        remaining_steps: Tensor,
        table: dict[str, Tensor],
    ) -> dict[str, Tensor]:
        log_odds, remaining_steps = torch.broadcast_tensors(log_odds, remaining_steps)
        shape = log_odds.shape
        odds = log_odds.reshape(-1)
        remaining = remaining_steps.reshape(-1).long()
        if bool((remaining < 0).any()) or bool(
            (remaining >= table["values"].shape[0]).any()
        ):
            raise ValueError("remaining steps outside precomputed table")
        batch = table["values"].shape[1]
        if batch not in {1, odds.numel()}:
            raise ValueError("table batch must be one or match the number of log odds")
        rows = (
            torch.zeros_like(remaining)
            if batch == 1
            else torch.arange(batch, device=odds.device)
        )
        # Avoid interpolating -inf at n=0: that would create 0*(-inf) NaNs.
        waiting_rows = (
            table["waits"][remaining.clamp_min(1), rows]
            if table["waits"].shape[0] > 1
            else torch.zeros(
                odds.numel(),
                table["grid"].numel(),
                device=odds.device,
                dtype=odds.dtype,
            )
        )
        wait = _interpolate(table["grid"], waiting_rows, odds[:, None]).squeeze(1)
        wait = torch.where(remaining > 0, wait, torch.full_like(wait, -torch.inf))
        confidence = torch.sigmoid(odds.abs())
        advantage = confidence - wait
        return {
            "stop_value": confidence.reshape(shape),
            "wait_value": wait.reshape(shape),
            "advantage": advantage.reshape(shape),
            "value": torch.maximum(confidence, wait).reshape(shape),
            "stop": ((advantage >= 0) | (remaining == 0)).reshape(shape),
            "stop_probability": torch.sigmoid(advantage / 0.02).reshape(shape),
        }

    def forward(
        self,
        log_odds: Tensor,
        remaining_steps: Tensor,
        observation_snr: Tensor,
        wait_cost: Tensor,
    ) -> dict[str, Tensor]:
        table = self.table(
            observation_snr, wait_cost, int(remaining_steps.max().item())
        )
        return self.evaluate(log_odds, remaining_steps, table)


class StoppingPolicy(nn.Module):
    """Fixed/direct/value arms with an identical causal input contract."""

    def __init__(self, mode: str = "fixed", threshold: float = 0.85, **solver_kwargs):
        super().__init__()
        if mode not in {"fixed", "direct", "value"} or not 0.5 < threshold < 1:
            raise ValueError("unknown mode or threshold outside (0.5,1)")
        self.mode = mode
        self.register_buffer("fixed_threshold", torch.tensor(threshold))
        scaled = (threshold - 0.5) / 0.4999
        bias = torch.tensor(math.log(scaled / (1 - scaled)))
        if mode == "direct":
            self.direct_bias = nn.Parameter(bias)
            self.direct_context = nn.Parameter(torch.zeros(3))
        else:
            self.register_buffer("direct_bias", bias)
            self.register_buffer("direct_context", torch.zeros(3))
        self.solver = FiniteHorizonStoppingBoundary(**solver_kwargs)

    def forward(
        self,
        log_odds: Tensor,
        remaining_steps: Tensor,
        observation_snr: Tensor,
        wait_cost: Tensor,
        table=None,
    ) -> dict[str, Tensor]:
        if self.mode == "value":
            if table is None:
                return self.solver(
                    log_odds, remaining_steps, observation_snr, wait_cost
                )
            return self.solver.evaluate(log_odds, remaining_steps, table)
        odds, remaining, snr, cost = torch.broadcast_tensors(
            log_odds, remaining_steps, observation_snr, wait_cost
        )
        confidence = odds.abs().sigmoid()
        threshold = self.fixed_threshold.expand_as(confidence)
        if self.mode == "direct":
            features = torch.stack(
                (
                    remaining.log1p(),
                    snr.clamp_min(1e-6).log(),
                    cost.clamp_min(1e-6).log(),
                ),
                dim=-1,
            )
            threshold = 0.5 + 0.4999 * torch.sigmoid(
                self.direct_bias + features @ self.direct_context
            )
        advantage = confidence - threshold
        forced = remaining <= 0
        return {
            "threshold": threshold,
            "advantage": advantage,
            "stop": (advantage >= 0) | forced,
            "stop_probability": torch.where(
                forced, torch.ones_like(advantage), torch.sigmoid(advantage / 0.02)
            ),
        }
