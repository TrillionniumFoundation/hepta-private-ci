"""Exact reusable visual features and a no-CNN public-state alternative."""

from collections import Counter
import math

import torch
from torch.nn import functional as F

from ...abc_next.observability import input_evidence
from ...abc_recovery.runtime import PublicFrame
from ...v6.data import BOS, DIGIT_OFFSET, EOS, VOCAB


COMPACT_DIM = 577


def compact_from_full(full):
    if full.shape[-1] != 763:
        raise ValueError("Expected the frozen 763-column public schema")
    return torch.cat((full[..., :384], full[..., 480:672], full[..., -1:]), -1)


@torch.no_grad()
def compact_frame(frame):
    if not isinstance(frame, PublicFrame):
        raise TypeError("Only current public state is permitted")
    latent = torch.cat(tuple(getattr(frame.state, name) for name in ("h", "image", "text", "context")), 1)
    text = F.one_hot(frame.tokens, num_classes=len(VOCAB)).flatten(1).to(latent.dtype)
    budget = torch.full((len(latent), 1), frame.remaining / 2, dtype=latent.dtype)
    return torch.cat((latent, text, budget), 1).float().detach()


def entropy(probabilities):
    return -(probabilities * probabilities.clamp_min(1e-12).log()).sum(-1) / math.log(10)


class ExactFeatureCache:
    """Memoize only functions of byte-identical current public draft pixels.

    Cache lifetime is one request. Latents, tokens and budget are always rebuilt;
    neither source identities nor private targets are accepted by this API.
    """

    def __init__(self, model, sensor, observation, work=None):
        self.model, self.sensor = model, sensor
        self.work = work if work is not None else Counter()
        self.evidence = input_evidence(sensor, observation, self.work)
        self.pixels = self.visual = self.draft = None

    @torch.no_grad()
    def read(self, frame):
        if not isinstance(frame, PublicFrame):
            raise TypeError("Only current PublicFrame is permitted")
        batch = len(frame.pixels)
        panels = torch.stack((frame.pixels[:, :, :, :28], frame.pixels[:, :, :, 28:]), 1)
        if self.pixels is None or not torch.equal(frame.pixels, self.pixels):
            flattened = panels.flatten(0, 1)
            self.visual = self.model.pixel_encoder(torch.cat((flattened, torch.ones_like(flattened)), 1)).reshape(batch, -1)
            self.draft = self.sensor(flattened, torch.ones_like(flattened)).softmax(-1).reshape(batch, 2, 10)
            self.pixels = frame.pixels.detach().clone()
            self.work.update({"draft_pixel_encoder_calls": 1, "public_draft_sensor_calls": 1,
                              "draft_pixel_encoder_panel_examples": 2 * batch,
                              "public_draft_sensor_panel_examples": 2 * batch})
        else:
            self.work.update({"exact_pixel_cache_hits": 1, "exact_pixel_cache_examples": batch})
        latent = torch.cat(tuple(getattr(frame.state, name) for name in ("h", "image", "text", "context")), 1)
        textual = F.one_hot(frame.tokens, num_classes=len(VOCAB)).flatten(1).to(latent.dtype)
        tokens, evidence, draft = frame.tokens, self.evidence, self.draft
        digits = tokens[:, (2, 4)] - DIGIT_OFFSET
        valid_digits = ((digits >= 0) & (digits < 10)).all(1)
        valid = (valid_digits & (tokens[:, 0] == BOS) & (tokens[:, 1] == 3)
                 & (tokens[:, 3] == 4) & (tokens[:, 5] == 5)
                 & (tokens[:, 6] >= 6) & (tokens[:, 6] <= 8) & (tokens[:, 7] == EOS))
        text = F.one_hot(digits.clamp(0, 9), 10).float() * valid[:, None, None]
        relation = F.one_hot((tokens[:, 6] - 6).clamp(0, 2), 3).float() * valid[:, None]
        joint = evidence.probabilities[:, 0, :, None] * evidence.probabilities[:, 1, None, :]
        expected = torch.stack((joint.triu(1).sum((1, 2)), joint.diagonal(dim1=1, dim2=2).sum(1), joint.tril(-1).sum((1, 2))), 1)
        agreements = torch.cat(((evidence.probabilities * draft).sum(-1), (evidence.probabilities * text).sum(-1),
                                (draft * text).sum(-1), (expected * relation).sum(-1, keepdim=True)), 1)
        uncertainty = torch.cat((entropy(evidence.probabilities), entropy(draft), evidence.probabilities.max(-1).values,
                                 draft.max(-1).values), 1)
        mass = evidence.mask.sum((2, 3, 4))
        error = ((panels - evidence.pixels).square() * evidence.mask).sum((2, 3, 4)) / mass.clamp_min(1)
        extra = torch.cat((evidence.probabilities.flatten(1), draft.flatten(1), text.flatten(1), relation, expected,
                           evidence.visibility, evidence.reliability, evidence.hint_present, agreements,
                           uncertainty, error, valid[:, None].float()), 1)
        budget = torch.full((batch, 1), frame.remaining / 2, dtype=latent.dtype)
        result = torch.cat((latent, self.visual, textual, extra, budget), 1).float().detach()
        if result.shape != (batch, 763) or not torch.isfinite(result).all():
            raise ValueError("Cached public schema differs")
        self.work.update({"public_feature_calls": 1, "public_feature_examples": batch, "token_onehot_examples": batch})
        return result
