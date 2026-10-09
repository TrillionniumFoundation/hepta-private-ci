"""Small residual evidence head over a shared frozen *paired* encoder.

Labels are source-support supervision, not semantic citation certificates.
No encoder, benchmark targets, optimizer or source text is serialized as state.
"""

from dataclasses import dataclass
import json
import math
import time

import torch
from torch import nn

from native import digest


@dataclass(frozen=True)
class Features:
    question_id: str
    family: str
    encoder_identity: str
    pool_digest: str
    candidate_ids: tuple[str, ...]
    roots: frozenset[str]
    paired: torch.Tensor
    frozen_scores: torch.Tensor

    def validate(self, dimension):
        n = len(self.candidate_ids)
        if (not self.question_id or not self.family or len(set(self.candidate_ids)) != n
                or not 0 <= n <= 64 or self.paired.shape != (n, dimension)
                or self.frozen_scores.shape != (n,)
                or any(t.requires_grad or t.dtype != torch.float32 or t.device.type != "cpu"
                       or not torch.isfinite(t).all() for t in (self.paired, self.frozen_scores))):
            raise ValueError("invalid frozen feature batch")

    def seal(self):
        return digest((self.question_id, self.family, self.encoder_identity,
                       self.pool_digest, self.candidate_ids, sorted(self.roots),
                       self.paired.tolist(), self.frozen_scores.tolist()))


@dataclass(frozen=True)
class Supervision:
    features: Features
    positive_indices: tuple[int, ...]
    negative_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrainingCut:
    question_ids: frozenset[str]
    families: frozenset[str]
    allowed_roots: frozenset[str]
    forbidden_roots: frozenset[str]
    admission_digest: str


