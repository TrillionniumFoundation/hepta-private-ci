"""Trainable continuous dual-channel recurrent block.

Financial values are not used as physical forces. Recovery and regeneration
below are explicitly learned neural dynamics. The scalar FPT law is exact
within a frozen interval; propagation of its mean through recurrent feedback
is a mean-field approximation. High-dimensional content is retained separately.
"""

import math

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .kernels import reset_at_interval_end_mean


def _raw_positive(value: float) -> float:
    return math.log(math.expm1(value))


class _ContinuousCell(nn.Module):
    def __init__(self, width: int, mode: str, boundary_mode: str):
        super().__init__()
        self.width, self.mode, self.boundary_mode = width, mode, boundary_mode
        self.drift_input = nn.Linear(width, width, bias=False)
        self.drift_bias = nn.Parameter(torch.full((width,), 0.35))
        self.raw_diffusion = nn.Parameter(torch.full((width,), _raw_positive(0.7)))
        self.channel_gates = nn.Linear(
            2 * width, width if mode == "single" else 2 * width
        )
        self.raw_recovery = nn.Parameter(torch.full((width,), _raw_positive(0.7)))
        for name, value, enabled in (
            ("raw_regeneration", 0.7, mode != "single"),
            ("raw_adaptation", 0.2, mode != "no_adaptation"),
            ("raw_adaptation_decay", 0.3, mode != "no_adaptation"),
        ):
            initial = torch.full((width,), _raw_positive(value))
            if enabled:
                self.register_parameter(name, nn.Parameter(initial))
            else:
                self.register_buffer(name, initial)
        self.raw_content_rate = nn.Parameter(torch.full((width,), _raw_positive(0.2)))
        self.content_input = nn.Linear(width, width)
        self.content_state = nn.Linear(width, width, bias=False)
        self.output = nn.Linear(width, width, bias=False)
        self.norm = nn.LayerNorm(width)
        if boundary_mode == "direct":
            self.raw_boundary = nn.Parameter(torch.full((width,), _raw_positive(1.0)))
        else:
            self.register_buffer("fixed_boundary", torch.ones(width))

    def forward(self, x: Tensor, dt: Tensor) -> tuple[Tensor, dict[str, Tensor]]:
        batch, steps, width = x.shape
        content = x.new_zeros(batch, width)
        voltage = torch.zeros_like(content)
        adaptation = torch.zeros_like(content)
        previous_event = torch.zeros_like(content)
        diffusion = F.softplus(self.raw_diffusion) + 1e-4
        boundary = (
            F.softplus(self.raw_boundary) + 1e-4
            if self.boundary_mode == "direct"
            else self.fixed_boundary
        )
        record = {
            key: []
            for key in (
                "event_probability",
                "voltage",
                "adaptation",
                "recovery",
                "regeneration",
                "content",
                "drift",
                "pre_reset_mean",
            )
        }
        outputs = []
        for index in range(steps):
            duration = dt[:, index, None]
            signal = self.norm(x[:, index])
            gates = self.channel_gates(torch.cat((signal, content), dim=-1)).sigmoid()
            if self.mode == "single":
                recovery_gate, regeneration_gate = gates, torch.zeros_like(gates)
            else:
                recovery_gate, regeneration_gate = gates.chunk(2, dim=-1)
            recovery = F.softplus(self.raw_recovery) * recovery_gate
            regeneration = F.softplus(self.raw_regeneration) * regeneration_gate
            if self.mode == "single":
                regeneration = torch.zeros_like(regeneration)
            drift = (
                self.drift_bias
                + self.drift_input(signal).tanh()
                - recovery * voltage
                + regeneration * previous_event
                - adaptation
            )
            pre_reset_mean = voltage + duration * drift
            if self.mode == "ordinary":
                event = torch.sigmoid(
                    (duration * drift - (boundary - voltage))
                    / (diffusion * duration.clamp_min(1e-8).sqrt())
                ) * (duration > 0)
                voltage = (1 - event) * pre_reset_mean
            else:
                voltage, terms = reset_at_interval_end_mean(
                    voltage, boundary, drift, diffusion, duration
                )
                event = terms["cdf"]
            if self.mode != "no_adaptation":
                adaptation = (
                    adaptation
                    * torch.exp(-F.softplus(self.raw_adaptation_decay) * duration)
                    + F.softplus(self.raw_adaptation) * event
                )
            candidate = torch.tanh(
                self.content_input(signal) + self.content_state(content)
            )
            write = 1 - (1 - event) * torch.exp(
                -F.softplus(self.raw_content_rate) * duration
            )
            content = (1 - write) * content + write * candidate
            outputs.append(x[:, index] + self.output(content))
            values = (
                event,
                voltage,
                adaptation,
                recovery,
                regeneration,
                content,
                drift,
                pre_reset_mean,
            )
            for key, value in zip(record, values, strict=True):
                record[key].append(value)
            previous_event = torch.where(duration > 0, event, previous_event)
        aux = {key: torch.stack(value, dim=1) for key, value in record.items()}
        aux.update({"diffusion": diffusion, "boundary": boundary})
        return torch.stack(outputs, dim=1), aux


class ContinuousSpikingBlock(nn.Module):
    """Sequence-preserving block with fixed or directly trained natural barriers.

    Task-value stopping is implemented independently in ``boundary.py``.
    It is deliberately not presented as a solved endogenous natural barrier.
    """

    def __init__(
        self,
        width: int,
        depth: int = 1,
        mode: str = "dual",
        boundary_mode: str = "fixed",
    ):
        super().__init__()
        aliases = {"single_channel": "single", "ordinary_dual_gate": "ordinary"}
        mode = aliases.get(mode, mode)
        if mode not in {"dual", "single", "no_adaptation", "ordinary"}:
            raise ValueError(f"unknown cell mode: {mode}")
        if boundary_mode not in {"fixed", "direct"}:
            raise ValueError(
                "natural barrier supports fixed/direct; use StoppingPolicy for task value"
            )
        if width < 1 or depth < 1:
            raise ValueError("width and depth must be positive")
        self.layers = nn.ModuleList(
            [_ContinuousCell(width, mode, boundary_mode) for _ in range(depth)]
        )

    def forward(
        self,
        x: Tensor,
        dt: Tensor,
        context=None,
    ) -> tuple[Tensor, dict[str, Tensor]]:
        del context  # Shared backbone protocol; no hidden information is consumed.
        if x.ndim != 3 or x.shape[1] == 0:
            raise ValueError("x must have shape [batch, nonempty_time, width]")
        if dt.ndim == 3 and dt.shape[-1] == 1:
            dt = dt.squeeze(-1)
        if dt.shape != x.shape[:2] or bool((dt < 0).any()):
            raise ValueError("dt must be nonnegative with shape [batch,time]")
        aux = {}
        for layer in self.layers:
            x, aux = layer(x, dt)
        return x, aux
