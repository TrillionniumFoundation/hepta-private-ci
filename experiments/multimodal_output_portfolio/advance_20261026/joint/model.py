"""Public posterior learning with a frozen, actual-codec output portfolio.

The learned object is a conditional target distribution. Deployment minimizes
the corresponding finite conditional cost; no sampled-token/greedy switch is
hidden in the objective. Renderer and feature extractors remain frozen.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

import torch
from torch import nn
from torch.nn import functional as F

from ...abc_recovery.base_recovery import file_sha
from ...closure_20261025.media.network import ingress_state
from ...next_20261025.joint.model import JointModel, PublicTask
from ...next_20261025.media.repair.model import load_ingress
from ...next_20261025.media.runtime import render_state
from ...next_20261025.joint.train import load_initial
from ...v6.neural import parameter_hash


ROUTES = ("image", "text", "audio", "video")
FEATURES = 78
HIDDEN = 32
RESIDUAL_BOUND = 2.0


@dataclass(frozen=True)
class PublicEncoding:
    state: object
    raw_probabilities: torch.Tensor
    features: torch.Tensor
    route: str
    wall_ns: int


class FrozenPortfolio:
    """A frozen five-component reference and its canonical renderer protocol."""

    def __init__(self, paths):
        self.paths = {name: Path(path).resolve() for name, path in paths.items()}
        original = dict(self.paths)
        original["audio_input"] = self.paths["original_audio_input"]
        self.model = load_initial(original).eval().requires_grad_(False)
        self.model.audio_input = load_ingress(self.paths["audio_input"])
        if len(self.model.audio_input.members) != 1:
            raise ValueError("This candidate binds exactly one qualified ingress member")
        self.asset_sha256 = {str(p): file_sha(p) for p in self.paths.values()}
        self.parameter_sha256 = parameter_hash(self.model)

    @torch.no_grad()
    def encode(self, task):
        if type(task) is not PublicTask or task.route not in ROUTES:
            raise TypeError("A public modality task is required; private labels are excluded")
        started = time.perf_counter_ns()
        if task.route == "image":
            count = len(task.observation.pixels)
            state = self.model.encode(task, torch.zeros(count, 96))
            hidden = F.pad(state.h.reshape(count, 2, 48), (0, 16))
            logits = self.model.core.digit_head(state.h.reshape(-1, 48)).reshape(count, 2, 10)
            probabilities = logits.softmax(-1)
        elif task.route == "text":
            if task.text_digits is None or task.text_digits.shape[1:] != (2,):
                raise ValueError("Text input must explicitly provide its two public digits")
            probabilities = F.one_hot(task.text_digits, 10).float()
            count = len(probabilities)
            hidden = torch.zeros(count, 2, 64)
            state = self.model.encode(task, torch.zeros(count, 96))
        elif task.route == "audio":
            member = self.model.audio_input.members[0]
            if task.audio_features is not None:
                observed = task.audio_features.flatten(0, 1)
            elif task.spectrum is not None:
                observed = member.front_end(task.spectrum.flatten(0, 1))
            else:
                raise ValueError("Audio input requires observed acoustic tensors")
            hidden = member.features[:-1](observed).reshape(-1, 2, 64)
            logits = member.features[-1](hidden)
            probabilities = logits.softmax(-1)
            count = len(probabilities)
            state = ingress_state(self.model.core, probabilities)
        else:
            if task.video is None or task.video.shape[1:] != (20, 1, 28, 28):
                raise ValueError("Video input requires twenty actual ordered frames")
            count = len(task.video)
            observed = self.model.video_input.frames(task.video.flatten(0, 1))
            sequence, _ = self.model.video_input.temporal(observed.reshape(count * 2, 10, 32))
            final = sequence[:, -1].reshape(count, 2, 32)
            probabilities = self.model.video_input.head(final).softmax(-1)
            hidden = F.pad(final, (0, 32))
            state = ingress_state(self.model.core, probabilities)
        if task.route in {"audio", "video"}:
            for action in ("refine_semantic", "couple"):
                state = self.model.core.step(state, action)
        normalized = (hidden / hidden.square().mean(-1, keepdim=True).add(1e-6).sqrt()).clamp(-4, 4)
        law = probabilities.clamp_min(1e-8).log()
        route = F.one_hot(torch.full((count, 2), ROUTES.index(task.route)), 4).float()
        features = torch.cat((normalized, (law - law.mean(-1, keepdim=True)).clamp(-12, 12) / 6, route), -1)
        if features.shape != (count, 2, FEATURES) or not torch.isfinite(features).all():
            raise ValueError("Invalid public semantic features")
        return PublicEncoding(state, probabilities, features, task.route, time.perf_counter_ns() - started)

    @torch.no_grad()
    def canonical_state(self, codes):
        codes = torch.as_tensor(codes)
        if codes.dtype not in (torch.int8, torch.int16, torch.int32, torch.int64, torch.uint8):
            raise TypeError("Semantic actions must be integer codes without coercion")
        codes = codes.long().reshape(-1)
        if (codes < 0).any() or (codes >= 100).any():
            raise ValueError("Semantic action must be an integer from zero through 99")
        digits = torch.stack((codes // 10, codes % 10), -1)
        state = ingress_state(self.model.core, F.one_hot(digits, 10).float())
        for action in ("refine_semantic", "couple"):
            state = self.model.core.step(state, action)
        return state

    @torch.no_grad()
    def render(self, code, directory, request_id):
        state = self.canonical_state([code])
        result = render_state(self.model.core, self.model.speech, self.model.motion,
                              state, directory, request_id)
        return {**result, "semantic_action": int(code), "renderer_parameter_sha256": self.parameter_sha256,
                "semantic_action_schema": "left_times_10_plus_right; canonical two-continuation renderer"}

    def assert_frozen(self):
        if parameter_hash(self.model) != self.parameter_sha256:
            raise ValueError("A supposedly frozen component changed")
        if any(file_sha(Path(p)) != h for p, h in self.asset_sha256.items()):
            raise ValueError("Frozen model asset changed")


class SemanticAdapter(nn.Module):
    """Bounded residual posterior adapter; zero last layer preserves its reference."""

    def __init__(self):
        super().__init__()
        self.first = nn.Linear(FEATURES, HIDDEN)
        self.last = nn.Linear(HIDDEN, 10)
        nn.init.zeros_(self.last.weight)
        nn.init.zeros_(self.last.bias)

    def forward(self, features, raw_probabilities, text_mask=None):
        if features.shape[-2:] != (2, FEATURES) or raw_probabilities.shape != (*features.shape[:-1], 10):
            raise ValueError("Adapter requires paired public features and paired probabilities")
        residual = RESIDUAL_BOUND * self.last(self.first(features).tanh()).tanh()
        probability = (raw_probabilities.clamp_min(1e-8).log() + residual).softmax(-1)
        if text_mask is not None:
            probability = torch.where(text_mask[:, None, None], raw_probabilities, probability)
        return probability

    def export_native(self, endpoint, path):
        record = {"schema": "hepta.advance.semantic-adapter-native.v1", "features_per_digit": FEATURES,
                  "hidden": HIDDEN, "activation": "tanh", "residual_bound": RESIDUAL_BOUND,
                  "raw_probability_floor": 1e-8, "text_route_bypasses_adapter": True,
                  "parameter_sha256": parameter_hash(self), "state_dict": {k: v.detach().double().tolist()
                                                                          for k, v in self.state_dict().items()},
                  "utility_action_by_target": endpoint["utility_action_by_target"],
                  "strict_success_action_by_target": endpoint["strict_success_action_by_target"],
                  "gamma": 2., "action_code": "left*10+right",
                  "interpretation": "Predicted target law; raw expected success is not a calibration certificate",
                  "endpoint_table_sha256": hashlib.sha256(json.dumps(endpoint, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()}
        Path(path).write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        return record


def pair_law(probabilities):
    if probabilities.shape[-2:] != (2, 10):
        raise ValueError("A pair of ten-class posterior laws is required")
    return (probabilities[:, 0, :, None] * probabilities[:, 1, None, :]).reshape(-1, 100)


def fuse_digit_laws(before, arrived, prior=None):
    """Public external-evidence update under an explicit conditional-independence model.

    This is not an information gain from our own generated output. The caller
    must bind an independently arrived observation. Uniform class prior is the
    registered default; the two digits remain a factorized approximation.
    """
    if before.shape != arrived.shape or before.shape[-2:] != (2, 10):
        raise ValueError("Fusion requires paired public digit posterior laws")
    if (not torch.isfinite(before).all() or not torch.isfinite(arrived).all()
            or (before < 0).any() or (arrived < 0).any()
            or not torch.allclose(before.sum(-1), torch.ones_like(before[..., 0]), atol=1e-5)
            or not torch.allclose(arrived.sum(-1), torch.ones_like(arrived[..., 0]), atol=1e-5)):
        raise ValueError("Malformed external-evidence probabilities")
    reference = torch.full_like(before, .1) if prior is None else prior
    if reference.shape != before.shape or not torch.isfinite(reference).all() or (reference <= 0).any():
        raise ValueError("A finite positive registered class prior is required")
    law = before.clamp_min(1e-8).log() + arrived.clamp_min(1e-8).log() - reference.log()
    return law.softmax(-1)


def cost_matrix(utility, profile, gamma=2.):
    if profile == "mean":
        return -utility.double()
    if profile == "entropic":
        return torch.exp(-gamma * utility.double())
    raise ValueError("Unregistered conditional-cost profile")


def regression_matrix(utility, profile, gamma=2.):
    """Normalize outcome-vector regression, exposing binary affine equivalence.

    Row constants cancel because predicted and observed target laws both sum
    to one. A single global positive scale changes neither the population
    minimizer nor action ordering. Binary utilities make the two normalized
    regressions algebraically identical; use the same expression in that case.
    """
    levels = torch.unique(utility.double())
    affine_binary = len(levels) <= 2
    raw = -utility.double() if affine_binary else cost_matrix(utility, profile, gamma)
    centered = raw - raw.mean(-1, keepdim=True)
    scale = centered.square().mean().sqrt()
    if scale <= 0:
        raise ValueError("All endpoints have identical utility; conditional learning is unidentifiable")
    return centered / scale, {"affine_binary_equivalence": affine_binary,
                              "actual_utility_levels": levels.tolist(), "normalization_scale": float(scale)}


def conditional_loss(q, target_codes, regression):
    predicted = q.double() @ regression.T
    observed = regression[:, target_codes].T
    return (predicted - observed).square().mean()


def select_action(q, utility, profile):
    values = q.double() @ cost_matrix(utility, profile).T
    return values.argmin(-1), values
