"""A small irregular-sensor encoder with explicit clock and missingness semantics.

This is a research input adapter, not a multimodal foundation-model encoder.
Timestamps are physical times in one caller-declared unit. A missing observation
advances time; a padded position does not. Missing values are never interpreted
as observed zeros. The caller must carry ``last_timestamp`` between chunks.
"""

from dataclasses import dataclass
import math

import torch
from torch import Tensor, nn


@dataclass(frozen=True)
class EncodedStream:
    """An encoded chunk; all masks are per-example, not batch-wide decisions."""

    features: Tensor  # [batch, time, embedding]
    dt: Tensor  # [batch, time], in the same physical unit as timestamps
    observed: Tensor  # [batch, time], at least one genuinely observed channel
    valid: Tensor  # [batch, time], false means padding rather than missing data
    last_timestamp: Tensor  # [batch], retains at least the incoming clock precision
    start_timestamp: Tensor  # [batch], exact predecessor for this chunk


class IrregularSensorEncoder(nn.Module):
    """Encode bounded-size sensor vectors, channel masks and actual time gaps.

    ``start_time`` is the timestamp of the retained recurrent state. It defaults
    to zero only for a deliberately new stream. Equal timestamps are allowed:
    they describe successive observations with zero physical propagation. Time
    may have a different floating dtype from values so large absolute timestamps
    can be differenced in FP64 before casting *durations* to the model dtype.
    """

    def __init__(
        self,
        input_dim: int,
        embedding_dim: int,
        *,
        value_scale: Tensor | None = None,
        time_scale: float = 1.0,
    ) -> None:
        super().__init__()
        if input_dim < 1 or embedding_dim < 1:
            raise ValueError("input_dim and embedding_dim must be positive")
        if not math.isfinite(time_scale) or time_scale <= 0:
            raise ValueError("time_scale must be a finite positive physical duration")
        self.input_dim = int(input_dim)
        self.embedding_dim = int(embedding_dim)
        self.time_scale = float(time_scale)
        scale = torch.ones(input_dim) if value_scale is None else value_scale.detach().clone()
        if scale.shape != (input_dim,) or not scale.is_floating_point():
            raise ValueError("value_scale must be a floating vector with input_dim entries")
        if not bool(torch.isfinite(scale).all()) or not bool((scale > 0).all()):
            raise ValueError("value_scale must be finite and positive")
        self.register_buffer("value_scale", scale)
        self.projection = nn.Sequential(
            nn.Linear(2 * input_dim + 1, embedding_dim),
            nn.Tanh(),
            nn.Linear(embedding_dim, embedding_dim),
            nn.Tanh(),
        )

    def forward(
        self,
        values: Tensor,
        timestamps: Tensor,
        observation_mask: Tensor | None = None,
        valid_mask: Tensor | None = None,
        *,
        start_time: Tensor | float | None = None,
    ) -> EncodedStream:
        if values.ndim != 3 or values.shape[-1] != self.input_dim:
            raise ValueError("values must have shape [batch,time,input_dim]")
        if values.dtype not in (torch.float32, torch.float64):
            raise TypeError("sensor values must use float32 or float64")
        batch, steps, _ = values.shape
        if batch < 1 or steps < 1:
            raise ValueError("empty batches/chunks are not observations")
        if timestamps.shape != (batch, steps):
            raise ValueError("timestamps must have shape [batch,time]")
        if timestamps.dtype not in (torch.float32, torch.float64):
            raise TypeError("timestamps must use float32 or float64")
        if timestamps.device != values.device:
            raise ValueError("timestamps and values must use the same device")
        if self.value_scale.device != values.device or self.value_scale.dtype != values.dtype:
            raise ValueError("move the encoder to the values device and dtype before use")
        if observation_mask is None:
            observation_mask = torch.ones_like(values, dtype=torch.bool)
        if valid_mask is None:
            valid_mask = torch.ones((batch, steps), dtype=torch.bool, device=values.device)
        if observation_mask.shape != values.shape or observation_mask.dtype != torch.bool:
            raise ValueError("observation_mask must be bool and have the values shape")
        if valid_mask.shape != (batch, steps) or valid_mask.dtype != torch.bool:
            raise ValueError("valid_mask must be bool and have shape [batch,time]")
        if observation_mask.device != values.device or valid_mask.device != values.device:
            raise ValueError("all masks must use the values device")

        observed_channels = observation_mask & valid_mask.unsqueeze(-1)
        if not bool(torch.isfinite(values[observed_channels]).all()):
            raise ValueError("an observed sensor value is not finite")
        if not bool(torch.isfinite(timestamps[valid_mask]).all()):
            raise ValueError("a valid timestamp is not finite")
        if start_time is None:
            previous = timestamps.new_zeros(batch)
        elif isinstance(start_time, Tensor):
            if start_time.device != timestamps.device:
                raise ValueError("start_time and timestamps must use the same device")
            if start_time.dtype not in (torch.float32, torch.float64):
                raise TypeError("start_time tensors must use float32 or float64")
            clock_dtype = torch.promote_types(timestamps.dtype, start_time.dtype)
            timestamps = timestamps.to(dtype=clock_dtype)
            previous = start_time.to(dtype=clock_dtype)
            if previous.ndim == 0:
                previous = previous.expand(batch)
            if previous.shape != (batch,):
                raise ValueError("start_time must be scalar or have shape [batch]")
        else:
            # A Python float is double precision. Preserve it rather than
            # rounding a retained fractional clock down to an FP32 timestamp.
            timestamps = timestamps.to(dtype=torch.float64)
            previous = timestamps.new_full((batch,), float(start_time))
        if not bool(torch.isfinite(previous).all()):
            raise ValueError("start_time must be finite")
        start = previous
        durations = []
        for index in range(steps):
            # Select before subtracting: NaN padding must not pollute a clock or
            # autograd graph. Missing-but-valid samples still take this branch.
            current = torch.where(valid_mask[:, index], timestamps[:, index], previous)
            duration = current - previous
            if bool((duration < 0).any()) or not bool(torch.isfinite(duration).all()):
                raise ValueError("valid timestamps must be nondecreasing per example")
            durations.append(duration)
            previous = current
        dt = torch.stack(durations, dim=1).to(dtype=values.dtype)
        if not bool(torch.isfinite(dt).all()):
            raise ValueError("duration is outside the model dtype's finite range")
        clean_values = torch.where(observed_channels, values, torch.zeros_like(values))
        scaled = clean_values / self.value_scale
        time_feature = torch.log1p(dt / self.time_scale).unsqueeze(-1)
        inputs = torch.cat((scaled, observed_channels.to(values.dtype), time_feature), dim=-1)
        features = self.projection(inputs)
        observed = observed_channels.any(dim=-1)
        # The time gap acts through propagation even when there is no observed
        # channel. A learned projection bias must not invent an observation.
        features = torch.where(observed.unsqueeze(-1), features, torch.zeros_like(features))
        return EncodedStream(features, dt, observed, valid_mask, previous, start)
