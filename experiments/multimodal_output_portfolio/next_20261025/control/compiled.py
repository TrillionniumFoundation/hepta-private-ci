"""Frozen tensor execution of the existing conditional-NDU teacher.

This is a function-preserving implementation candidate, not an improved actor.
The public reader and all its costs remain present. Near ties fall back to the
original arithmetic. Compilation and qualification are charged separately.
"""

import copy

import torch
from torch import nn
from torch.nn import functional as F

from ...abc_followup.control.features import ExactFeatureCache, entropy
from ...v6.data import BOS, DIGIT_OFFSET, EOS, VOCAB


TIE_MARGIN = 1e-5


class TensorHeads(nn.Module):
    """Keep the teacher's original parameter order and operations."""

    def __init__(self, controller):
        super().__init__()
        self.one = copy.deepcopy(controller.one)
        self.two = copy.deepcopy(controller.two)
        self.enriched = controller.mode == "enriched"

    def forward(self, public):
        x = public if self.enriched else torch.cat((public[:, :672], public[:, -1:]), 1)
        return self.one(x), self.two(x)


class VisualPair(nn.Module):
    """A traced pair of the unchanged public draft readers."""

    def __init__(self, model, sensor):
        super().__init__()
        self.visual = copy.deepcopy(model.pixel_encoder)
        self.sensor = copy.deepcopy(sensor)

    def forward(self, pixels):
        panels = torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), 1).flatten(0, 1)
        mask = torch.ones_like(panels)
        return self.visual(torch.cat((panels, mask), 1)).reshape(-1, 96), self.sensor(panels, mask).softmax(-1).reshape(-1, 2, 10)


class TensorSummary(nn.Module):
    """The original semantic-summary expressions in one frozen tensor graph."""

    def forward(self, latent, visual, draft, pixels, tokens, probabilities,
                visibility, reliability, hint_present, observed, mask, budget):
        panels = torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), 1)
        textual = F.one_hot(tokens, num_classes=len(VOCAB)).flatten(1).to(latent.dtype)
        digits = tokens[:, (2, 4)] - DIGIT_OFFSET
        valid_digits = ((digits >= 0) & (digits < 10)).all(1)
        valid = (valid_digits & (tokens[:, 0] == BOS) & (tokens[:, 1] == 3)
                 & (tokens[:, 3] == 4) & (tokens[:, 5] == 5)
                 & (tokens[:, 6] >= 6) & (tokens[:, 6] <= 8) & (tokens[:, 7] == EOS))
        text = F.one_hot(digits.clamp(0, 9), 10).float() * valid[:, None, None]
        relation = F.one_hot((tokens[:, 6] - 6).clamp(0, 2), 3).float() * valid[:, None]
        joint = probabilities[:, 0, :, None] * probabilities[:, 1, None, :]
        expected = torch.stack((joint.triu(1).sum((1, 2)), joint.diagonal(dim1=1, dim2=2).sum(1), joint.tril(-1).sum((1, 2))), 1)
        agreements = torch.cat(((probabilities * draft).sum(-1), (probabilities * text).sum(-1),
                                (draft * text).sum(-1), (expected * relation).sum(-1, keepdim=True)), 1)
        uncertainty = torch.cat((entropy(probabilities), entropy(draft), probabilities.max(-1).values,
                                 draft.max(-1).values), 1)
        mass = mask.sum((2, 3, 4))
        error = ((panels - observed).square() * mask).sum((2, 3, 4)) / mass.clamp_min(1)
        extra = torch.cat((probabilities.flatten(1), draft.flatten(1), text.flatten(1), relation, expected,
                           visibility, reliability, hint_present, agreements, uncertainty, error, valid[:, None].float()), 1)
        return torch.cat((latent, visual, textual, extra, budget), 1).float()


