"""Public semantic features from an independently trained, deployable reader.

Neither reward observer is imported or loaded here. The reader is trained only
on generator-training sources; its probabilities are approximate features, not
certified posteriors. Public hint reliability comes from the task declaration,
never from whether a particular untrusted hint happened to be correct.
"""

from dataclasses import dataclass
import math

import torch
from torch import nn
from torch.nn import functional as F

from ..v6.data import BOS, DIGIT_OFFSET, EOS, Observation
from ..v7.model import validate_observation
from ..abc_recovery.runtime import PublicFrame, public_features


EXTRA_DIM = 90
ENRICHED_DIM = 673 + EXTRA_DIM


class PublicDigitSensor(nn.Module):
    """A separate two-channel image/mask recognizer, with a training-only prior."""

    def __init__(self, seed=20261025):
        super().__init__()
        generator = torch.Generator().manual_seed(seed)
        with torch.random.fork_rng(devices=[]):
            torch.random.set_rng_state(generator.get_state())
            self.net = nn.Sequential(
                nn.Conv2d(2, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Flatten(), nn.Linear(32 * 7 * 7, 64), nn.ReLU(), nn.Linear(64, 10))
        self.register_buffer("prior", torch.full((10,), .1))
        self.register_buffer("temperature", torch.ones(()))

    def forward(self, pixels, mask):
        if (pixels.ndim != 4 or pixels.shape[1:] != (1, 28, 28)
                or mask.shape != pixels.shape or not torch.isfinite(pixels).all()
                or not torch.isfinite(mask).all()):
            raise ValueError("Expected finite image/mask panels")
        return self.net(torch.cat((pixels, mask), 1)) / self.temperature


@dataclass(frozen=True)
class PublicEvidence:
    """Reusable input-only evidence in requested output order; contains no target."""

    probabilities: torch.Tensor
    visibility: torch.Tensor
    reliability: torch.Tensor
    hint_present: torch.Tensor
    pixels: torch.Tensor
    mask: torch.Tensor


def _frozen(sensor):
    if not isinstance(sensor, PublicDigitSensor) or sensor.training or any(p.requires_grad for p in sensor.parameters()):
        raise TypeError("Expected frozen eval-mode public sensor")


def _panels(pixels):
    return torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), 1)


@torch.no_grad()
def input_evidence(sensor, observation, work=None):
    """Encode original public pixels, mask, command and declared hint channel.

    Command routing here orders *features*. It never rewrites generator states,
    pixels or captions. A missing visual panel uses only the training prior.
    """
    _frozen(sensor)
    if not isinstance(observation, Observation):
        raise TypeError("Only public Observation is accepted")
    validate_observation(observation)
    pixels, mask = _panels(observation.pixels), _panels(observation.mask)
    batch = len(pixels)
    visibility = mask.mean((2, 3, 4))
    probabilities = sensor(pixels.flatten(0, 1), mask.flatten(0, 1)).softmax(-1).reshape(batch, 2, 10)
    probabilities = torch.where((visibility > 0)[..., None], probabilities, sensor.prior.expand(batch, 2, 10))
    hints = observation.text_tokens[:, (3, 5)] - DIGIT_OFFSET
    present = (hints >= 0) & (hints < 10)
    reliability = observation.text_tokens[:, (2, 4)] != 11
    hint_onehot = F.one_hot(hints.clamp(0, 9), 10).float()
    # Known corruption law: an untrusted hint is correct with probability 1/2,
    # otherwise a uniformly selected different digit. Recognition is approximate.
    likelihood = hint_onehot * .5 + (1 - hint_onehot) * (.5 / 9)
    conditioned = probabilities * likelihood
    conditioned = conditioned / conditioned.sum(-1, keepdim=True).clamp_min(1e-12)
    probabilities = torch.where((present & ~reliability)[..., None], conditioned, probabilities)
    probabilities = torch.where((present & reliability)[..., None], hint_onehot, probabilities)
    order = torch.tensor([0, 1]).expand(batch, 2).clone()
    swap = observation.text_tokens[:, 1] == 10
    order[swap] = order[swap].flip(1)
    rows = torch.arange(batch)[:, None]
    if work is not None:
        work["public_input_sensor_calls"] = work.get("public_input_sensor_calls", 0) + 1
        work["public_input_sensor_panel_examples"] = work.get("public_input_sensor_panel_examples", 0) + 2 * batch
    return PublicEvidence(*(value[rows, order].detach().clone() for value in
                            (probabilities, visibility, reliability.float(), present.float(), pixels, mask)))


