"""Matched ordinary/Hepta content and learned deployment forecasts.

No annotation, evaluator result, source group or split is available in this
module's deployment API. Task losses/observed transition labels are supplied by
the separate training driver, never by a confirmation actor.
"""

import math
from contextlib import nullcontext

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from experiments.multimodal_output_portfolio.joint_hepta_20261029.hepta_core import HeptaCore
from .controllers import ACTIONS, Forecast
from .objective import MEMORY_MODES
from .ocr import FEATURE_WIDTH

CONTENT_WIDTH = 24
META_WIDTH = 16
STATE_WIDTH = CONTENT_WIDTH + META_WIDTH


class ReceiptPortfolioModel(nn.Module):
    def __init__(self, core="ordinary"):
        super().__init__()
        if core not in {"ordinary", "hepta"}:
            raise ValueError("Unknown content core")
        self.core_kind = core
        self.project = nn.Linear(FEATURE_WIDTH, CONTENT_WIDTH)
        self.core = HeptaCore(CONTENT_WIDTH, mode="ordinary" if core == "ordinary" else "dual")
        self.answer = nn.Linear(CONTENT_WIDTH, 1)
        self.box_delta = nn.Linear(CONTENT_WIDTH, 4)
        self.utility_head = nn.Sequential(nn.Linear(STATE_WIDTH, 32), nn.Tanh(), nn.Linear(32, 1))
        self.light_head = nn.Sequential(nn.Linear(STATE_WIDTH, 32), nn.Tanh(), nn.Linear(32, len(ACTIONS)))
        self.transition = nn.Sequential(nn.Linear(STATE_WIDTH + len(ACTIONS), 48), nn.Tanh(),
                                        nn.Linear(48, STATE_WIDTH + 1))
        self.register_buffer("residual_std", torch.full((STATE_WIDTH,), 0.01))

    def content(self, candidates, *, meter=None):
        return self.content_step(candidates, memory_mode="reset", meter=meter)[:3]

    def content_step(self, candidates, *, memory=None, memory_mode="persistent", meter=None):
        if candidates.ndim != 2 or candidates.shape[1] != FEATURE_WIDTH or not len(candidates):
            raise ValueError("Candidate tensor has the wrong dimensions")
        if memory_mode not in MEMORY_MODES or (memory_mode == "reset" and memory is not None):
            raise ValueError("Reset observations must not receive persistent memory")
        with meter.stage("shared", "content core") if meter else nullcontext():
            initial = self.project(candidates).tanh()
            if memory is None:
                state = self.core.initial_state(len(initial), content=initial)
            else:
                if (len(memory) != self.core.depth or any(set(layer) != {"content", "voltage", "adaptation", "event"}
                        or any(value.shape != (1, CONTENT_WIDTH) or value.dtype != initial.dtype
                               or value.device != initial.device or not bool(torch.isfinite(value).all())
                               for value in layer.values()) for layer in memory)):
                    raise ValueError("Invalid episode memory")
                state = [{name: value.expand(len(initial), -1) for name, value in layer.items()} for layer in memory]
            encoded, following, _ = self.core.step(initial, state, 0.5)
            encoded = encoded.tanh()
        with meter.stage("decoder", "text selection and image region heads") if meter else nullcontext():
            logits = self.answer(encoded).squeeze(-1)
            weights = logits.softmax(0)
            shared = (weights[:, None] * encoded).sum(0)
            # Small, learned coordinate refinements around actual OCR regions.
            deltas = self.box_delta(encoded).tanh() * 0.05
            # Candidate count/order may change after a real ROI read. Memory is
            # episode-scoped, never attached to unstable OCR row indices.
            memory = ([{name: (weights[:, None] * value).sum(0, keepdim=True)
                        for name, value in layer.items()} for layer in following]
                      if memory_mode == "persistent" else None)
        return logits, deltas, shared, memory

    def public_state(self, candidates, metadata, *, meter=None):
        return self.public_state_step(candidates, metadata, memory_mode="reset", meter=meter)[:3]

    def public_state_step(self, candidates, metadata, *, memory=None, memory_mode="persistent", meter=None):
        logits, deltas, shared, memory = self.content_step(candidates, memory=memory,
                                                         memory_mode=memory_mode, meter=meter)
        meta = torch.as_tensor(metadata, dtype=shared.dtype, device=shared.device)
        if meta.shape != (META_WIDTH,) or not bool(torch.isfinite(meta).all()):
            raise ValueError("Invalid public deployment metadata")
        ordered = logits.softmax(0).sort(descending=True).values
        confidence = ordered[0]
        margin = confidence - ordered[1] if len(ordered) > 1 else confidence
        meta = torch.cat((meta[:10], confidence[None], margin[None], meta[12:]))
        return torch.cat((shared, meta)), logits, deltas, memory

    def predict_transition(self, states, actions):
        onehot = F.one_hot(actions, len(ACTIONS)).to(states.dtype)
        prediction = self.transition(torch.cat((states, onehot), -1))
        next_state = prediction[..., :STATE_WIDTH]
        next_state = torch.cat((next_state[..., :CONTENT_WIDTH].tanh(),
                                next_state[..., CONTENT_WIDTH:].sigmoid()), -1)
        duration = F.softplus(prediction[..., STATE_WIDTH]) + 1e-4
        return next_state, duration

    def content_parameters(self):
        for module in (self.project, self.core, self.answer, self.box_delta):
            yield from module.parameters()


