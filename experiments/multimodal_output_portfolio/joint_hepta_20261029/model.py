"""Trainable four-output generator and recurrent, feedback-conditioned policy."""

from dataclasses import dataclass
import hashlib
import math

import torch
from torch import nn
from torch.nn import functional as F

from .hepta_core import HeptaCore


MODALITIES = ("image", "audio", "video", "text")
ACTIONS = ("shared", "image", "audio", "video", "text", "verify", "stop")
SHAPES = {"image": (3, 16, 16), "audio": (1024,), "video": (4, 3, 16, 16)}
CLASSES = (63, 17)
EMISSION_SIGMA = 0.035


def tensor_digest(value):
    """Hash an exact CPU tensor tree without pickle serialization."""
    h = hashlib.sha256()
    def visit(node):
        if torch.is_tensor(node):
            item = node.detach().cpu().contiguous()
            h.update(str((str(item.dtype), tuple(item.shape))).encode())
            h.update(item.numpy().tobytes())
        elif isinstance(node, dict):
            for key in sorted(node):
                h.update(str(key).encode()); visit(node[key])
        elif isinstance(node, (tuple, list)):
            for item in node:
                visit(item)
        else:
            h.update(repr(node).encode())
    visit(value)
    return h.hexdigest()


@dataclass
class State:
    context: torch.Tensor
    shared: torch.Tensor
    slots: torch.Tensor
    core: list
    feedback: torch.Tensor
    steps: int = 0
    stopped: bool = False

    def tensors(self):
        return {"context": self.context, "shared": self.shared, "slots": self.slots,
                "core": self.core, "feedback": self.feedback,
                "steps": self.steps, "stopped": self.stopped}


