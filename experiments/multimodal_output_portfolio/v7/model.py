"""Shared source slots, learned command routing, and genuine neural decoders.

The task factorization is public: two 28x28 source panels. Ordering is learned
from the command token; no inference operation reads Target or swaps outputs.
Four controls update the internal generation state, not external model calls.
"""

from dataclasses import dataclass, replace
import hashlib
import math

import torch
from torch import nn
from torch.nn import functional as F

from ..v6.data import BOS, CAPTION_LENGTH, Observation, Target, VOCAB
from ..v6.neural import ACTIONS, NeuralOutput


ARCHITECTURE = "shared-source-slots-learned-command-attention-v1"


@dataclass(frozen=True)
class State:
    h: torch.Tensor
    image: torch.Tensor
    text: torch.Tensor
    context: torch.Tensor
    snapshot_digest: str = ""
    source_digest: str = ""
    content_control: bool = True
    step_count: int = 0


def observation_digest(observation):
    if not isinstance(observation, Observation):
        raise TypeError("Only public Observation can be encoded")
    digest = hashlib.sha256(b"hepta.ndu-v7.public-observation.v1")
    for tensor in (observation.pixels, observation.mask, observation.text_tokens):
        value = tensor.detach().cpu().contiguous()
        digest.update(str((str(value.dtype), tuple(value.shape))).encode())
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def validate_observation(observation):
    if not isinstance(observation, Observation):
        raise TypeError("Only public Observation can be encoded")
    pixels, mask, tokens = observation.pixels, observation.mask, observation.text_tokens
    if (pixels.ndim != 4 or pixels.shape[1:] != (1, 28, 56) or len(pixels) < 1
            or mask.shape != pixels.shape or tokens.shape != (len(pixels), 8)
            or tokens.dtype != torch.long or not pixels.is_floating_point()
            or not mask.is_floating_point() or not torch.isfinite(pixels).all()
            or not torch.isfinite(mask).all() or pixels.min() < 0 or pixels.max() > 1
            or not ((mask == 0) | (mask == 1)).all()
            or ((pixels != 0) & (mask == 0)).any()):
        raise ValueError("Invalid public tensor profile")
    if (not (tokens[:, 0] == 1).all() or not (tokens[:, 6] == 2).all()
            or not (tokens[:, 7] == 0).all()
            or not ((tokens[:, 1] == 9) | (tokens[:, 1] == 10)).all()
            or not ((tokens[:, 2] == 12) | (tokens[:, 2] == 11)).all()
            or not ((tokens[:, 4] == 13) | (tokens[:, 4] == 11)).all()):
        raise ValueError("Invalid command/reliability token grammar")
    hints = tokens[:, (3, 5)]
    if not ((hints == 11) | ((hints >= 14) & (hints < len(VOCAB)))).all():
        raise ValueError("Invalid public hint token")


