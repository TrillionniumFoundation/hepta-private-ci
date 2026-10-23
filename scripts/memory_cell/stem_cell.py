"""Research-only persistent heads on the existing immutable Features contract.

No production writer, permissions, evidence authority or model selection lives
here. SGD without momentum makes weights plus counters the complete persistent
learning state; no hidden Adam reset is concealed by an artifact-only reload.
"""

from dataclasses import replace
import hashlib
import json
import math
import re
import time

import torch
from torch import nn

from selector_head import Features

KINDS = ("linear", "prototype", "gated")
MAX_SEEN = 4096
MAX_ROOTS = 16384


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def route_text(text):
    """Observable fixed two-domain route, NOT a discovered semantic topology."""
    pattern = r"\b(when|before|after|first|last|year|month|earlier|later)\b"
    return "temporal" if re.search(pattern, text.lower()) else "general"


def clone_features(batch):
    return replace(
        batch, paired=batch.paired.clone(), frozen_scores=batch.frozen_scores.clone()
    )


class StemHead(nn.Module):
    def __init__(
        self, dimension, encoder_identity, *, kind="gated", rank=16, seed=1837
    ):
        super().__init__()
        if (
            kind not in KINDS
            or type(dimension) is not int
            or not 1 <= dimension <= 1024
            or type(rank) is not int
            or not 1 <= rank <= 32
            or type(seed) is not int
            or not 0 <= seed < 2**31
            or not isinstance(encoder_identity, str)
            or not encoder_identity
        ):
            raise ValueError("bounded head architecture and encoder identity required")
        self.dimension, self.encoder_identity = dimension, encoder_identity
        self.kind, self.rank, self.seed = kind, rank, seed
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            if kind == "prototype":
                self.register_buffer("sums", torch.zeros(2, dimension))
                self.register_buffer("counts", torch.zeros(2))
            else:
                self.readout = nn.Linear(dimension, 1)
                self.null = nn.Linear(dimension, 1)
                if kind == "gated":
                    self.down = nn.Linear(dimension, rank, bias=False)
                    self.up = nn.Linear(rank, dimension, bias=False)
                    self.gate_scale = nn.Parameter(torch.zeros(dimension))
                    self.gate_bias = nn.Parameter(torch.zeros(dimension))
                nn.init.zeros_(self.readout.weight)
                nn.init.zeros_(self.readout.bias)
                nn.init.zeros_(self.null.weight)
                nn.init.zeros_(self.null.bias)
        self.roots, self.seen = set(), set()
        self.steps = self.pair_evaluations = 0
        self.quarantined = False

    def forward(self, batch: Features):
        batch.validate(self.dimension)
        if (
            self.quarantined
            or batch.encoder_identity != self.encoder_identity
            or not batch.pool_digest
            or not batch.encoder_identity
        ):
            raise ValueError("incompatible or unavailable stem head")
        x = batch.paired
        if not len(x):
            return torch.zeros(1)
        if self.kind == "prototype":
            means = self.sums / self.counts.clamp(min=1).unsqueeze(1)
            normalized = torch.nn.functional.normalize(x, dim=-1)
            residual = normalized @ (means[1] - means[0])
            null = torch.zeros(1)
        else:
            if self.kind == "gated":
                gate = torch.sigmoid(self.gate_scale * x + self.gate_bias)
                x = x + gate * self.up(torch.tanh(self.down(x)))
            residual = self.readout(x).flatten()
            null = self.null(batch.paired.mean(0)).reshape(1)
        return torch.cat((batch.frozen_scores + residual, null))

    @torch.no_grad()
    def decide(self, batch, *, revoked, offset=0.0, mode="learned"):
        if (
            self.roots.intersection(revoked)
            or batch.roots.intersection(revoked)
            or not math.isfinite(offset)
            or mode not in ("learned", "frozen", "forced")
        ):
            raise ValueError("withdrawn source or invalid decision policy")
        scores = self(batch)
        if mode in ("frozen", "forced"):
            scores = torch.cat((batch.frozen_scores, torch.zeros(1)))
        scores[-1] += offset
        if not batch.candidate_ids:
            return None, scores.tolist()
        best = min(
            range(len(batch.candidate_ids)),
            key=lambda i: (-float(scores[i]), batch.candidate_ids[i]),
        )
        selected = None if mode != "forced" and scores[-1] >= scores[best] else best
        return selected, scores.tolist()

    def fit(self, rows, cut, *, revoked, steps=192, pair_ceiling=1000000, lr=0.03):
        """Continue this head; validate all rows before any mutation.

        The pair ceiling and cyclic sample cursor survive artifact reload.
        Changing the admitted curriculum is explicit: sort the new row set and
        continue at cumulative_steps modulo its length. Native source-support
        labels are weak supervision, not entailment verdicts.
        """
        if (
            self.quarantined
            or not 1 <= len(rows) <= 256
            or type(steps) is not int
            or not 1 <= steps <= 2048
            or type(pair_ceiling) is not int
            or not 1 <= pair_ceiling <= 10000000
            or not math.isfinite(lr)
            or not 0 < lr <= 0.1
            or not cut.admission_digest
            or self.roots.intersection(revoked | cut.forbidden_roots)
        ):
            raise ValueError("unavailable session or invalid cumulative budget")
        seen, admitted_roots = set(), set(self.roots)
        for row in rows:
            f = row.features
            f.validate(self.dimension)
            if (
                not f.pool_digest
                or f.encoder_identity != self.encoder_identity
                or f.question_id in seen
                or f.question_id not in cut.question_ids
                or f.family not in cut.families
                or not f.roots.issubset(cut.allowed_roots)
                or f.roots.intersection(revoked | cut.forbidden_roots)
                or len(set(row.positive_indices)) != len(row.positive_indices)
                or any(
                    type(i) is not int or not 0 <= i < len(f.candidate_ids)
                    for i in row.positive_indices
                )
            ):
                raise ValueError("unadmitted, duplicated, withdrawn or held-out row")
            seen.add(f.question_id)
            admitted_roots.update(f.roots)
        if len(self.seen | seen) > MAX_SEEN or len(admitted_roots) > MAX_ROOTS:
            raise ValueError("bounded persistent lineage capacity exceeded")
        before = {k: v.clone() for k, v in self.state_dict().items()}
        started, losses, consumed = time.perf_counter(), [], 0
        parameters = list(self.parameters())
        optimizer = torch.optim.SGD(parameters, lr=lr) if parameters else None
        ordered = sorted(
            rows, key=lambda r: (r.features.family, r.features.question_id)
        )
        batches = [ordered[(self.steps + i) % len(ordered)] for i in range(steps)]
        if self.kind == "prototype":
            batches = [r for r in ordered if r.features.question_id not in self.seen]
        no_new_prototypes = self.kind == "prototype" and not batches
        try:
            for row in batches:
                f = row.features
                pairs = len(f.candidate_ids)
                if self.pair_evaluations + pairs > pair_ceiling:
                    break
                self.pair_evaluations += pairs
                if self.kind == "prototype":
                    with torch.no_grad():
                        x = torch.nn.functional.normalize(f.paired, dim=-1)
                        for i in range(pairs):
                            group = int(i in row.positive_indices)
                            self.sums[group] += x[i]
                            self.counts[group] += 1
                elif pairs:
                    optimizer.zero_grad(set_to_none=True)
                    logits = self(f)
                    positive = list(row.positive_indices) or [pairs]
                    loss = torch.logsumexp(logits, 0) - torch.logsumexp(
                        logits[positive], 0
                    )
                    if not torch.isfinite(loss):
                        raise ValueError("nonfinite stem loss")
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(
                        parameters, 1.0, error_if_nonfinite=True
                    )
                    optimizer.step()
                    losses.append(float(loss.detach()))
                self.steps += 1
                consumed += 1
                self.seen.add(f.question_id)
                self.roots.update(f.roots)
                if any(not torch.isfinite(t).all() for t in self.state_dict().values()):
                    raise ValueError("nonfinite persistent state")
            if not consumed and not no_new_prototypes:
                raise ValueError("no admitted update fits remaining budget")
        except Exception:
            self.quarantined = True
            raise
        delta = sum(
            float((value - before[k]).square().sum())
            for k, value in self.state_dict().items()
        )
        return dict(
            kind=self.kind,
            requested_steps=steps,
            consumed_steps=consumed,
            cumulative_steps=self.steps,
            cumulative_pairs=self.pair_evaluations,
            cumulative_unique_examples=len(self.seen),
            pair_ceiling=pair_ceiling,
            sample_cursor=self.steps % len(ordered),
            no_update_reason="no-new-prototype-examples" if no_new_prototypes else None,
            loss_first=None if not losses else losses[0],
            loss_last=None if not losses else losses[-1],
            wall_seconds=time.perf_counter() - started,
            trainable_parameters=sum(p.numel() for p in parameters),
            parameter_bytes=sum(p.numel() * p.element_size() for p in parameters),
            buffer_bytes=sum(b.numel() * b.element_size() for b in self.buffers()),
            gradient_bytes=sum(
                p.grad.numel() * p.grad.element_size()
                for p in parameters
                if p.grad is not None
            ),
            persistent_optimizer_bytes=0,
            optimizer="sufficient-statistics"
            if self.kind == "prototype"
            else "SGD-no-momentum",
            tensor_delta_squared_norm=delta,
            state_changed=delta > 0,
            encoder_updates=0,
            production_accepted=False,
        )

    def export(self):
        if self.quarantined:
            raise ValueError("cannot export quarantined head")
        return json.dumps(
            dict(
                schema="hepta.stem-head.research.v1",
                dimension=self.dimension,
                encoder_identity=self.encoder_identity,
                kind=self.kind,
                rank=self.rank,
                seed=self.seed,
                roots=sorted(self.roots),
                seen=sorted(self.seen),
                steps=self.steps,
                pair_evaluations=self.pair_evaluations,
                state={k: v.detach().tolist() for k, v in self.state_dict().items()},
                production_accepted=False,
            ),
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()

    @classmethod
    def restore(
        cls, payload, *, expected_sha256, encoder_identity, allowed_roots, revoked
    ):
        if len(payload) > 4 * 1024 * 1024 or sha256(payload) != expected_sha256:
            raise ValueError("head artifact byte bound or hash")

        def unique(pairs):
            result = {}
            for k, v in pairs:
                if k in result:
                    raise ValueError("duplicate artifact key")
                result[k] = v
            return result

        obj = json.loads(payload, object_pairs_hook=unique)
        keys = {
            "schema",
            "dimension",
            "encoder_identity",
            "kind",
            "rank",
            "seed",
            "roots",
            "seen",
            "steps",
            "pair_evaluations",
            "state",
            "production_accepted",
        }
        if (
            set(obj) != keys
            or obj["schema"] != "hepta.stem-head.research.v1"
            or obj["production_accepted"] is not False
            or obj["encoder_identity"] != encoder_identity
            or any(
                not isinstance(v, list)
                or len(v) != len(set(v))
                or any(not isinstance(s, str) or not s for s in v)
                for v in (obj["roots"], obj["seen"])
            )
            or len(obj["seen"]) > MAX_SEEN
            or len(obj["roots"]) > MAX_ROOTS
            or not set(obj["roots"]).issubset(allowed_roots)
            or set(obj["roots"]) & revoked
            or any(
                type(obj[k]) is not int or not 0 <= obj[k] <= 10000000
                for k in ("steps", "pair_evaluations")
            )
        ):
            raise ValueError("head artifact identity, lineage or counter mismatch")
        head = cls(
            obj["dimension"],
            encoder_identity,
            kind=obj["kind"],
            rank=obj["rank"],
            seed=obj["seed"],
        )
        expected = head.state_dict()
        if set(obj["state"]) != set(expected):
            raise ValueError("head tensor inventory")
        tensors = {
            k: torch.tensor(v, dtype=torch.float32) for k, v in obj["state"].items()
        }
        if any(
            tensors[k].shape != v.shape or not torch.isfinite(tensors[k]).all()
            for k, v in expected.items()
        ):
            raise ValueError("head tensor layout or values")
        if head.kind == "prototype" and (tensors["counts"] < 0).any():
            raise ValueError("negative prototype counts")
        head.load_state_dict(tensors, strict=True)
        head.roots, head.seen = set(obj["roots"]), set(obj["seen"])
        head.steps, head.pair_evaluations = obj["steps"], obj["pair_evaluations"]
        return head