class CompiledCache(ExactFeatureCache):
    """Retain the original public bookkeeping while executing frozen CNN graphs."""

    def __init__(self, model, sensor, observation, readers, summary, work=None):
        super().__init__(model, sensor, observation, work)
        self.readers, self.summary = readers, summary

    @torch.no_grad()
    def read(self, frame):
        batch = len(frame.pixels)
        fresh = self.pixels is None or not torch.equal(frame.pixels, self.pixels)
        if fresh:
            self.visual, self.draft = self.readers(frame.pixels)
            self.pixels = frame.pixels.detach().clone()
            self.work.update({"draft_pixel_encoder_calls": 1, "public_draft_sensor_calls": 1,
                              "draft_pixel_encoder_panel_examples": 2 * batch,
                              "public_draft_sensor_panel_examples": 2 * batch,
                              "compiled_visual_pair_calls": 1})
        else:
            self.work.update({"exact_pixel_cache_hits": 1, "exact_pixel_cache_examples": batch})
        latent = torch.cat(tuple(getattr(frame.state, name) for name in ("h", "image", "text", "context")), 1)
        budget = torch.full((batch, 1), frame.remaining / 2, dtype=latent.dtype)
        e = self.evidence
        result = self.summary(latent, self.visual, self.draft, frame.pixels, frame.tokens,
                              e.probabilities, e.visibility, e.reliability, e.hint_present, e.pixels, e.mask, budget)
        if result.shape != (batch, 763) or not torch.isfinite(result).all():
            raise ValueError("Compiled public schema differs")
        self.work.update({"public_feature_calls": 1, "public_feature_examples": batch, "token_onehot_examples": batch})
        return result


class CompiledTeacher:
    """B=1 qualified graph with an exact-original fallback at a near tie."""

    def __init__(self, model, sensor, original):
        self.original = original
        with torch.inference_mode():
            trace = torch.jit.trace(TensorHeads(original).eval(), torch.zeros(1, 763), check_trace=True)
            self.heads = torch.jit.freeze(trace)
            visual = torch.jit.trace(VisualPair(model, sensor).eval(), torch.zeros(1, 1, 28, 56), check_trace=True)
            self.readers = torch.jit.freeze(visual)
            args = (torch.zeros(1, 384), torch.zeros(1, 96), torch.full((1, 2, 10), .1),
                    torch.zeros(1, 1, 28, 56), torch.zeros(1, 8, dtype=torch.long), torch.full((1, 2, 10), .1),
                    torch.ones(1, 2), torch.ones(1, 2), torch.zeros(1, 2), torch.zeros(1, 2, 1, 28, 28),
                    torch.ones(1, 2, 1, 28, 28), torch.ones(1, 1))
            self.summary = torch.jit.freeze(torch.jit.trace(TensorSummary().eval(), args, check_trace=True))

    @torch.inference_mode()
    def values(self, public, remaining):
        if public.shape != (1, 763) or not torch.isfinite(public).all() or remaining not in (1, 2):
            raise ValueError("Compiled teacher requires a finite B=1 registered public frame")
        one, two = self.heads(public)
        result = one if remaining == 1 else two
        if result.shape != (1, 5) or not torch.isfinite(result).all() or not (result > 0).all():
            raise ValueError("Compiled moment head produced invalid conditional moments")
        if remaining == 1:
            result = result.clone(); result[:, 1] = float("inf")
        return result

    @torch.inference_mode()
    def choose(self, public, remaining, work=None):
        result = self.values(public, remaining)
        ordered = result.sort(-1).values
        fallback = bool((ordered[:, 1] - ordered[:, 0] <= TIE_MARGIN).any())
        if work is not None:
            work["compiled_teacher_calls"] += 1
            work["near_tie_original_fallbacks"] += int(fallback)
        return self.original.choose(public, remaining) if fallback else result.argmin(-1)

    def cache(self, model, sensor, observation, work=None):
        return CompiledCache(model, sensor, observation, self.readers, self.summary, work)