class FittedPredictor:
    def __init__(self, model, *, meter=None, memory_mode="reset"):
        self.model, self.meter, self.memory_mode = model, meter, memory_mode
        self.model.eval()

    def _tensor(self, state):
        anchor = next(self.model.parameters())
        return torch.tensor(state.features, dtype=anchor.dtype, device=anchor.device)

    def utility(self, state):
        with self.meter.stage("critic", "learned current utility") if self.meter else nullcontext(), torch.inference_mode():
            return float(self.model.utility_head(self._tensor(state)).sigmoid().item())

    def light_scores(self, state):
        with self.meter.stage("critic", "learned light router") if self.meter else nullcontext(), torch.inference_mode():
            values = self.model.light_head(self._tensor(state)).cpu().tolist()
        return {name: values[ACTIONS.index(name)] for name in state.legal_actions}

    def forecast(self, state, action, particles, seed):
        with self.meter.stage("critic", "learned transition forecast") if self.meter else nullcontext(), torch.inference_mode():
            x = self._tensor(state)
            features, duration, legal = forecast_tensors(self.model, x, action, particles, seed,
                state.step, state.remaining_seconds, state.legal_actions, self.memory_mode)
            seconds = float(duration)
        rows = []
        for feature in features:
            with self.meter.stage("critic", "predicted successor utility") if self.meter else nullcontext(), torch.inference_mode():
                utility = float(self.model.utility_head(feature).sigmoid().item())
            if not math.isfinite(seconds):
                raise ValueError("Forecast duration is nonfinite")
            rows.append(Forecast(tuple(float(v) for v in feature), utility, seconds, 1/particles, legal))
        return rows


def forecast_tensors(model, x, action, particles, seed, step, remaining, legal, memory_mode):
    """The same frozen-noise transition in deployment and differentiable unrolls."""
    predicted, duration = model.predict_transition(x[None], torch.tensor([ACTIONS.index(action)], device=x.device))
    duration = duration.squeeze()
    noise = np.random.default_rng(seed).normal(size=(particles, STATE_WIDTH))
    noisy = predicted + x.new_tensor(noise) * model.residual_std
    noisy = torch.cat((noisy[:, :CONTENT_WIDTH].clamp(-1, 1), noisy[:, CONTENT_WIDTH:].clamp(0, 1)), -1)
    meta = x[CONTENT_WIDTH:]
    fields = [noisy[:, i] for i in range(STATE_WIDTH)]
    preserve = [*range(CONTENT_WIDTH, CONTENT_WIDTH + 4), CONTENT_WIDTH + 6, CONTENT_WIDTH + 7]
    if action != "READ_ROI" and memory_mode == "reset":
        preserve += [*range(CONTENT_WIDTH), *range(CONTENT_WIDTH + 10, CONTENT_WIDTH + 13)]
    for i in preserve:
        fields[i] = x[i].expand(particles)
    for i, operation in ((4, "WRITE_TEXT"), (5, "RENDER_IMAGE"), (8, "PREPARE_ROI"), (9, "READ_ROI")):
        fields[CONTENT_WIDTH + i] = x.new_full((particles,), float(action == operation or meta[i] > .5))
    fields[CONTENT_WIDTH + 13] = x.new_full((particles,), min((step + 1) / 8, 1))
    fields[CONTENT_WIDTH + 14] = (meta[14] * (1 - duration / max(remaining, 1e-9)).clamp(min=0)).expand(particles)
    following_legal = tuple(a for a in ACTIONS if (a != "READ_ROI" or action == "PREPARE_ROI" or meta[8] > .5)
                           and (a not in {"WRITE_TEXT", "RENDER_IMAGE"} or a in legal))
    if step + 1 >= 8:
        following_legal = ("STOP",)
    return torch.stack(fields, -1), duration, following_legal
