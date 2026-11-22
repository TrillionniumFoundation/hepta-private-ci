"""Causal sensor encoders with the same timestamp and next-sensor interface.

The gated-delta arm implements the published recurrent delta update in ordinary
PyTorch. It is not the full Gated DeltaNet architecture or its optimized kernel.
CfC is the official ncps implementation; absence is an error, never a substitute.
"""

import importlib.metadata
import math

import torch
from torch import nn
from torch.nn import functional as F

KINDS = (
    "tanh",
    "gru",
    "lif_surrogate",
    "official_cfc",
    "gated_delta_reference",
    "causal_transformer",
)


class StreamBaseline(nn.Module):
    """Small reference models; all layers and the common SSL head are trained."""

    def __init__(self, kind, input_size, width, clock_scale_seconds):
        super().__init__()
        if kind not in KINDS or not 2 <= width <= 64 or input_size < 1:
            raise ValueError("unsupported streaming model or width")
        if not math.isfinite(clock_scale_seconds) or clock_scale_seconds <= 0:
            raise ValueError("positive clock scale required")
        self.kind, self.input_size, self.width = kind, input_size, width
        self.clock_scale_seconds = clock_scale_seconds
        inputs = input_size + 1
        if kind == "gru":
            self.cell = nn.GRUCell(inputs, width)
        elif kind in ("tanh", "lif_surrogate"):
            self.input = nn.Linear(inputs, width)
            self.recurrent = nn.Linear(width, width, bias=False)
            if kind == "lif_surrogate":
                self.raw_tau = nn.Parameter(torch.zeros(width))
                self.raw_threshold = nn.Parameter(torch.zeros(width))
        elif kind == "official_cfc":
            if importlib.metadata.version("ncps") != "1.0.1":
                raise RuntimeError("the study binds official ncps==1.0.1")
            from ncps.torch import CfC

            self.cell = CfC(
                inputs,
                width,
                batch_first=True,
                return_sequences=True,
                backbone_units=8,
                backbone_layers=1,
                backbone_dropout=0.0,
            )
        elif kind == "gated_delta_reference":
            self.qkv_gates = nn.Linear(inputs, 3 * width + 2)
        else:
            self.input = nn.Linear(inputs, width)
            self.block = nn.TransformerEncoderLayer(
                width,
                1,
                dim_feedforward=2 * width,
                dropout=0.0,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
        self.feature_width = width
        self.predictor = nn.Linear(width, input_size)
        self.double()

    def encode_batch(self, windows, intervals):
        """Use only observations at or before each prediction origin."""
        dt = torch.as_tensor(intervals, dtype=windows.dtype, device=windows.device)
        if (
            windows.ndim != 3
            or windows.shape[-1] != self.input_size
            or dt.shape != windows.shape[:2]
            or not bool(torch.isfinite(windows).all())
            or not bool(torch.isfinite(dt).all())
            or bool((dt <= 0).any())
        ):
            raise ValueError(
                "finite windows and positive individual durations required"
            )
        elapsed = dt / self.clock_scale_seconds
        inputs = torch.cat((windows, torch.log1p(elapsed[..., None])), -1)
        batch, length, _ = inputs.shape
        if self.kind == "official_cfc":
            spans = elapsed[..., None].expand(-1, -1, self.width)
            return self.cell(inputs, timespans=spans)[0]
        if self.kind == "causal_transformer":
            # t_j is the known next-query time; no future sensor enters a token.
            angles = elapsed.cumsum(1)[..., None] * torch.exp(
                -math.log(10000.0)
                * torch.arange(self.width, device=inputs.device, dtype=inputs.dtype)
                / self.width
            )
            positions = torch.where(
                (torch.arange(self.width, device=inputs.device) % 2) == 0,
                angles.sin(),
                angles.cos(),
            )
            mask = torch.ones(
                length, length, dtype=torch.bool, device=inputs.device
            ).triu(1)
            return self.block(self.input(inputs) + positions, src_mask=mask)
        state = inputs.new_zeros(batch, self.width)
        outputs = []
        if self.kind == "lif_surrogate":
            voltage, refractory = torch.zeros_like(state), torch.zeros_like(state)
        if self.kind == "gated_delta_reference":
            memory = inputs.new_zeros(batch, self.width, self.width)
        for index in range(length):
            item, step = inputs[:, index], elapsed[:, index, None]
            if self.kind == "gru":
                state = self.cell(item, state)
            elif self.kind == "tanh":
                state = torch.tanh(self.input(item) + self.recurrent(state))
            elif self.kind == "lif_surrogate":
                active = (step - refractory).clamp_min(0)
                tau, threshold = (
                    0.05 + F.softplus(self.raw_tau),
                    0.5 + self.raw_threshold.sigmoid(),
                )
                drive = 0.5 + F.softplus(self.input(item) + self.recurrent(state))
                decay = torch.exp(-active / tau)
                voltage = decay * voltage + (1 - decay) * drive
                soft = torch.sigmoid(10 * (voltage - threshold))
                hard = ((voltage >= threshold) & (active > 0)).to(inputs)
                spike = (soft + (hard - soft).detach()) * (active > 0).to(inputs)
                voltage = voltage * (1 - spike)
                refractory = torch.where(
                    hard.bool(),
                    torch.full_like(refractory, 0.2),
                    (refractory - step).clamp_min(0),
                )
                state = torch.exp(-step / 2.0) * state + spike
            else:
                projected = self.qkv_gates(item)
                q, k, v = projected[:, : 3 * self.width].split(self.width, -1)
                q, k = F.normalize(q, dim=-1), F.normalize(k, dim=-1)
                beta = projected[:, -2:-1].sigmoid()
                decay = torch.exp(-F.softplus(projected[:, -1:]) * step)
                memory = decay[..., None] * memory
                residual = v - torch.einsum("bi,bij->bj", k, memory)
                memory = memory + beta[..., None] * k[..., None] * residual[:, None]
                state = torch.einsum("bi,bij->bj", q / math.sqrt(self.width), memory)
            outputs.append(state)
        return torch.stack(outputs, 1)

    def encode_one(self, sequence, intervals):
        return self.encode_batch(sequence[None], torch.as_tensor(intervals)[None])[0]

    def next_sensor_loss(self, windows, intervals):
        features = self.encode_batch(windows[:, :-1], intervals[:, :-1])
        return (self.predictor(features) - windows[:, 1:]).square().mean()

    @torch.no_grad()
    def representations(self, windows, intervals):
        features = self.encode_batch(windows, intervals)
        dt = torch.as_tensor(intervals, dtype=features.dtype, device=features.device)
        pool = (features * dt[..., None]).sum(1) / dt.sum(1, keepdim=True)
        loss = (self.predictor(features[:, :-1]) - windows[:, 1:]).square().mean()
        return torch.cat((features[:, -1], pool), -1), float(loss)

    def identity(self, *, sequence_length=16):
        state_elements = {
            "tanh": self.width,
            "gru": self.width,
            "lif_surrogate": 3 * self.width,
            "official_cfc": self.width,
            "gated_delta_reference": self.width**2,
            "causal_transformer": sequence_length * (self.input_size + 1),
        }[self.kind]
        return {
            "kind": self.kind,
            "width": self.width,
            "input_size": self.input_size,
            "parameters": sum(p.numel() for p in self.parameters()),
            "persistent_state_bytes_per_stream": state_elements * 8,
            "state_account": "FP64 recurrent state; transformer retains raw prefix, not optimized KV",
            "training_tape_excluded_from_state": True,
            "embedding_width": 2 * self.width,
            "pool": "last and physical-duration-weighted endpoint features",
            "lif_event_semantics": (
                "endpoint single-event surrogate: at most one spike per source interval; "
                "no exact within-interval event-time or repeated-event solution"
                if self.kind == "lif_surrogate"
                else None
            ),
            "implementation": "official ncps==1.0.1"
            if self.kind == "official_cfc"
            else "explicit CPU reference implementation",
        }


def matched_width(kind, input_size, clock_scale_seconds, target=600):
    """Capacity choice uses parameter counts only, never dataset labels or scores."""
    choices = []
    for width in range(2, 33):
        model = StreamBaseline(kind, input_size, width, clock_scale_seconds)
        count = sum(p.numel() for p in model.parameters())
        choices.append((abs(count - target), width, count))
    _, width, count = min(choices)
    if abs(count - target) / target > 0.15:
        raise ValueError(f"cannot match declared parameter band for {kind}: {count}")
    return width, count