def _entropy(probabilities):
    return -(probabilities * probabilities.clamp_min(1e-12).log()).sum(-1) / math.log(10)


@torch.no_grad()
def semantic_features(sensor, frame, evidence, work=None):
    """A 90-dimensional summary of approximate facts and observed output quality."""
    _frozen(sensor)
    if not isinstance(frame, PublicFrame) or not isinstance(evidence, PublicEvidence):
        raise TypeError("Expected public frame and input-only evidence")
    batch = len(frame.pixels)
    if evidence.probabilities.shape != (batch, 2, 10):
        raise ValueError("Public evidence cardinality mismatch")
    panels = _panels(frame.pixels)
    draft = sensor(panels.flatten(0, 1), torch.ones_like(panels).flatten(0, 1)).softmax(-1).reshape(batch, 2, 10)
    tokens = frame.tokens
    digits = tokens[:, (2, 4)] - DIGIT_OFFSET
    valid_digits = ((digits >= 0) & (digits < 10)).all(1)
    valid = (valid_digits & (tokens[:, 0] == BOS) & (tokens[:, 1] == 3)
             & (tokens[:, 3] == 4) & (tokens[:, 5] == 5)
             & (tokens[:, 6] >= 6) & (tokens[:, 6] <= 8) & (tokens[:, 7] == EOS))
    text = F.one_hot(digits.clamp(0, 9), 10).float() * valid[:, None, None]
    relation = F.one_hot((tokens[:, 6] - 6).clamp(0, 2), 3).float() * valid[:, None]
    joint = evidence.probabilities[:, 0, :, None] * evidence.probabilities[:, 1, None, :]
    expected_relation = torch.stack((joint.triu(1).sum((1, 2)), joint.diagonal(dim1=1, dim2=2).sum(1),
                                     joint.tril(-1).sum((1, 2))), 1)
    agreements = torch.cat(((evidence.probabilities * draft).sum(-1),
                            (evidence.probabilities * text).sum(-1),
                            (draft * text).sum(-1),
                            (expected_relation * relation).sum(-1, keepdim=True)), 1)
    uncertainty = torch.cat((_entropy(evidence.probabilities), _entropy(draft),
                             evidence.probabilities.max(-1).values, draft.max(-1).values), 1)
    mask_mass = evidence.mask.sum((2, 3, 4))
    public_pixel_error = ((panels - evidence.pixels).square() * evidence.mask).sum((2, 3, 4)) / mask_mass.clamp_min(1)
    # 20 input + 20 draft + 20 text + 3 relation + 3 expected relation +
    # 2 visible + 2 reliable + 2 hint-present + 7 agreement + 8 uncertainty +
    # 2 observed-pixel errors + 1 caption-valid = 90.
    features = torch.cat((evidence.probabilities.flatten(1), draft.flatten(1), text.flatten(1),
                          relation, expected_relation, evidence.visibility, evidence.reliability,
                          evidence.hint_present, agreements, uncertainty, public_pixel_error,
                          valid[:, None].float()), 1).float().detach()
    if features.shape != (batch, EXTRA_DIM) or not torch.isfinite(features).all():
        raise ValueError(f"Public semantic feature schema differs: {tuple(features.shape)}")
    if work is not None:
        work["public_draft_sensor_calls"] = work.get("public_draft_sensor_calls", 0) + 1
        work["public_draft_sensor_panel_examples"] = work.get("public_draft_sensor_panel_examples", 0) + 2 * batch
    return features


@torch.no_grad()
def observed_features(model, frame, *, sensor=None, evidence=None, work=None):
    """Keep the remaining-budget column last for fitted finite-horizon models."""
    base = public_features(model, frame, work=work)
    if sensor is None and evidence is None:
        return base
    extra = semantic_features(sensor, frame, evidence, work)
    return torch.cat((base[:, :-1], extra, base[:, -1:]), 1)
