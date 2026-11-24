"""Full-encoder next-sensor BP with a declared physical clock and capacity axis.

Each sensor window starts from its model-defined initial state (the HCSN reset
distribution or zero GRU hidden state). Checkpoints
are only at completed optimizer-step boundaries, with no in-flight window or AD
tape. HCSN content width is capacity; bins and phase stages stay fixed. The GRU
receives the same known intervals as log1p(dt / clock_scale_seconds).
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math

import numpy as np
import torch
from torch import nn

from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig


@dataclass(frozen=True)
class ModelConfig:
    kind: str
    input_size: int
    width: int
    clock_scale_seconds: float
    bins: int = 4
    stages: int = 2
    boundary_scale: float = 0.25
    dtype: str = "float64"

    def __post_init__(self):
        if (self.kind not in ("hcsn", "gru") or self.dtype not in ("float32", "float64")
                or type(self.input_size) is not int or not 1 <= self.input_size <= 256
                or type(self.width) is not int or not 1 <= self.width <= 64
                or type(self.bins) is not int or not 2 <= self.bins <= 64
                or type(self.stages) is not int or not 1 <= self.stages <= 128
                or not math.isfinite(self.clock_scale_seconds) or self.clock_scale_seconds <= 0
                or not math.isfinite(self.boundary_scale) or not 0 < self.boundary_scale <= 1):
            raise ValueError("invalid scale-model configuration")


class SequenceModel(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        if config.kind == "hcsn":
            s = config.clock_scale_seconds
            self.encoder = BatchedFlow(FlowConfig(
                input_size=config.input_size, content_size=config.width,
                bins=config.bins, stages=config.stages, upper_mode="reflecting",
                transport_precision="float64", sigma=0.35 / math.sqrt(s),
                base_drift=-0.15 / s, drift_scale=0.8 / s, drift_limit=4.0 / s,
                refractory=0.2 * s, discount=0.25 / s, gain=0.5 / s,
                maintenance=0.2 / s))
            self.boundary = nn.Linear(config.input_size, 1)
            self.feature_width = len(self.encoder.feature_names)
        else:
            self.encoder = nn.GRUCell(config.input_size + 1, config.width)
            self.boundary = None
            self.feature_width = config.width
        self.predictor = nn.Linear(self.feature_width, config.input_size)
        self.to(dtype=getattr(torch, config.dtype))

    def encode_one(self, sequence, intervals):
        """Causal per-window execution; unequal intervals are never averaged."""
        if (sequence.ndim != 2 or sequence.shape[1] != self.config.input_size
                or len(sequence) < 1 or len(intervals) != len(sequence)
                or not torch.isfinite(sequence).all()):
            raise ValueError("finite [time,input] sequence and one interval per event required")
        state, outputs = None, []
        for inputs, interval in zip(sequence, intervals):
            seconds = float(interval)
            micros = round(seconds * 1_000_000)
            if (not math.isfinite(seconds) or not 1 <= micros <= 10**9
                    or not math.isclose(seconds * 1_000_000, micros, rel_tol=0, abs_tol=1e-6)):
                raise ValueError("actual positive integer-microsecond intervals required")
            inputs = inputs.unsqueeze(0)
            if self.config.kind == "hcsn":
                boundary = self.config.boundary_scale * self.boundary(inputs).tanh().squeeze(-1)
                features, state, _ = self.encoder.step(inputs, state, dt=seconds,
                                                       boundary_override=boundary)
            else:
                timing = inputs.new_full((1, 1), math.log1p(seconds / self.config.clock_scale_seconds))
                state = self.encoder(torch.cat((inputs, timing), -1), state)
                features = state
            outputs.append(features.squeeze(0))
        return torch.stack(outputs)

    def next_sensor_loss(self, windows, intervals):
        if windows.ndim != 3 or windows.shape[1] < 2 or len(windows) != len(intervals):
            raise ValueError("next-sensor learning requires [batch,time>=2,input]")
        losses = []
        for sequence, timing in zip(windows, intervals):
            features = self.encode_one(sequence[:-1], timing[:-1])
            losses.append((self.predictor(features) - sequence[1:]).square().mean())
        loss = torch.stack(losses).mean()
        if not torch.isfinite(loss):
            raise FloatingPointError("nonfinite self-supervised loss")
        return loss

    @torch.no_grad()
    def representations(self, windows, intervals):
        embeddings, losses = [], []
        for sequence, timing in zip(windows, intervals):
            features = self.encode_one(sequence, timing)
            embeddings.append(torch.cat((features[-1], features.mean(0))))
            losses.append((self.predictor(features[:-1]) - sequence[1:]).square().mean())
        result, loss = torch.stack(embeddings), torch.stack(losses).mean()
        if not torch.isfinite(result).all() or not torch.isfinite(loss):
            raise FloatingPointError("nonfinite frozen encoder representation")
        return result, float(loss)

    def identity(self):
        return {"config": asdict(self.config), "all_trainable_parameters": sum(p.numel() for p in self.parameters()),
                "encoder_parameters": sum(p.numel() for name, p in self.named_parameters() if not name.startswith("predictor.")),
                "prediction_head_parameters": sum(p.numel() for p in self.predictor.parameters()),
                "trainable_names": [name for name, p in self.named_parameters() if p.requires_grad],
                "embedding_width": 2 * self.feature_width,
                "clock": "actual seconds; common fixed train-only clock scale",
                "state_boundary": "reset between independent windows; no in-flight state at checkpoint",
                "hcsn_upper_boundary": "reflecting finite-cell approximation" if self.config.kind == "hcsn" else None,
                "transport_dtype": "torch.float64" if self.config.kind == "hcsn" else str(next(self.parameters()).dtype)}


def tensor_map_digest(values):
    digest = hashlib.sha256()
    for name, value in sorted(values.items()):
        tensor = value.detach().cpu().contiguous()
        descriptor = json.dumps([name, str(tensor.dtype), list(tensor.shape)]).encode()
        digest.update(len(descriptor).to_bytes(8, "big"))
        digest.update(descriptor)
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def validate_split(data, input_size):
    x, y, dt = data["x"], data["y"], data["dt"]
    if (x.ndim != 3 or x.shape[2] != input_size or x.shape[1] < 2
            or y.ndim != 2 or len(y) != len(x) or dt.shape != x.shape[:2]
            or any(not np.isfinite(value).all() for value in (x, y, dt))):
        raise ValueError("invalid finite sensor split")
    micros = np.rint(dt * 1_000_000)
    if (np.any(micros < 1) or np.any(micros > 10**9)
            or not np.allclose(micros, dt * 1_000_000, rtol=0, atol=1e-6)):
        raise ValueError("invalid physical timestamps")