class JointGenerator(nn.Module):
    """Shared HCSN content, modality states and true dense media emissions.

    The ordinary arm uses the parameter-identical sigmoid operator ablation.
    Actor/critic consume only public inputs, latent state and arrived feedback.
    """
    def __init__(self, width=32, depth=1, mode="dual", boundary="direct"):
        super().__init__()
        self.config = dict(width=width, depth=depth, mode=mode, boundary=boundary)
        self.width = width
        self.image_encoder = nn.Sequential(nn.Linear(1536, width), nn.Tanh())
        self.audio_encoder = nn.Sequential(nn.Linear(2048, width), nn.Tanh())
        self.video_encoder = nn.Sequential(nn.Linear(4 * width, width), nn.Tanh())
        self.token_encoder = nn.Embedding(128, width)
        self.encoder_fusion = nn.Sequential(nn.Linear(4 * width, width), nn.Tanh())
        self.initial_slots = nn.Linear(width, 4 * width)
        self.core = HeptaCore(width, depth=depth, mode=mode, boundary_mode=boundary)
        self.action_embedding = nn.Embedding(5, width)
        self.feedback_projection = nn.Linear(3, width)
        self.transition_input = nn.Linear(3 * width, width)
        self.adapters = nn.ModuleDict({m: nn.Sequential(nn.Linear(3 * width, width), nn.Tanh())
                                       for m in MODALITIES})
        self.emissions = nn.ModuleDict({
            "image": nn.Sequential(nn.Linear(2 * width, 64), nn.Tanh(), nn.Linear(64, 768)),
            "audio": nn.Sequential(nn.Linear(2 * width, 64), nn.Tanh(), nn.Linear(64, 1024)),
            "video": nn.Sequential(nn.Linear(2 * width, 96), nn.Tanh(), nn.Linear(96, 3072)),
            "text": nn.Linear(2 * width, sum(CLASSES)),
        })
        self.actor = nn.Sequential(nn.Linear(2 * width + 5, width), nn.Tanh(),
                                   nn.Linear(width, len(ACTIONS)))
        self.critic = nn.Sequential(nn.Linear(2 * width + 5, width), nn.Tanh(), nn.Linear(width, 1))
        self.delivery_critic = nn.Sequential(nn.Linear(2 * width + 5, width), nn.Tanh(), nn.Linear(width, 1))

    def encode(self, public):
        allowed = {"image", "image_mask", "audio", "audio_mask", "video", "video_mask", "tokens"}
        if set(public) != allowed:
            raise ValueError("Public input schema differs; targets never enter encode")
        batch = len(public["image"])
        image = self.image_encoder(torch.cat((public["image"], public["image_mask"]), 1).flatten(1))
        frames = public["video"].reshape(batch * 4, 3, 16, 16)
        masks = public["video_mask"].reshape_as(frames)
        video = self.image_encoder(torch.cat((frames, masks), 1).flatten(1)).reshape(batch, -1)
        audio = self.audio_encoder(torch.cat((public["audio"], public["audio_mask"]), -1))
        text = self.token_encoder(public["tokens"]).mean(1)
        context = self.encoder_fusion(torch.cat((image, audio, self.video_encoder(video), text), -1))
        return State(context, context, self.initial_slots(context).tanh().reshape(batch, 4, self.width),
                     self.core.initial_state(batch, content=context), context.new_zeros(batch, 3))

    def outputs(self, state):
        logits = {m: self.emissions[m](torch.cat((state.shared, state.slots[:, i]), -1))
                  for i, m in enumerate(MODALITIES)}
        return {**{m: logits[m].reshape(-1, *SHAPES[m]) for m in SHAPES},
                "text": logits["text"].split(CLASSES, dim=-1)}

    def features(self, state, remaining):
        clocks = state.shared.new_tensor([[remaining, state.steps / 8]]).expand(len(state.shared), -1)
        return torch.cat((state.shared, state.slots.mean(1), state.feedback, clocks), -1)

    def policy(self, state, remaining, horizon=6):
        features = self.features(state, remaining)
        logits = self.actor(features)
        legal = torch.ones_like(logits, dtype=torch.bool)
        if state.steps == 0:
            legal[:, -1] = False
        if state.steps >= horizon:
            legal[:, :-1] = False
        return logits.masked_fill(~legal, -torch.inf).log_softmax(-1), self.critic(features.detach())[:, 0]

    def advance(self, state, action, public, feedback_override=None):
        if state.stopped or action not in ACTIONS:
            raise ValueError("Cannot execute unknown action or continue after STOP")
        if action == "stop":
            return State(state.context, state.shared, state.slots, state.core,
                         state.feedback, state.steps + 1, True), {}
        if action == "verify":
            raw = self.outputs(state)
            im = ((raw["image"].sigmoid() - public["image"]).square() * public["image_mask"]).flatten(1).mean(1)
            au = ((raw["audio"].tanh() - public["audio"]).square() * public["audio_mask"]).mean(1)
            vi = ((raw["video"].sigmoid() - public["video"]).square() * public["video_mask"]).flatten(1).mean(1)
            # Public consistency is a deterministic function of theta. Keep its
            # path into subsequent conditional log probabilities; detaching it
            # would silently omit a joint-score derivative through verification.
            feedback = torch.stack((im, au, vi), -1)
            if feedback_override is not None:
                if feedback_override.shape != feedback.shape or not torch.isfinite(feedback_override).all():
                    raise ValueError("Invalid arrived public feedback")
                feedback = feedback_override
            return State(state.context, state.shared, state.slots, state.core,
                         feedback, state.steps + 1), {}
        index = ACTIONS.index(action)
        condition = self.action_embedding.weight[index].expand_as(state.shared)
        signal = self.transition_input(torch.cat((state.context, state.shared, state.slots.mean(1)), -1))
        signal = signal + condition + self.feedback_projection(state.feedback)
        shared, core, aux = self.core.step(signal, state.core, 0.5)
        shared = shared.tanh()
        slots = []
        for i, modality in enumerate(MODALITIES):
            slot = state.slots[:, i]
            if action == modality or action == "shared":
                delta = self.adapters[modality](torch.cat((shared, slot, state.context), -1))
                slot = slot + 0.25 * delta
            slots.append(slot)
        return State(state.context, shared, torch.stack(slots, 1), core,
                     state.feedback, state.steps + 1), aux

    def sample(self, state, rng, deterministic=False):
        raw = self.outputs(state)
        sampled, pathwise, log_probability = {}, {}, state.shared.new_zeros(len(state.shared))
        for modality in SHAPES:
            mean = raw[modality]
            latent = mean.detach() if deterministic else (mean + EMISSION_SIGMA * torch.randn(
                mean.shape, generator=rng, device=mean.device, dtype=mean.dtype)).detach()
            log_probability += (-0.5 * ((latent - mean) / EMISSION_SIGMA).square()
                                - math.log(EMISSION_SIGMA * math.sqrt(2 * math.pi))).flatten(1).sum(1)
            linked = mean + (latent - mean).detach()
            transform = torch.tanh if modality == "audio" else torch.sigmoid
            sampled[modality], pathwise[modality] = transform(latent), transform(linked)
        tokens = []
        for logits in raw["text"]:
            law = logits.log_softmax(-1)
            index = logits.argmax(-1, keepdim=True) if deterministic else torch.multinomial(law.exp(), 1, generator=rng)
            log_probability += law.gather(1, index)[:, 0]
            tokens.append(index[:, 0])
        sampled["text"] = torch.stack(tokens, -1).detach()
        pathwise["text"] = sampled["text"]
        return sampled, pathwise, log_probability


def supervised_loss(model, state, target):
    raw = model.outputs(state)
    visual = sum((raw[m].sigmoid() - target[m]).square().mean() for m in ("image", "video"))
    audio = (raw["audio"].tanh() - target["audio"]).square().mean()
    text = sum(F.cross_entropy(logits, target["text"][:, i]) for i, logits in enumerate(raw["text"]))
    return 5 * visual + 2 * audio + 0.2 * text