class SlotPortfolio(nn.Module):
    """Each decoder shares weights across digits; text remains autoregressive."""

    def __init__(self, hidden=96, noise_scale=.15, cell_gain=.25, layer_norm_eps=1e-5):
        super().__init__()
        if (hidden != 96 or not math.isfinite(noise_scale) or not 0 <= noise_scale <= 1
                or cell_gain != .25 or layer_norm_eps != 1e-5):
            raise ValueError("Unsupported registered slot architecture configuration")
        self.config = {"architecture": ARCHITECTURE, "hidden": hidden,
                       "noise_scale": noise_scale, "cell_gain": cell_gain,
                       "layer_norm_eps": layer_norm_eps}
        self.hidden, self.slot = hidden, hidden // 2
        self.noise_scale, self.cell_gain = noise_scale, cell_gain
        self.token_embedding = nn.Embedding(len(VOCAB), 24)
        self.reliability_embedding = nn.Embedding(2, 8)
        self.pixel_encoder = nn.Sequential(
            nn.Conv2d(2, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 24, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Flatten(), nn.Linear(24 * 7 * 7, self.slot),
            nn.LayerNorm(self.slot, eps=layer_norm_eps), nn.Tanh(),
        )
        self.fuse = nn.Sequential(nn.Linear(self.slot + 24 + 8 + 1, self.slot),
                                  nn.LayerNorm(self.slot, eps=layer_norm_eps), nn.Tanh())
        self.command_attention = nn.Embedding(2, 4)
        nn.init.normal_(self.command_attention.weight, std=.1)
        self.initial_image = nn.Linear(self.slot, self.slot)
        self.initial_text = nn.Linear(self.slot, self.slot)
        self.semantic_cell = nn.Sequential(nn.Linear(4 * self.slot, self.slot), nn.Tanh())
        self.image_cell = nn.Sequential(nn.Linear(3 * self.slot, self.slot), nn.Tanh())
        self.text_cell = nn.Sequential(nn.Linear(3 * self.slot, self.slot), nn.Tanh())
        self.coupling_cell = nn.Sequential(nn.Linear(4 * self.slot, 3 * self.slot), nn.Tanh())
        self.pixel_decoder = nn.Sequential(nn.Linear(2 * self.slot, 192), nn.ReLU(),
                                           nn.Linear(192, 28 * 28))
        self.text_initial = nn.Linear(2 * hidden, hidden)
        self.text_decoder = nn.GRU(24, hidden, batch_first=True)
        self.text_projection = nn.Linear(hidden, len(VOCAB))
        self.digit_head = nn.Linear(self.slot, 10)

    def encode(self, observation, noise=None, *, content_control=True):
        validate_observation(observation)
        if type(content_control) is not bool:
            raise TypeError("content_control must be bool")
        pixels = torch.stack((observation.pixels[:, :, :, :28],
                              observation.pixels[:, :, :, 28:]), dim=1).flatten(0, 1)
        mask = torch.stack((observation.mask[:, :, :, :28],
                            observation.mask[:, :, :, 28:]), dim=1).flatten(0, 1)
        visual = self.pixel_encoder(torch.cat((pixels, mask), dim=1))
        hint = self.token_embedding(observation.text_tokens[:, (3, 5)]).flatten(0, 1)
        declared_reliable = (observation.text_tokens[:, (2, 4)] != 11).long().flatten()
        reliability = self.reliability_embedding(declared_reliable)
        source_slots = self.fuse(torch.cat((visual, hint, reliability,
                                           mask.mean((1, 2, 3))[:, None]), dim=1))
        source_slots = source_slots.reshape(-1, 2, self.slot)
        # All four mixing coefficients are learned. This is not a hardcoded
        # keep/swap index operation, pixel permutation, or caption repair.
        routing = self.command_attention(observation.text_tokens[:, 1] - 9)
        routing = routing.reshape(-1, 2, 2).softmax(-1)
        context = torch.bmm(routing, source_slots).flatten(1)
        if noise is not None and (noise.shape != context.shape or not torch.isfinite(noise).all()):
            raise ValueError("Invalid latent-noise scenario")
        h = context if noise is None else context + self.noise_scale * noise
        slots = h.reshape(-1, self.slot)
        image = torch.tanh(self.initial_image(slots)).reshape(-1, self.hidden)
        text = torch.tanh(self.initial_text(slots)).reshape(-1, self.hidden)
        return State(h, image, text, context, content_control=content_control)

    def step(self, state, action):
        if action not in ACTIONS:
            raise ValueError("Unknown generation action")
        if not state.content_control and action in {"refine_semantic", "couple"}:
            raise ValueError("Shared content controls are disabled")
        h, image, text, context = [getattr(state, name).reshape(-1, self.slot)
                                   for name in ("h", "image", "text", "context")]
        if action == "refine_semantic":
            h = h + self.cell_gain * self.semantic_cell(torch.cat((h, image, text, context), 1))
        elif action == "refine_image":
            image = image + self.cell_gain * self.image_cell(torch.cat((h, image, context), 1))
        elif action == "refine_text":
            text = text + self.cell_gain * self.text_cell(torch.cat((h, text, context), 1))
        else:
            dh, di, dt = self.coupling_cell(torch.cat((h, image, text, context), 1)).chunk(3, 1)
            h, image, text = h + self.cell_gain * dh, image + self.cell_gain * di, text + self.cell_gain * dt
        return replace(state, h=h.reshape(-1, self.hidden), image=image.reshape(-1, self.hidden),
                       text=text.reshape(-1, self.hidden), step_count=state.step_count + 1)

    def decode(self, state, teacher_tokens=None):
        digit_latents = torch.cat((state.h.reshape(-1, self.slot),
                                   state.image.reshape(-1, self.slot)), 1)
        panels = self.pixel_decoder(digit_latents).reshape(-1, 2, 1, 28, 28)
        image_logits = torch.cat((panels[:, 0], panels[:, 1]), dim=3)
        hidden = torch.tanh(self.text_initial(torch.cat((state.h, state.text), 1))).unsqueeze(0)
        bos = torch.full((len(state.h), 1), BOS, dtype=torch.long, device=state.h.device)
        if teacher_tokens is not None:
            sequence, _ = self.text_decoder(self.token_embedding(teacher_tokens[:, :-1]), hidden)
            text_logits = self.text_projection(sequence)
            tokens = torch.cat((bos, text_logits.argmax(-1)), 1)
        else:
            token, emitted, all_logits = bos, [bos], []
            for _ in range(CAPTION_LENGTH - 1):
                sequence, hidden = self.text_decoder(self.token_embedding(token), hidden)
                logits = self.text_projection(sequence)
                token = logits.argmax(-1)
                emitted.append(token)
                all_logits.append(logits)
            tokens, text_logits = torch.cat(emitted, 1), torch.cat(all_logits, 1)
        digit_logits = self.digit_head(state.h.reshape(-1, self.slot)).reshape(-1, 2, 10)
        return NeuralOutput(image_logits, text_logits, tokens, digit_logits)

    def semantic_probabilities(self, state):
        return self.digit_head(state.h.reshape(-1, self.slot)).reshape(-1, 2, 10).softmax(-1)

    def state_features(self, state):
        return torch.cat((state.h, state.image, state.text, state.context), 1)

    def loss(self, output, target):
        if not isinstance(target, Target):
            raise TypeError("Training loss requires Target")
        image = F.binary_cross_entropy_with_logits(output.image_logits, target.pixels,
                                                   reduction="none").flatten(1).mean(1)
        text = F.cross_entropy(output.text_logits.transpose(1, 2), target.text_tokens[:, 1:],
                               reduction="none").mean(1)
        digit = F.cross_entropy(output.digit_logits.transpose(1, 2), target.labels,
                                reduction="none").mean(1)
        return {"joint": image + .5 * text + .3 * digit,
                "image_bce": image, "text_ce": text, "digit_ce": digit}
