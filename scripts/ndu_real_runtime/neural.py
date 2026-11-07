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
        if candidates.ndim != 2 or candidates.shape[1] != FEATURE_WIDTH or not len(candidates):
            raise ValueError("Candidate tensor has the wrong dimensions")
        with meter.stage("shared", "content core") if meter else nullcontext():
            initial = self.project(candidates).tanh()
            state = self.core.initial_state(len(initial), content=initial)
            encoded, _, _ = self.core.step(initial, state, 0.5)
            encoded = encoded.tanh()
        with meter.stage("decoder", "text selection and image region heads") if meter else nullcontext():
            logits = self.answer(encoded).squeeze(-1)
            weights = logits.softmax(0)
            shared = (weights[:, None] * encoded).sum(0)
            # Small, learned coordinate refinements around actual OCR regions.
            deltas = self.box_delta(encoded).tanh() * 0.05
        return logits, deltas, shared

    def public_state(self, candidates, metadata, *, meter=None):
        logits, deltas, shared = self.content(candidates, meter=meter)
        meta = torch.as_tensor(metadata, dtype=shared.dtype, device=shared.device)
        if meta.shape != (META_WIDTH,) or not bool(torch.isfinite(meta).all()):
            raise ValueError("Invalid public deployment metadata")
        ordered = logits.softmax(0).sort(descending=True).values
        confidence = ordered[0]
        margin = confidence - ordered[1] if len(ordered) > 1 else confidence
        meta = torch.cat((meta[:10], confidence[None], margin[None], meta[12:]))
        return torch.cat((shared, meta)), logits, deltas

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
    def __init__(self, model, *, meter=None):
        self.model, self.meter = model, meter
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
            following, duration = self.model.predict_transition(
                x[None, :], torch.tensor([ACTIONS.index(action)], device=x.device))
            following = following[0].cpu().numpy()
            std = self.model.residual_std.cpu().numpy()
            seconds = float(duration.item())
        generator = np.random.default_rng(seed)
        rows = []
        for _ in range(particles):
            feature = following + generator.normal(0, std)
            feature[:CONTENT_WIDTH] = np.clip(feature[:CONTENT_WIDTH], -1, 1)
            feature[CONTENT_WIDTH:] = np.clip(feature[CONTENT_WIDTH:], 0, 1)
            # Query/requirements and already-visible delivery flags are known
            # protocol state, not hidden forecasts. Only a real READ can change
            # the underlying image observation or its encoded candidates.
            feature[CONTENT_WIDTH:CONTENT_WIDTH+4] = state.features[CONTENT_WIDTH:CONTENT_WIDTH+4]
            feature[CONTENT_WIDTH+6:CONTENT_WIDTH+8] = state.features[CONTENT_WIDTH+6:CONTENT_WIDTH+8]
            feature[CONTENT_WIDTH+4] = float(action == "WRITE_TEXT" or state.features[CONTENT_WIDTH+4] > .5)
            feature[CONTENT_WIDTH+5] = float(action == "RENDER_IMAGE" or state.features[CONTENT_WIDTH+5] > .5)
            if action != "READ_ROI":
                feature[:CONTENT_WIDTH] = state.features[:CONTENT_WIDTH]
                feature[CONTENT_WIDTH+10:CONTENT_WIDTH+13] = state.features[CONTENT_WIDTH+10:CONTENT_WIDTH+13]
            feature[CONTENT_WIDTH+13] = min((state.step + 1) / 8, 1)
            feature[CONTENT_WIDTH+14] = state.features[CONTENT_WIDTH+14] * max(0.0, 1-seconds/max(state.remaining_seconds, 1e-9))
            # Prepared/read availability follows selected public operations,
            # not a learned guess about secret task labels.
            feature[CONTENT_WIDTH + 8] = float(action == "PREPARE_ROI" or state.features[CONTENT_WIDTH + 8] > .5)
            feature[CONTENT_WIDTH + 9] = float(action == "READ_ROI" or state.features[CONTENT_WIDTH + 9] > .5)
            legal = tuple(a for a in ACTIONS
                if not (a == "READ_ROI" and feature[CONTENT_WIDTH + 8] <= .5)
                and not (a in {"WRITE_TEXT", "RENDER_IMAGE"} and a not in state.legal_actions))
            with self.meter.stage("critic", "predicted successor utility") if self.meter else nullcontext(), torch.inference_mode():
                value = torch.as_tensor(feature, dtype=x.dtype, device=x.device)
                utility = float(self.model.utility_head(value).sigmoid().item())
            if not math.isfinite(seconds):
                raise ValueError("Forecast duration is nonfinite")
            rows.append(Forecast(tuple(float(v) for v in feature), utility, seconds, 1/particles, legal))
        return rows
