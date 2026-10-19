"""Research-only parameter associative memory on an immutable encoder output.

This is deliberately *not* a memory store, runtime model installer or evidence
source. The caller admits a source-only cue/value training cut; a clean process
may subsequently read only the exported small cell weights and lineage. It
cannot establish source authenticity, semantic correctness or production safety.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import math

import torch
from torch import nn

SCHEMA = "hepta.associative-memory-cell.research.v1"
KINDS = ("semantic", "procedural")
MAX_SAMPLES = 512
MAX_ROOTS = 4096
MAX_SEEN = 8192
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError("duplicate artifact key")
        obj[k] = v
    return obj


def _vector(values, dimension):
    if (
        not isinstance(values, tuple)
        or len(values) != dimension
        or any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 8 for v in values)
    ):
        raise ValueError("finite bounded frozen-encoder vector required")
    return torch.tensor(values, dtype=torch.float32)


def _id(value):
    return isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 256


@dataclass(frozen=True)
class Experience:
    identity: str
    scope: str
    family: str
    root: str
    kind: str
    encoder_identity: str
    observed_at: int
    cue: tuple[float, ...]
    value: tuple[float, ...]


@dataclass(frozen=True)
class ReadQuery:
    scope: str
    kind: str
    encoder_identity: str
    as_of: int
    cue: tuple[float, ...]


@dataclass(frozen=True)
class TrainingCut:
    scope: str
    encoder_identity: str
    through: int
    allowed_roots: frozenset[str]
    allowed_families: frozenset[str]
    forbidden_roots: frozenset[str]
    forbidden_families: frozenset[str]
    admission_digest: str

    def validate(self):
        if (
            not _id(self.scope)
            or not _id(self.encoder_identity)
            or not _id(self.admission_digest)
            or type(self.through) is not int
            or self.through < 0
            or any(type(v) is not frozenset for v in (
                self.allowed_roots, self.allowed_families,
                self.forbidden_roots, self.forbidden_families,
            ))
            or not self.allowed_roots
            or not self.allowed_families
            or any(not _id(x) for values in (
                self.allowed_roots, self.allowed_families,
                self.forbidden_roots, self.forbidden_families,
            ) for x in values)
            or self.allowed_roots & self.forbidden_roots
            or self.allowed_families & self.forbidden_families
        ):
            raise ValueError("invalid, overlapping or unpinned training cut")


class AssociativeCell(nn.Module):
    """Local, low-rank cue->value function; SGD state is only persistent weights.

    No raw source examples, cached values or task answers are included in export.
    New weights are proposals; the selected parent instance remains unchanged.
    """

    def __init__(self, dimension, rank, encoder_identity, scope, kind="mixed", seed=17):
        super().__init__()
        if (
            type(dimension) is not int or not 2 <= dimension <= 256
            or type(rank) is not int or not 1 <= rank <= 32
            or kind not in (*KINDS, "mixed")
            or not _id(encoder_identity) or not _id(scope)
            or type(seed) is not int or not 0 <= seed < 2**31
        ):
            raise ValueError("invalid associative cell architecture or identity")
        self.dimension, self.rank = dimension, rank
        self.encoder_identity, self.scope, self.kind, self.seed = (
            encoder_identity, scope, kind, seed
        )
        gen = torch.Generator(device="cpu").manual_seed(seed)
        self.down = nn.Parameter(torch.randn(rank, dimension, generator=gen) * 0.15)
        self.up = nn.Parameter(torch.randn(dimension, rank, generator=gen) * 0.15)
        self.roots = set()
        self.seen = set()
        self.steps = self.generation = self.latest_observed = 0
        self.predecessor = None
        self.split_from = None

    def forward(self, cues):
        return torch.tanh(torch.nn.functional.linear(cues, self.down)) @ self.up.T

    def parameter_count(self):
        return sum(p.numel() for p in self.parameters())

    def _check_query(self, query, revoked, *, allow_wrong_kind=False):
        if (
            not isinstance(query, ReadQuery)
            or not isinstance(revoked, (set, frozenset))
            or not _id(query.scope)
            or query.scope != self.scope
            or query.encoder_identity != self.encoder_identity
            or query.kind not in KINDS
            or (not allow_wrong_kind and self.kind not in ("mixed", query.kind))
            or type(query.as_of) is not int
            or query.as_of < self.latest_observed
            or self.roots & revoked
        ):
            raise ValueError("stale, revoked, wrong-kind or incompatible memory read")
        return _vector(query.cue, self.dimension)

    @torch.no_grad()
    def read(self, query, *, revoked):
        cue = self._check_query(query, revoked)
        return tuple(float(v) for v in self(cue).tolist())

    def _copy(self):
        copy = type(self)(
            self.dimension, self.rank, self.encoder_identity,
            self.scope, self.kind, seed=self.seed,
        )
        copy.load_state_dict({k: v.detach().clone() for k, v in self.state_dict().items()})
        copy.roots, copy.seen = set(self.roots), set(self.seen)
        copy.steps, copy.generation = self.steps, self.generation
        copy.latest_observed = self.latest_observed
        copy.predecessor, copy.split_from = self.predecessor, self.split_from
        return copy

    def propose_update(self, rows, cut, *, revoked, steps=256, lr=0.15):
        """Prevalidate complete source cut and train a separate candidate.

        A no-momentum SGD optimizer leaves no undeclared persistent momentum.
        Row source IDs are metadata, not authenticated permissions or evidence.
        """
        if torch.is_inference_mode_enabled():
            raise ValueError("inference-mode training forbidden")
        if (
            not isinstance(cut, TrainingCut) or not isinstance(revoked, (set, frozenset))
            or not isinstance(rows, (tuple, list))
            or not 1 <= len(rows) <= MAX_SAMPLES
            or type(steps) is not int or not 1 <= steps <= 2048
            or self.steps + steps > 1000000
            or type(lr) not in (float, int) or not math.isfinite(lr) or not 0 < lr <= 0.5
        ):
            raise ValueError("invalid training budget or source session")
        cut.validate()
        if (
            cut.scope != self.scope or cut.encoder_identity != self.encoder_identity
            or self.roots & (revoked | cut.forbidden_roots)
            or len(self.roots) > MAX_ROOTS
        ):
            raise ValueError("parent lineage, cut or revocation mismatch")
        distinct = set()
        validated = []
        for row in rows:
            if (
                not isinstance(row, Experience)
                or not all(_id(v) for v in (
                    row.identity, row.scope, row.family, row.root, row.encoder_identity
                ))
                or row.identity in distinct
                or row.scope != self.scope
                or row.encoder_identity != self.encoder_identity
                or row.kind not in KINDS
                or self.kind not in ("mixed", row.kind)
                or type(row.observed_at) is not int
                or not 0 <= row.observed_at <= cut.through
                or row.root not in cut.allowed_roots
                or row.root in revoked
                or row.family not in cut.allowed_families
            ):
                raise ValueError("unadmitted, future, duplicate or wrong-kind source")
            distinct.add(row.identity)
            validated.append((row, _vector(row.cue, self.dimension),
                              _vector(row.value, self.dimension)))
        if (
            len(self.roots | {row.root for row, _, _ in validated}) > MAX_ROOTS
            or len(self.seen | {sha256(row.identity.encode()) for row, _, _ in validated}) > MAX_SEEN
        ):
            raise ValueError("memory lineage capacity exceeded")
        candidate = self._copy()
        candidate.predecessor = sha256(self.export())
        ordered = sorted(validated, key=lambda r: r[0].identity)
        before = {k: v.detach().clone() for k, v in candidate.state_dict().items()}
        optimizer = torch.optim.SGD(candidate.parameters(), lr=float(lr), momentum=0)
        losses = []
        with torch.enable_grad():
            for index in range(steps):
                row, cue, value = ordered[(self.steps + index) % len(ordered)]
                optimizer.zero_grad(set_to_none=True)
                loss = torch.mean((candidate(cue) - value) ** 2)
                if not bool(torch.isfinite(loss)):
                    raise ValueError("nonfinite associative training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(candidate.parameters(), 4.0,
                                               error_if_nonfinite=True)
                optimizer.step()
                losses.append(float(loss.detach()))
        if any(not bool(torch.isfinite(p).all()) for p in candidate.parameters()):
            raise ValueError("nonfinite proposed parameters")
        candidate.roots |= {row.root for row, _, _ in ordered}
        candidate.seen |= {sha256(row.identity.encode()) for row, _, _ in ordered}
        candidate.steps += steps
        candidate.generation += 1
        candidate.latest_observed = max(
            [self.latest_observed, *(row.observed_at for row, _, _ in ordered)]
        )
        delta = sum(float((candidate.state_dict()[k] - old).square().sum())
                    for k, old in before.items())
        receipt = dict(
            schema="hepta.associative-cell-proposal-receipt.v1",
            predecessor=candidate.predecessor,
            candidate=sha256(candidate.export()),
            kind=candidate.kind,
            train_examples=len(ordered),
            steps=steps,
            cumulative_steps=candidate.steps,
            trainable_parameters=candidate.parameter_count(),
            parameter_bytes=4 * candidate.parameter_count(),
            persistent_optimizer_bytes=0,
            loss_first=losses[0], loss_last=losses[-1],
            tensor_delta_squared_norm=delta,
            source_roots=len(candidate.roots),
            source_admission_self_attested=True,
            no_raw_examples_in_artifact=True,
            production_accepted=False,
            superiority_claim=False,
        )
        return candidate, receipt

    def export(self):
        state = {k: v.detach().cpu().tolist() for k, v in sorted(self.state_dict().items())}
        manifest = dict(
            schema=SCHEMA, dimension=self.dimension, rank=self.rank,
            encoder_identity=self.encoder_identity, scope=self.scope,
            kind=self.kind, seed=self.seed,
            roots=sorted(self.roots), seen=sorted(self.seen),
            steps=self.steps, generation=self.generation,
            latest_observed=self.latest_observed,
            predecessor=self.predecessor, split_from=self.split_from,
            state=state,
            source_admission_self_attested=True,
            production_accepted=False,
        )
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValueError("memory artifact capacity exceeded")
        return raw

    @classmethod
    def restore(cls, raw, *, expected_sha256, encoder_identity, scope,
                allowed_roots, revoked):
        if (
            not isinstance(raw, bytes)
            or len(raw) > MAX_ARTIFACT_BYTES
            or sha256(raw) != expected_sha256
            or not isinstance(allowed_roots, (set, frozenset))
            or not isinstance(revoked, (set, frozenset))
        ):
            raise ValueError("memory artifact size, bytes or hash mismatch")
        obj = json.loads(raw, object_pairs_hook=_unique)
        expected_keys = {
            "schema", "dimension", "rank", "encoder_identity", "scope", "kind",
            "seed", "roots", "seen", "steps", "generation", "latest_observed",
            "predecessor", "split_from", "state", "source_admission_self_attested",
            "production_accepted",
        }
        if (
            not isinstance(obj, dict) or set(obj) != expected_keys
            or obj["schema"] != SCHEMA
            or obj["production_accepted"] is not False
            or obj["source_admission_self_attested"] is not True
            or obj["scope"] != scope or obj["encoder_identity"] != encoder_identity
            or any(type(obj[k]) is not int or not 0 <= obj[k] <= 1000000
                   for k in ("steps", "generation"))
            or type(obj["latest_observed"]) is not int
            or not 0 <= obj["latest_observed"] <= 2**63 - 1
            or any(v is not None and (not isinstance(v, str) or len(v) != 64)
                   for v in (obj["predecessor"], obj["split_from"]))
            or any(not isinstance(v, list) or v != sorted(set(v))
                   or any(not _id(s) for s in v)
                   for v in (obj["roots"], obj["seen"]))
            or len(obj["roots"]) > MAX_ROOTS
            or len(obj["seen"]) > MAX_SEEN
            or not set(obj["roots"]) <= allowed_roots
            or bool(set(obj["roots"]) & revoked)
            or any(not isinstance(d, str) or len(d) != 64 for d in obj["seen"])
            or not isinstance(obj["state"], dict)
        ):
            raise ValueError("memory artifact identity, lineage or policy mismatch")
        cell = cls(obj["dimension"], obj["rank"], obj["encoder_identity"],
                   obj["scope"], obj["kind"], obj["seed"])
        expected = cell.state_dict()
        if set(obj["state"]) != set(expected):
            raise ValueError("memory artifact tensor inventory mismatch")
        try:
            tensors = {k: torch.tensor(v, dtype=torch.float32)
                       for k, v in obj["state"].items()}
        except (ValueError, TypeError, RuntimeError) as exc:
            raise ValueError("invalid memory artifact tensor") from exc
        if any(tensors[k].shape != val.shape or not bool(torch.isfinite(tensors[k]).all())
               for k, val in expected.items()):
            raise ValueError("memory artifact tensor shape or finite bound")
        cell.load_state_dict(tensors, strict=True)
        cell.roots, cell.seen = set(obj["roots"]), set(obj["seen"])
        cell.steps, cell.generation = obj["steps"], obj["generation"]
        cell.latest_observed = obj["latest_observed"]
        cell.predecessor, cell.split_from = obj["predecessor"], obj["split_from"]
        return cell


def propose_split(parent):
    """Equal total parameter partition, not yet an accepted behavioral split.

    The *sum* of initial child functions equals the parent function. Routing to
    one child need not be equivalent; acceptance requires independent evaluation.
    Both children conservatively inherit all parent training-root dependencies.
    """
    if not isinstance(parent, AssociativeCell) or parent.kind != "mixed" \
            or parent.rank % 2 or parent.rank < 2:
        raise ValueError("split needs a mixed, even-rank parent")
    rank = parent.rank // 2
    children = []
    parent_digest = sha256(parent.export())
    for idx, kind in enumerate(KINDS):
        child = AssociativeCell(parent.dimension, rank,
                                parent.encoder_identity, parent.scope, kind, parent.seed)
        with torch.no_grad():
            child.down.copy_(parent.down[idx * rank:(idx + 1) * rank])
            child.up.copy_(parent.up[:, idx * rank:(idx + 1) * rank])
        child.roots, child.seen = set(parent.roots), set(parent.seen)
        child.latest_observed, child.steps = parent.latest_observed, parent.steps
        child.generation, child.split_from = parent.generation + 1, parent_digest
        child.predecessor = parent_digest
        children.append(child)
    if sum(c.parameter_count() for c in children) != parent.parameter_count():
        raise ValueError("unexpected split parameter inflation")
    return tuple(children)


class ExperimentalBank:
    """Two-type research routing only. Swapped routing is an explicit ablation."""

    def __init__(self, children):
        if (
            len(children) != 2
            or {c.kind for c in children} != set(KINDS)
            or len({(c.scope, c.encoder_identity, c.dimension) for c in children}) != 1
            or len({c.split_from for c in children}) != 1
            or None in {c.split_from for c in children}
        ):
            raise ValueError("incompatible memory bank or missing split lineage")
        self.children = {c.kind: c for c in children}

    @torch.no_grad()
    def read(self, query, *, revoked, ablation="correct"):
        if ablation not in ("correct", "swapped") or not isinstance(query, ReadQuery):
            raise ValueError("unregistered experimental router ablation")
        desired = query.kind
        if desired not in KINDS:
            raise ValueError("unregistered query kind")
        chosen = desired if ablation == "correct" else next(k for k in KINDS if k != desired)
        cell = self.children[chosen]
        cue = cell._check_query(query, revoked, allow_wrong_kind=(ablation == "swapped"))
        return tuple(float(v) for v in cell(cue).tolist())