class EvidenceHead(nn.Module):
    def __init__(self, dimension, encoder_identity, *, hidden=16):
        super().__init__()
        if (type(dimension) is not int or not 1 <= dimension <= 1024
                or type(hidden) is not int or not 1 <= hidden <= 32
                or not isinstance(encoder_identity, str) or not encoder_identity):
            raise ValueError("head resource/encoder identity")
        self.dimension, self.hidden = dimension, hidden
        self.encoder_identity = encoder_identity
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(1837)
            self.projection = nn.Linear(dimension, hidden)
            self.residual = nn.Linear(hidden, 1)
            self.null = nn.Linear(dimension, 1)
        nn.init.zeros_(self.residual.weight)
        nn.init.zeros_(self.residual.bias)
        nn.init.zeros_(self.null.weight)
        nn.init.zeros_(self.null.bias)
        self.roots, self.training_receipt = frozenset(), None
        self.quarantined = False

    def forward(self, batch: Features):
        batch.validate(self.dimension)
        if self.quarantined or batch.encoder_identity != self.encoder_identity:
            raise ValueError("unavailable head or incompatible encoder")
        if not batch.candidate_ids:
            return self.null.bias * 0  # Only no-evidence abstention is possible.
        x = batch.paired
        scores = batch.frozen_scores + self.residual(torch.tanh(self.projection(x))).flatten()
        return torch.cat((scores, self.null(x.mean(0)).reshape(1)))

    @torch.no_grad()
    def decide(self, batch: Features, *, revoked: set[str], offset=0.0, mode="learned"):
        if self.roots.intersection(revoked) or batch.roots.intersection(revoked):
            raise ValueError("withdrawn feature or training root")
        if not math.isfinite(offset) or mode not in ("learned", "frozen", "forced"):
            raise ValueError("registered finite decision policy required")
        logits = self(batch)
        if mode in ("frozen", "forced"):
            logits = torch.cat((batch.frozen_scores, torch.zeros(1)))
        logits[-1] += offset
        n = len(batch.candidate_ids)
        if not n:
            return None, logits.tolist()
        # Stable source identity tie-break, independent of batch order.
        i = min(range(n), key=lambda j: (-float(logits[j]), batch.candidate_ids[j]))
        return (None if mode != "forced" and logits[-1] >= logits[i] else i), logits.tolist()

    def fit(self, rows: tuple[Supervision, ...], cut: TrainingCut, *, revoked: set[str], steps=192):
        if not 1 <= len(rows) <= 256 or not 1 <= steps <= 1024 or not cut.admission_digest:
            raise ValueError("bounded admitted training required")
        groups, seen = {}, set()
        for row in rows:  # Validate ALL rows before an optimizer can mutate state.
            f = row.features
            f.validate(self.dimension)
            if (f.encoder_identity != self.encoder_identity or f.question_id in seen
                    or f.question_id not in cut.question_ids or f.family not in cut.families
                    or not f.roots.issubset(cut.allowed_roots)
                    or f.roots.intersection(cut.forbidden_roots | revoked)):
                raise ValueError("non-admitted, held-out, duplicate or withdrawn training data")
            seen.add(f.question_id)
            if (len(set(row.positive_indices)) != len(row.positive_indices)
                    or any(type(i) is not int or not 0 <= i < len(f.candidate_ids)
                           for i in row.positive_indices)):
                raise ValueError("invalid support indices")
            groups.setdefault(f.family, []).append(row)
        families = sorted(groups)
        for group in groups.values():
            group.sort(key=lambda r: r.features.question_id)
        if self.quarantined or self.roots.intersection(revoked | cut.forbidden_roots):
            raise ValueError("unavailable training head")
        before = {k: v.clone() for k, v in self.state_dict().items()}
        optimizer = torch.optim.AdamW(self.parameters(), lr=0.001, weight_decay=0.01)
        losses, pairs, started = [], 0, time.perf_counter()
        try:
            for step in range(steps):
                group = groups[families[step % len(families)]]
                row = group[(step // len(families)) % len(group)]
                scores = self(row.features)
                positive = list(row.positive_indices) or [len(scores) - 1]
                # Marginal source-support loss: multiple annotated sources allowed.
                loss = torch.logsumexp(scores, 0) - torch.logsumexp(scores[positive], 0)
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite listwise loss")
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.parameters(), 1.0, error_if_nonfinite=True)
                optimizer.step()
                if any(not torch.isfinite(p).all() for p in self.parameters()):
                    raise ValueError("nonfinite updated head")
                losses.append(float(loss.detach()))
                pairs += len(scores) - 1
            self.roots = self.roots.union(*(r.features.roots for r in rows))
            delta = sum(float((v - before[k]).square().sum()) for k, v in self.state_dict().items())
            self.training_receipt = dict(
                objective="family-balanced-marginal-source-support-plus-null-v1",
                admission_digest=cut.admission_digest,
                data_digest=digest([(r.features.seal(), r.positive_indices, r.negative_kinds) for r in rows]),
                rows=len(rows), families=families, steps=steps, pair_evaluations=pairs,
                trainable_parameters=sum(p.numel() for p in self.parameters()),
                delta_squared_norm=delta, losses=losses, seconds=time.perf_counter() - started,
                encoder_updates=0, training_roots=sorted(self.roots), production_accepted=False)
            return self.training_receipt
        except Exception:
            self.quarantined = True
            raise

    def export(self):
        if self.quarantined or self.training_receipt is None:
            raise ValueError("no valid trained head")
        return json.dumps(dict(schema="hepta.evidence-head.v1", dimension=self.dimension,
            hidden=self.hidden, encoder_identity=self.encoder_identity, roots=sorted(self.roots),
            state={k: v.tolist() for k, v in self.state_dict().items()}, training=self.training_receipt,
            production_accepted=False), sort_keys=True, allow_nan=False).encode()

    @classmethod
    def restore(cls, payload: bytes, *, expected_digest: str, encoder_identity: str,
                allowed_roots: set[str], revoked: set[str]):
        if len(payload) > 2 * 1024 * 1024 or digest(payload.hex()) != expected_digest:
            raise ValueError("head artifact digest/bound")
        def unique(pairs):
            out = {}
            for k, v in pairs:
                if k in out:
                    raise ValueError("duplicate artifact key")
                out[k] = v
            return out
        obj = json.loads(payload, object_pairs_hook=unique)
        if (set(obj) != {"schema", "dimension", "hidden", "encoder_identity", "roots", "state", "training", "production_accepted"}
                or obj["schema"] != "hepta.evidence-head.v1" or obj["production_accepted"] is not False
                or obj["encoder_identity"] != encoder_identity or len(set(obj["roots"])) != len(obj["roots"])
                or not set(obj["roots"]).issubset(allowed_roots) or set(obj["roots"]) & revoked):
            raise ValueError("head compatibility/lineage")
        model = cls(obj["dimension"], encoder_identity, hidden=obj["hidden"])
        expected = model.state_dict()
        if set(expected) != set(obj["state"]):
            raise ValueError("head tensor inventory")
        state = {k: torch.tensor(v, dtype=torch.float32) for k, v in obj["state"].items()}
        if any(state[k].shape != v.shape or not torch.isfinite(state[k]).all() for k, v in expected.items()):
            raise ValueError("head tensor shape/value")
        model.load_state_dict(state, strict=True)
        model.roots, model.training_receipt = frozenset(obj["roots"]), obj["training"]
        return model
