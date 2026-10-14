"""Typed, non-authorizing AMCN multimodal projection and train-only connector.

This is NOT physical image/audio/video encoder execution. Tensors must be
externally materialized by separately reviewed frozen towers, with per-span
digest and scope. Does not interpret screenshot pixels or invent observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from hashlib import sha256

import torch
from torch import nn
from torch.nn import functional as F

from amcn_core import is_sha, require, digest, shadow_disposition
from experiments.shared_stem_cell.execution import measured, parameters, tensor_digest

MODALITIES = ("text", "image", "audio", "video")
SCHEMA = "hepta.amcn.multimodal-connector.v1"


@dataclass(frozen=True)
class Span:
    span_id: str
    source_event: str
    source_root: str
    scope: str
    generation: str
    modality: str
    asset_sha256: str
    preprocessor_sha256: str
    encoder_sha256: str
    start_ms: int
    end_ms: int
    revoked: bool = False

    def __post_init__(self):
        require(all(isinstance(x, str) and x and len(x) <= 256 for x in
                    (self.span_id, self.source_event, self.source_root,
                     self.scope, self.generation)), "span identity")
        require(self.modality in MODALITIES, "unknown modality")
        require(all(is_sha(x) for x in
                    (self.asset_sha256, self.preprocessor_sha256, self.encoder_sha256)),
                "external modality inventory")
        require(type(self.start_ms) is int and type(self.end_ms) is int
                and 0 <= self.start_ms <= self.end_ms <= 2**53 - 1,
                "temporal interval")
        require(type(self.revoked) is bool, "revocation state")


@dataclass(frozen=True)
class Binding:
    text_span: Span
    other_span: Span
    relation_sha256: str
    maximum_time_gap_ms: int

    def __post_init__(self):
        a, b = self.text_span, self.other_span
        require(a.modality == "text" and b.modality in ("image", "audio", "video"),
                "typed cross-modal pairing")
        require(a.source_event == b.source_event and a.source_root == b.source_root
                and a.scope == b.scope and a.generation == b.generation,
                "cross-source pairing needs separately admitted relationship")
        require(not a.revoked and not b.revoked and is_sha(self.relation_sha256),
                "untrusted or revoked span")
        require(type(self.maximum_time_gap_ms) is int
                and 0 <= self.maximum_time_gap_ms <= 600000, "bounded synchronization")
        gap = max(0, max(a.start_ms, b.start_ms) - min(a.end_ms, b.end_ms))
        require(gap <= self.maximum_time_gap_ms, "unmatched modality timestamps")


@dataclass(frozen=True)
class TrainingPair:
    """Explicit TRAIN contrast: positives require a supported Binding.

    Negatives must be cross-event within one scope/generation; they are never
    cast as a real co-reference or written to the HNMF evidence graph.
    """
    text_span: Span
    other_span: Span
    pair_sha256: str
    positive: bool
    split: str
    relation_sha256: str | None = None

    def __post_init__(self):
        a, b = self.text_span, self.other_span
        require(self.split == "train" and type(self.positive) is bool
                and is_sha(self.pair_sha256), "training-only contrast identity")
        require(a.modality == "text" and b.modality in ("image", "audio", "video")
                and a.scope == b.scope and a.generation == b.generation
                and not a.revoked and not b.revoked, "cross-scope/expired contrast")
        if self.positive:
            require(is_sha(self.relation_sha256), "missing matching support")
            Binding(a, b, self.relation_sha256, maximum_time_gap_ms=600000)
        else:
            require(a.source_event != b.source_event
                    and self.relation_sha256 is None, "false negative co-reference")

def _checked(x, maximum_width=8192):
    require(isinstance(x, torch.Tensor) and x.dtype == torch.float32
            and x.device.type == "cpu" and x.ndim == 2 and 1 <= len(x) <= 4096
            and 1 <= x.shape[1] <= maximum_width and bool(torch.isfinite(x).all()),
            "actual bounded tensor values required")
    return x.detach().clone().contiguous()


class Connector(nn.Module):
    """Small learned projection from already-admitted frozen modalities."""
    def __init__(self, text_width, other_width, latent=32):
        super().__init__()
        require(all(type(n) is int and 1 <= n <= 8192 for n in
                    (text_width, other_width, latent)), "connector geometry")
        self.text = nn.Linear(text_width, latent, bias=False)
        self.other = nn.Linear(other_width, latent, bias=False)

    def forward(self, text, other):
        a = F.normalize(self.text(text), dim=-1)
        b = F.normalize(self.other(other), dim=-1)
        return (a * b).sum(dim=-1)


def train_connector(pairs, text_features, other_features, *,
                    split, seed=17, steps=40, latent=32):
    """Train only same-TRAIN matched/wrong-pair examples; no future labels.

    Caller must supply materialized tower receipts independently; this trainer
    has no access to raw source or image/audio/video files or model credentials.
    """
    require(type(steps) is int and 1 <= steps <= 512, "multimodal training budget")
    require(split == "train" and isinstance(pairs, (tuple, list))
            and 4 <= len(pairs) <= 4096, "TRAIN-only paired examples")
    require(all(isinstance(p, TrainingPair) and p.split == "train" for p in pairs),
            "typed TRAIN-only pairing contrasts")
    ids = [p.pair_sha256 for p in pairs]
    require(len(set(ids)) == len(ids), "duplicate pairing support")
    require(len({p.text_span.scope for p in pairs}) == 1
            and len({p.text_span.generation for p in pairs}) == 1,
            "cross-scope/generation training")
    x, z = _checked(text_features), _checked(other_features)
    require(len(x) == len(z) == len(pairs), "tensor/binding cardinality")
    require({p.positive for p in pairs} == {False, True}, "matched and wrong-pair contrasts")
    y = torch.tensor([float(p.positive) for p in pairs], dtype=torch.float32)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        initial = Connector(x.shape[1], z.shape[1], latent)
    control = deepcopy(initial).eval()
    initial_digest = parameters(control)["sha256"]
    model = deepcopy(initial).train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.005, weight_decay=0)
    with measured() as work:
        for _ in range(steps):
            optimizer.zero_grad(set_to_none=True)
            score = model(x, z)
            # bounded correlation score, not a calibrated similarity probability
            loss = F.binary_cross_entropy_with_logits(score * 4, y)
            require(bool(torch.isfinite(loss)), "invalid connector loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
    model.eval()
    require(parameters(control)["sha256"] == initial_digest
            and parameters(model)["sha256"] != initial_digest,
            "frozen connector changed or no physical update")
    with torch.no_grad():
        frozen = control(x, z).tolist()
        trained = model(x, z).tolist()
    return {"frozen": control, "trained": model,
            "scores": [{"binding_sha256": sid, "frozen": a, "trained": b}
                       for sid, a, b in zip(ids, frozen, trained)],
            "receipt": shadow_disposition(
                profile=SCHEMA, source_binding_digest=digest(ids),
                text_features_sha256=tensor_digest(x),
                other_features_sha256=tensor_digest(z),
                pretrained_modal_towers_executed_here=False,
                real_modal_receipts_independently_admitted=False,
                frozen=parameters(control), trained=parameters(model),
                training_work=work, physical_optimizer_steps=steps)}
