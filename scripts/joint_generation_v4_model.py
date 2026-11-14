"""Trainable v4 joint generator matching the native bounded FP64 profile.

The numerical media heads remain 16x16 RGB, 1024 mono samples and four frames.
Byte text is autoregressive and open vocabulary. This implementation provides
no claim that a newly initialized checkpoint has learned semantic generation.
"""

from dataclasses import dataclass, replace

import torch
from torch import nn
from torch.nn import functional as F

from experiments.multimodal_output_portfolio.joint_hepta_20261029.hepta_core import (
    HeptaCore,
)
from scripts.joint_generation_v4_io import OBSERVATION_FEATURES, PROFILES, packet_bytes


ACTIONS = ("shared", "image", "audio", "video", "text", "verify", "stop")
MODALITIES = ("image", "audio", "video", "text")


@dataclass
class GenerationState:
    context: torch.Tensor
    shared: torch.Tensor
    slots: torch.Tensor
    core: list
    feedback: torch.Tensor
    text_hidden: torch.Tensor
    steps: int = 0
    stopped: bool = False
    verified: bool = False
    content_revision: int = 0
    verified_revision: int = -1
    text_units: int = 0
    text_bytes: int = 0


class JointGeneratorV4(nn.Module):
    def __init__(
        self,
        width=32,
        depth=1,
        mode="dual",
        boundary="direct",
        *,
        core_state_profile="persistent-v1",
        allow_initial_stop=False,
        suppress_redundant_verify=False,
    ):
        super().__init__()
        if (
            type(width) is not int
            or not 1 <= width <= 256
            or type(depth) is not int
            or not 1 <= depth <= 8
            or core_state_profile not in {"persistent-v1", "reset-each-action-v1"}
        ):
            raise ValueError("Invalid v4 model profile")
        self.width, self.depth = width, depth
        self.mode, self.boundary = mode, boundary
        self.core_state_profile = core_state_profile
        self.allow_initial_stop = allow_initial_stop
        self.suppress_redundant_verify = suppress_redundant_verify
        self.image_encoder = nn.Sequential(nn.Linear(1536, width), nn.Tanh())
        self.audio_encoder = nn.Sequential(nn.Linear(2048, width), nn.Tanh())
        self.video_encoder = nn.Sequential(nn.Linear(4 * width, width), nn.Tanh())
        self.token_encoder = nn.Embedding(256, width)
        self.text_recurrent = nn.Linear(width, width)
        self.text_condition = nn.Linear(2 * width, width)
        self.encoder_fusion = nn.Sequential(nn.Linear(4 * width, width), nn.Tanh())
        self.initial_slots = nn.Linear(width, 4 * width)
        self.feedback_projection = nn.Linear(3, width)
        self.transition_input = nn.Linear(3 * width, width)
        self.action_embedding = nn.Embedding(5, width)
        self.core = HeptaCore(width, depth=depth, mode=mode, boundary_mode=boundary)
        self.adapters = nn.ModuleDict(
            {
                name: nn.Sequential(nn.Linear(3 * width, width), nn.Tanh())
                for name in MODALITIES
            }
        )
        self.emissions = nn.ModuleDict(
            {
                name: nn.Sequential(
                    nn.Linear(2 * width, hidden), nn.Tanh(), nn.Linear(hidden, output)
                )
                for name, hidden, output in (
                    ("image", 64, 768),
                    ("audio", 64, 1024),
                    ("video", 96, 3072),
                )
            }
        )
        self.emissions["text"] = nn.Linear(2 * width, 256)
        for name, output in (("actor", 7), ("critic", 1), ("delivery_critic", 1)):
            setattr(
                self,
                name,
                nn.Sequential(
                    nn.Linear(2 * width + 5 + OBSERVATION_FEATURES, width),
                    nn.Tanh(),
                    nn.Linear(width, output),
                ),
            )
        self.double()

    def encode(self, public):
        """Encode one public task; tokens are raw, valid UTF-8 byte IDs."""
        if set(public) != {
            "image",
            "image_mask",
            "audio",
            "audio_mask",
            "video",
            "video_mask",
            "tokens",
        }:
            raise ValueError("Public tensor inventory")
        expected = {
            "image": (1, 3, 16, 16),
            "audio": (1, 1024),
            "video": (1, 4, 3, 16, 16),
        }
        for name, shape in expected.items():
            for key in (name, name + "_mask"):
                value = public[key]
                if (
                    tuple(value.shape) != shape
                    or not bool(torch.isfinite(value).all())
                    or bool((value.abs() > 1).any())
                ):
                    raise ValueError("Public shape/range")
            if bool((public[name + "_mask"] < 0).any()):
                raise ValueError("Public mask range")
        tokens = public["tokens"]
        if (
            tokens.ndim != 2
            or tokens.shape[0] != 1
            or tokens.shape[1] > 4096
            or not bool(torch.isfinite(tokens).all())
            or bool(((tokens < 0) | (tokens >= 256)).any())
            or bool((tokens != tokens.long()).any())
        ):
            raise ValueError("UTF-8 token domain")
        bytes(tokens.long().flatten().tolist()).decode("utf-8")
        image = self.image_encoder(
            torch.cat((public["image"].flatten(1), public["image_mask"].flatten(1)), -1)
        )
        audio = self.audio_encoder(
            torch.cat((public["audio"], public["audio_mask"]), -1)
        )
        frames = [
            self.image_encoder(
                torch.cat(
                    (
                        public["video"][:, index].flatten(1),
                        public["video_mask"][:, index].flatten(1),
                    ),
                    -1,
                )
            )
            for index in range(4)
        ]
        video = self.video_encoder(torch.cat(frames, -1))
        text = image.new_zeros(1, self.width)
        for token in tokens.long().unbind(1):
            text = (self.text_recurrent(text) + self.token_encoder(token)).tanh()
        context = self.encoder_fusion(torch.cat((image, audio, video, text), -1))
        return GenerationState(
            context,
            context,
            self.initial_slots(context).tanh().reshape(1, 4, self.width),
            self.core.initial_state(1, content=context),
            context.new_zeros(1, 3),
            context,
        )

    def outputs(self, state):
        return {
            name: self.emissions[name](
                torch.cat(
                    (
                        state.shared,
                        state.text_hidden if name == "text" else state.slots[:, index],
                    ),
                    -1,
                )
            )
            for index, name in enumerate(MODALITIES)
        }

    def inspect(self, state, observation):
        extras = state.shared.new_tensor(
            [[observation.remaining_fraction, state.steps / 8]]
        )
        observed = state.shared.new_tensor([observation.features()])
        features = torch.cat(
            (state.shared, state.slots.mean(1), state.feedback, extras, observed), -1
        )
        logits = self.actor(features)
        legal = [True] * 7
        selected = observation.required_mask | observation.optional_mask
        totals = (16, 1024, 4, 128)
        for index in range(4):
            legal[index + 1] = (
                bool(selected & (1 << index))
                and observation.cursors[index] < totals[index]
            )
        legal[0] = any(legal[1:5])
        if state.steps == 0 and not self.allow_initial_stop:
            legal[6] = False
        if state.verified and self.suppress_redundant_verify:
            legal[5] = False
        if state.steps >= 6 or state.stopped:
            legal = [False] * 6 + [True]
        mask = torch.tensor(legal, dtype=torch.bool, device=logits.device)
        return {
            "actor.logits": logits,
            "critic": self.critic(features),
            "delivery_critic": self.delivery_critic(features),
            "policy.probabilities": logits.masked_fill(~mask, -torch.inf).softmax(-1),
            "policy.legal_mask": mask.to(logits.dtype).unsqueeze(0),
        }

    def advance(self, state, action, public):
        if (
            action not in ACTIONS
            or state.stopped
            or (state.steps >= 6 and action != "stop")
            or (state.steps == 0 and action == "stop" and not self.allow_initial_stop)
        ):
            raise ValueError("Illegal continuation")
        following = replace(state, steps=state.steps + 1)
        if action == "stop":
            return replace(following, stopped=True)
        if action == "verify":
            if self.suppress_redundant_verify and state.verified:
                raise ValueError("Redundant verification")
            outputs = self.outputs(state)
            feedback = []
            for name in MODALITIES[:3]:
                emitted = (
                    outputs[name].tanh() if name == "audio" else outputs[name].sigmoid()
                )
                feedback.append(
                    (
                        (emitted - public[name].flatten(1)).square()
                        * public[name + "_mask"].flatten(1)
                    ).mean(-1)
                )
            return replace(
                following,
                feedback=torch.stack(feedback, -1),
                verified=True,
                verified_revision=state.content_revision,
            )
        signal = self.transition_input(
            torch.cat((state.context, state.shared, state.slots.mean(1)), -1)
        )
        signal = (
            signal
            + self.action_embedding.weight[ACTIONS.index(action)]
            + self.feedback_projection(state.feedback)
        )
        prior = (
            self.core.initial_state(1, content=state.context)
            if self.core_state_profile == "reset-each-action-v1"
            else state.core
        )
        output, core, _ = self.core.step(signal, prior, 0.5)
        shared = output.tanh()
        slots = []
        for index, name in enumerate(MODALITIES):
            slot = state.slots[:, index]
            if action in ("shared", name):
                slot = slot + 0.25 * self.adapters[name](
                    torch.cat((shared, slot, state.context), -1)
                )
            slots.append(slot)
        return replace(
            following,
            shared=shared,
            slots=torch.stack(slots, 1),
            core=core,
            verified=False,
            content_revision=state.content_revision + 1,
        )

    def consume_byte(self, state, byte):
        if type(byte) is not int or not 0 <= byte < 256:
            raise ValueError("Byte domain")
        condition = self.text_condition(
            torch.cat((state.shared, state.slots[:, 3]), -1)
        )
        hidden = (
            self.text_recurrent(state.text_hidden)
            + condition
            + self.token_encoder.weight[byte]
        ).tanh()
        return replace(state, text_hidden=hidden, text_bytes=state.text_bytes + 1)

    def text_loss(self, state, target):
        """Actual next-byte likelihood gradients through the persistent decoder.

        This teacher-forced loss is a content loss, not an NDU training claim.
        NDU utility targets must be supplied by a separately frozen evaluator.
        """
        target = target.encode("utf-8") if isinstance(target, str) else target
        text = target.decode("utf-8")
        if not target or state.text_units + len(text) > 128:
            raise ValueError("Target text bound")
        prefix, losses = bytearray(), []
        for byte in target:
            logits = self.emissions["text"](
                torch.cat((state.shared, state.text_hidden), -1)
            )
            legal = torch.tensor(
                [valid_utf8_next(prefix, candidate) for candidate in range(256)],
                dtype=torch.bool,
                device=logits.device,
            )
            losses.append(
                F.cross_entropy(
                    logits.masked_fill(~legal, -torch.inf),
                    torch.tensor([byte], device=logits.device),
                )
            )
            state = self.consume_byte(state, byte)
            prefix.append(byte)
            try:
                prefix.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                prefix.clear()
                state = replace(state, text_units=state.text_units + 1)
        return torch.stack(losses).mean(), state

    def export_weights(self, *, inference_profile="ndu-finite-deterministic-v1"):
        if inference_profile not in {
            "ndu-finite-deterministic-v1",
            "actor-greedy-observed-v1",
        }:
            raise ValueError("Unknown inference profile")
        metadata = {
            **PROFILES,
            "width": self.width,
            "depth": self.depth,
            "mode": self.mode,
            "boundary": self.boundary,
            "core_state_profile": self.core_state_profile,
            "allow_initial_stop": str(self.allow_initial_stop).lower(),
            "suppress_redundant_verify": str(self.suppress_redundant_verify).lower(),
            "inference_profile": inference_profile,
        }
        if inference_profile == "ndu-finite-deterministic-v1":
            metadata.update(
                {
                    "ndu.risk": "0.25",
                    "ndu.discount_per_second": "1",
                    "ndu.latency_weight": "0.01",
                    "ndu.horizon": "2",
                    "ndu.max_forecasts": "32",
                    "ndu.action_micros": "1000,1000,1000,1000,1000,1000,1000",
                    "ndu.critic_output": "sigmoid-quality-v1",
                }
            )
        return packet_bytes(metadata, self.state_dict())


def valid_utf8_next(prefix, byte):
    if not prefix:
        return byte <= 0x7F or 0xC2 <= byte <= 0xF4
    if len(prefix) == 1:
        bounds = {
            0xE0: (0xA0, 0xBF),
            0xED: (0x80, 0x9F),
            0xF0: (0x90, 0xBF),
            0xF4: (0x80, 0x8F),
        }
        lower, upper = bounds.get(prefix[0], (0x80, 0xBF))
        return lower <= byte <= upper
    return len(prefix) < 4 and 0x80 <= byte <= 0xBF


def public_packet(public):
    return packet_bytes({"kind": "joint-generator-public-v4"}, public)
