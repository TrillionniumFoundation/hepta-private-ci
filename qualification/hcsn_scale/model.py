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
from .feedback import (ContentFeedback, FEEDBACK_MODES, FEATURE_BANKS, POOLING_MODES,
                       pool_features, pooled_feature_names, select_feature_bank)


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
    write_law: str = "legacy"
    write_rate: float = 0.0
    feedback_mode: str = "legacy"
    feedback_gain: float = 0.5
    feature_bank: str = "same_generator"
    pooling: str = "legacy"

    def __post_init__(self):
        if (self.kind not in ("hcsn", "gru") or self.dtype not in ("float32", "float64")
                or type(self.input_size) is not int or not 1 <= self.input_size <= 256
                or type(self.width) is not int or not 1 <= self.width <= 64
                or type(self.bins) is not int or not 2 <= self.bins <= 64
                or type(self.stages) is not int or not 1 <= self.stages <= 128
                or not math.isfinite(self.clock_scale_seconds) or self.clock_scale_seconds <= 0
                or not math.isfinite(self.boundary_scale) or not 0 < self.boundary_scale <= 1):
            raise ValueError("invalid scale-model configuration")
        if (self.write_law not in ("legacy", "event_mask", "continuous_write")
                or not math.isfinite(self.write_rate) or self.write_rate < 0
                or (self.write_law == "continuous_write" and self.write_rate <= 0)
                or self.feedback_mode not in ("legacy", *FEEDBACK_MODES)
                or not math.isfinite(self.feedback_gain) or not 0 < self.feedback_gain <= 4
                or self.feature_bank not in FEATURE_BANKS or self.pooling not in POOLING_MODES
                or (self.kind == "gru" and (self.write_law != "legacy"
                    or self.feedback_mode not in ("legacy", "none") or self.feature_bank != "same_generator"))):
            raise ValueError("invalid physical write, feedback, feature bank or pooling mode")


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
            self.flow_feature_names = (self.encoder.feature_names if config.write_law == "legacy"
                                       else self.encoder.physical_feature_names)
            self.feature_names = self.flow_feature_names
            if config.feature_bank == "ordinary_tanh":
                self.feature_names = tuple({"risk": "ordinary_risk", "call": "ordinary_value",
                    "first_event_probability": "ordinary_risk", "continuation_value": "ordinary_value"}.get(name, name)
                                           for name in self.feature_names)
            self.feedback = (ContentFeedback(config.width, config.feedback_mode, config.feedback_gain)
                             if config.feedback_mode != "legacy" else None)
        else:
            self.encoder = nn.GRUCell(config.input_size + 1, config.width)
            self.boundary = None
            self.feature_width = config.width
            self.feature_names = tuple(f"hidden_{i}" for i in range(config.width))
            self.feedback = None
        self.predictor = nn.Linear(self.feature_width, config.input_size)
        self.to(dtype=getattr(torch, config.dtype))

    def encode_one(self, sequence, intervals, *, observation_mask=None):
        """Causal per-window execution; unequal intervals are never averaged."""
        if (sequence.ndim != 2 or sequence.shape[1] != self.config.input_size
                or len(sequence) < 1 or len(intervals) != len(sequence)
                or not torch.isfinite(sequence).all()):
            raise ValueError("finite [time,input] sequence and one interval per event required")
        if observation_mask is not None:
            observation_mask = torch.as_tensor(observation_mask, device=sequence.device)
            if (self.config.write_law != "event_mask" or observation_mask.shape != (len(sequence),)
                    or not bool(((observation_mask == 0) | (observation_mask == 1)).all())):
                raise ValueError("observation mask requires matching event-mask semantics")
        state, outputs = None, []
        for index, (inputs, interval) in enumerate(zip(sequence, intervals)):
            seconds = float(interval)
            micros = round(seconds * 1_000_000)
            if (not math.isfinite(seconds) or not 1 <= micros <= 10**9
                    or not math.isclose(seconds * 1_000_000, micros, rel_tol=0, abs_tol=1e-6)):
                raise ValueError("actual positive integer-microsecond intervals required")
            mask = None if observation_mask is None else observation_mask[index:index + 1]
            features, state = self._encode_interval(inputs.unsqueeze(0), state, seconds, mask)
            outputs.append(features.squeeze(0))
        return torch.stack(outputs)

    def _encode_interval(self, inputs, state, seconds, write_mask):
        if self.config.kind == "gru":
            timing = inputs.new_full((len(inputs), 1), math.log1p(seconds / self.config.clock_scale_seconds))
            state = self.encoder(torch.cat((inputs, timing), -1), state)
            return state, state
        if (self.config.write_law == "legacy" and self.feedback is None
                and self.config.feature_bank == "same_generator"):
            boundary = self.config.boundary_scale * self.boundary(inputs).tanh().squeeze(-1)
            features, state, _ = self.encoder.step(inputs, state, dt=seconds, boundary_override=boundary)
            return features, state
        raw_boundary = self.boundary(inputs).squeeze(-1)
        raw_drive = self.encoder.drive(inputs).squeeze(-1)
        controls = inputs.new_zeros(len(inputs), 3) if self.feedback is None else self.feedback(state, inputs)
        boundary = self.config.boundary_scale * (raw_boundary + controls[:, 1]).tanh()
        options = {"dt": seconds, "boundary_override": boundary}
        if self.feedback is not None:
            c = self.encoder.config
            options.update(drift_override=c.base_drift + c.drift_scale * (raw_drive + controls[:, 0]).tanh(),
                           reward_offset=c.maintenance * controls[:, 2])
        if self.config.write_law == "legacy":
            features, state, _ = self.encoder.step(inputs, state, **options)
        else:
            from qualification.hcsn_adaptive.flow_semantics import FlowSemantics
            options["semantics"] = FlowSemantics(write_law=self.config.write_law,
                write_rate=self.config.write_rate if self.config.write_law == "continuous_write" else None)
            if self.config.write_law == "event_mask":
                # Original rows write once; inserted subdivisions need an explicit mask.
                options["write_mask"] = inputs.new_ones(len(inputs)) if write_mask is None else write_mask
            features, state, _ = self.encoder.step_physical(inputs, state, **options)
        features = select_feature_bank(features, torch.stack((raw_drive, raw_boundary), -1),
                                       self.flow_feature_names, self.config.feature_bank)
        return features, state

    def encode_batch(self, windows, intervals, *, observation_mask=None):
        """Batch windows with identical physical clocks; never average unequal dt.

        Groups are execution-only. Every sample has its own state, and grouped
        outputs remain differentiable in input order. Distinct clocks fall back
        to smaller groups, with the corresponding actual computational cost.
        """
        dt = torch.as_tensor(intervals, dtype=torch.float64, device="cpu")
        if (windows.ndim != 3 or len(windows) < 1 or windows.shape[1] < 1
                or windows.shape[2] != self.config.input_size or dt.shape != windows.shape[:2]
                or not bool(torch.isfinite(windows).all()) or not bool(torch.isfinite(dt).all())):
            raise ValueError("finite matching [batch,time,input] windows and physical intervals required")
        micros = (dt * 1_000_000).round()
        if (bool((micros < 1).any()) or bool((micros > 10**9).any())
                or not torch.allclose(micros, dt * 1_000_000, rtol=0, atol=1e-6)):
            raise ValueError("actual positive integer-microsecond intervals required")
        if observation_mask is not None:
            observation_mask = torch.as_tensor(observation_mask, device=windows.device)
            if (self.config.write_law != "event_mask" or observation_mask.shape != dt.shape
                    or not bool(((observation_mask == 0) | (observation_mask == 1)).all())):
                raise ValueError("observation mask requires matching event-mask semantics")
        groups, outputs = {}, [None] * len(windows)
        for index, row in enumerate(micros.to(torch.int64).tolist()):
            groups.setdefault(tuple(row), []).append(index)
        for clock, indices in groups.items():
            state, features = None, []
            subset = windows[indices]
            for position, microseconds in enumerate(clock):
                mask = None if observation_mask is None else observation_mask[indices, position]
                value, state = self._encode_interval(subset[:, position], state, microseconds / 1_000_000, mask)
                features.append(value)
            encoded = torch.stack(features, dim=1)
            for local, original in enumerate(indices):
                outputs[original] = encoded[local]
        return torch.stack(outputs)

    def next_sensor_loss(self, windows, intervals):
        if windows.ndim != 3 or windows.shape[1] < 2 or len(windows) != len(intervals):
            raise ValueError("next-sensor learning requires [batch,time>=2,input]")
        if self.config.write_law == "legacy":
            # Keep the historical per-window arithmetic path reproducible.
            loss = torch.stack([(self.predictor(self.encode_one(x[:-1], dt[:-1])) - x[1:]).square().mean()
                                for x, dt in zip(windows, intervals)]).mean()
        else:
            features = self.encode_batch(windows[:, :-1], intervals[:, :-1])
            loss = (self.predictor(features) - windows[:, 1:]).square().mean()
        if not torch.isfinite(loss):
            raise FloatingPointError("nonfinite self-supervised loss")
        return loss

    @torch.no_grad()
    def representations(self, windows, intervals):
        embeddings, losses = [], []
        encoded = ([self.encode_one(x, dt) for x, dt in zip(windows, intervals)]
                   if self.config.write_law == "legacy" else self.encode_batch(windows, intervals))
        for sequence, timing, features in zip(windows, intervals, encoded):
            embeddings.append(pool_features(features, timing, self.feature_names, self.config.pooling))
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
                "feature_names": list(self.feature_names),
                "embedding_feature_names": pooled_feature_names(self.feature_names, self.config.pooling),
                "streaming_state_bytes_per_sample": (self.encoder.initial_state(1).tensor_bytes()
                    if self.config.kind == "hcsn" else self.config.width * next(self.parameters()).element_size()),
                "state_bytes_exclude_autograd_and_outputs": True,
                "feature_bank_comparison": "equal feature width; parameter counts reported, no cross-architecture matching claim",
                "feedback_content": "previous active plus refractory signed mass; no escaped marks or stop-gradient",
                "feedback_clock": "updated at each declared interval start and held within it; subdivision changes the feedback control path",
                "risk_pooling": "sum of interval first-hit probabilities / duration; not hazard or whole-window risk",
                "feedback_reward_offset_bound": (self.config.feedback_gain * self.encoder.config.maintenance
                    if self.feedback is not None else 0.0),
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
