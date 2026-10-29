"""Trainable, matched FPT/ordinary temporal backbones for the existing generator.

The fixed HCSN source supplies parameters and the interval-end-reset kernel.
Both modes train every generator parameter. This is a controlled comparison of
that first-passage recurrence, not a Call--Put or endogenous-barrier claim.
"""

from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import sys
import types

import torch
from torch import nn
from torch.nn import functional as F

from experiments.multimodal_output_portfolio.v6.data import (
    BOS, CAPTION_LENGTH, Observation,
)
from experiments.multimodal_output_portfolio.v6.neural import (
    NeuralOutput, NeuralPortfolio, NeuralState,
)


REFERENCE_COMMIT = "68eb16caa9c14c7b5729585c86d9c293018a987c"
REFERENCE_SHA256 = {
    "kernels.py": "188334725b39b7e3bfdf5b17dd04cef2d3383ab6eb02c17eedad912dea21ae30",
    "cell.py": "486b9f86ad7cdbae2f3e8a151cb500a219b87cd67a438e9a4e10c038a43ac311",
}


def reference_modules(reference_root):
    """Load only hash-pinned source without replacing repository import paths."""
    folder = Path(reference_root) / "experiments" / "continuous_spiking_network"
    for name, expected in REFERENCE_SHA256.items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"HCSN reference identity mismatch: {name}")
    package_name = "_hepta_fullstudy_hcsn_" + REFERENCE_COMMIT
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(folder)]
        sys.modules[package_name] = package
        for name in ("kernels", "cell"):
            module_name = package_name + "." + name
            spec = importlib.util.spec_from_file_location(module_name, folder / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
    return (sys.modules[package_name + ".cell"], sys.modules[package_name + ".kernels"])


@dataclass(frozen=True)
class TemporalState:
    content: torch.Tensor
    voltage: torch.Tensor
    adaptation: torch.Tensor
    event: torch.Tensor

    def detached_clone(self):
        """Checkpoint all four public tensors between autograd steps."""
        return TemporalState(*(value.detach().clone() for value in self.tensors()))

    def tensors(self):
        return (self.content, self.voltage, self.adaptation, self.event)


class TrainableTemporalModule(nn.Module):
    """Explicit four-state recurrence; input/output sequences retain their length."""

    def __init__(self, input_width, width, mode, reference_root):
        super().__init__()
        if mode not in {"dual", "ordinary"}:
            raise ValueError("The matched treatment requires dual or ordinary mode")
        if min(input_width, width) < 1:
            raise ValueError("Temporal dimensions must be positive")
        cell, kernels = reference_modules(reference_root)
        self.input_width, self.width, self.mode = input_width, width, mode
        self.input_projection = nn.Linear(input_width, width)
        self.layer = cell._ContinuousCell(width, mode, "direct")
        self._reset_mean = kernels.reset_at_interval_end_mean

    def initial_state(self, batch_size, content=None):
        anchor = self.input_projection.weight
        zero = anchor.new_zeros(batch_size, self.width)
        if content is None:
            content = zero.clone()
        if (content.shape != zero.shape or content.dtype != zero.dtype
                or content.device != zero.device):
            raise ValueError("Initial content must match temporal batch, dtype and device")
        return TemporalState(content, zero.clone(), zero.clone(), zero.clone())

    def step(self, embedding, state=None, dt=None):
        if embedding.ndim != 2 or embedding.shape[-1] != self.input_width:
            raise ValueError("Embedding must have shape [batch,input_width]")
        x = self.input_projection(embedding)
        state = self.initial_state(len(x)) if state is None else state
        if not isinstance(state, TemporalState) or any(
            value.shape != x.shape or value.dtype != x.dtype or value.device != x.device
            for value in state.tensors()
        ):
            raise ValueError("All four temporal state tensors must match the current input")
        duration = x.new_ones(len(x), 1) if dt is None else dt.reshape(-1, 1).to(x)
        if duration.shape != (len(x), 1) or not torch.isfinite(duration).all() or (duration < 0).any():
            raise ValueError("dt must contain one finite nonnegative duration per example")
        layer = self.layer
        content, voltage, adaptation, previous_event = state.tensors()
        diffusion = F.softplus(layer.raw_diffusion) + 1e-4
        boundary = F.softplus(layer.raw_boundary) + 1e-4
        signal = layer.norm(x)
        recovery_gate, regeneration_gate = layer.channel_gates(
            torch.cat((signal, content), dim=-1)
        ).sigmoid().chunk(2, dim=-1)
        recovery = F.softplus(layer.raw_recovery) * recovery_gate
        regeneration = F.softplus(layer.raw_regeneration) * regeneration_gate
        drift = (layer.drift_bias + layer.drift_input(signal).tanh()
                 - recovery * voltage + regeneration * previous_event - adaptation)
        if self.mode == "ordinary":
            event = torch.sigmoid(
                (duration * drift - (boundary - voltage))
                / (diffusion * duration.clamp_min(1e-8).sqrt())
            ) * (duration > 0)
            voltage = (1 - event) * (voltage + duration * drift)
        else:
            voltage, terms = self._reset_mean(voltage, boundary, drift, diffusion, duration)
            event = terms["cdf"]
        adaptation = (adaptation * torch.exp(-F.softplus(layer.raw_adaptation_decay) * duration)
                      + F.softplus(layer.raw_adaptation) * event)
        candidate = torch.tanh(layer.content_input(signal) + layer.content_state(content))
        write = 1 - (1 - event) * torch.exp(-F.softplus(layer.raw_content_rate) * duration)
        content = (1 - write) * content + write * candidate
        successor = TemporalState(
            content, voltage, adaptation, torch.where(duration > 0, event, previous_event)
        )
        return x + layer.output(content), successor

    def forward(self, embeddings, state=None, dt=None):
        if embeddings.ndim != 3 or embeddings.shape[1] < 1:
            raise ValueError("Expected a nonempty [batch,time,input_width] sequence")
        if dt is not None and dt.shape != embeddings.shape[:2]:
            raise ValueError("Sequence durations must have shape [batch,time]")
        outputs = []
        for index in range(embeddings.shape[1]):
            output, state = self.step(
                embeddings[:, index], state, None if dt is None else dt[:, index]
            )
            outputs.append(output)
        return torch.stack(outputs, dim=1), state


class TrainablePortfolio(NeuralPortfolio):
    """Existing image/text generator with two trained HCSN temporal modules.

Only the text encoder and decoder architecture changes. Ordinary and dual
construction consumes identical random draws. Existing legacy snapshot loaders
are intentionally not used; this study must save explicit config/state_dicts.
"""

    def __init__(self, *, reference_root, mode, seed, hidden=32, noise_scale=.15):
        if hidden % 2:
            raise ValueError("Matched generator hidden width must be even")
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            super().__init__(hidden=hidden, noise_scale=noise_scale)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed + 100003)
            self.text_encoder = TrainableTemporalModule(24, hidden // 2, mode, reference_root)
            self.text_decoder = TrainableTemporalModule(24, hidden, mode, reference_root)
        self.config.update(architecture="fullstudy-hcsn-temporal-v1", mode=mode, seed=seed,
                           reference_commit=REFERENCE_COMMIT)

    def encode(self, observation, noise=None):
        if not isinstance(observation, Observation):
            raise TypeError("Inference encoder accepts Observation only")
        if observation.pixels.ndim != 4 or observation.pixels.shape[1:] != (1, 28, 56):
            raise ValueError("Expected Bx1x28x56 public pixels")
        if observation.mask.shape != observation.pixels.shape:
            raise ValueError("Pixel/missingness shape mismatch")
        visual = self.pixel_encoder(torch.cat((observation.pixels, observation.mask), dim=1))
        language, _ = self.text_encoder(self.token_embedding(observation.text_tokens))
        context = self.fuse(torch.cat((visual, language[:, -1]), dim=1))
        h = context if noise is None else context + self.noise_scale * noise
        if h.shape != context.shape:
            raise ValueError("Initial latent noise shape mismatch")
        return NeuralState(h, torch.tanh(self.initial_image(h)),
                           torch.tanh(self.initial_text(h)), context)

    def decode(self, state, teacher_tokens=None):
        image_logits = self.pixel_decoder(torch.cat((state.h, state.image), dim=1)).reshape(-1, 1, 28, 56)
        initial = torch.tanh(self.text_initial(torch.cat((state.h, state.text), dim=1)))
        temporal = self.text_decoder.initial_state(len(state.h), content=initial)
        bos = torch.full((len(state.h), 1), BOS, dtype=torch.long, device=state.h.device)
        if teacher_tokens is not None:
            sequence, _ = self.text_decoder(self.token_embedding(teacher_tokens[:, :-1]), temporal)
            text_logits = self.text_projection(sequence)
            tokens = torch.cat((bos, text_logits.argmax(-1)), dim=1)
        else:
            token, emitted, logits = bos, [bos], []
            for _ in range(CAPTION_LENGTH - 1):
                output, temporal = self.text_decoder.step(self.token_embedding(token[:, 0]), temporal)
                step_logits = self.text_projection(output).unsqueeze(1)
                token = step_logits.argmax(-1)
                emitted.append(token)
                logits.append(step_logits)
            tokens, text_logits = torch.cat(emitted, dim=1), torch.cat(logits, dim=1)
        digit_logits = self.digit_head(state.h).reshape(-1, 2, 10)
        return NeuralOutput(image_logits, text_logits, tokens, digit_logits)


def matched_pair(*, reference_root, seed, hidden=32, noise_scale=.15):
    """Construct active, equally initialized models; no parameter is frozen."""
    models = {mode: TrainablePortfolio(reference_root=reference_root, mode=mode,
                                      seed=seed, hidden=hidden, noise_scale=noise_scale)
              for mode in ("ordinary", "dual")}
    ordinary, dual = (models[mode].state_dict() for mode in ("ordinary", "dual"))
    if ordinary.keys() != dual.keys() or any(not torch.equal(ordinary[k], dual[k]) for k in ordinary):
        raise AssertionError("Matched architecture initialization differs")
    if any(not parameter.requires_grad for model in models.values() for parameter in model.parameters()):
        raise AssertionError("The architecture experiment must train its full generator")
    return models
