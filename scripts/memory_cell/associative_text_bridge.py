"""Research-only, source-bound text -> frozen encoder -> associative parameters.

This is a DEVELOPMENT adapter, not a source owner, model selector, or a reader.
All source facts come from recorded event JSON, never target answer annotations.
Input text remains data; source identifiers and revocations are checked outside
weights. The fixed projection and tokenizer are pinned as part of cell identity.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math

import numpy as np
import torch

from associative_cell import AssociativeCell, Experience, ReadQuery, TrainingCut, sha256

PROFILE = "hepta.associative-source-text.v1"
EVENT_SCHEMA = "hepta.controlled-event.v1"
EVENT_FIELDS = frozenset({
    "schema", "id", "entity", "attribute", "value", "revision", "supersedes",
})
MAX_DOCS = 128
MAX_INPUT_BYTES = 1024 * 1024
PROJECTION_SEED = 2718


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate event field")
        result[name] = value
    return result


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("source observation must have explicit timezone")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("source observation must have explicit timezone")
    result = int(stamp.timestamp())
    if result < 0 or result > 2**63 - 2:
        raise ValueError("source observation out of bounds")
    return result


def _identifier(value):
    return isinstance(value, str) and 0 < len(value.encode()) <= 96 and all(
        c.isascii() and (c.isalnum() or c in "_-") for c in value
    )


@dataclass(frozen=True)
class SourceFact:
    identity: str
    root: str
    scope: str
    observed_at: int
    kind: str
    entity: str
    attribute: str
    value: str
    revision: int

    @property
    def cue(self):
        # This supervised cue is produced only from a source record.
        return (f"In the observed registry at logical revision {self.revision}, "
                f"identify {self.attribute} for {self.entity}.")

    @property
    def target(self):
        return "Recorded identifier: " + self.value


def source_facts(documents, *, logical_revision=2, revoked=frozenset()):
    """Project source-only unambiguous active facts, omitting corrected heads.

    A corrected head requires multiple source ancestors, which the v1 Experience
    single-root field cannot represent. Rather than misattribute training
    lineage, this bridge excludes all heads with supersedes edges. Later versions
    must use a multi-root, versioned artifact contract before learning from them.
    """
    if (
        not isinstance(documents, (tuple, list))
        or not 1 <= len(documents) <= MAX_DOCS
        or type(logical_revision) is not int
        or not 0 <= logical_revision <= 10000
        or not isinstance(revoked, (set, frozenset))
        or len({d.identity for d in documents}) != len(documents)
        or len({d.scope for d in documents}) != 1
        or any(d.root in revoked for d in documents)
    ):
        raise ValueError("unadmitted, duplicate, cross-scope or revoked source set")
    active = {}
    for doc in documents:
        if (
            not _identifier(doc.identity) or not _identifier(doc.root)
            or not _identifier(doc.scope)
            or not isinstance(doc.content, str)
            or not 0 < len(doc.content.encode()) <= 4096
        ):
            raise ValueError("invalid bounded source document")
        observed = _timestamp(doc.observed_at)
        item = json.loads(doc.content, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ValueError("invalid nonfinite source")))
        if (
            not isinstance(item, dict) or set(item) != EVENT_FIELDS
            or item["schema"] != EVENT_SCHEMA or item["id"] != doc.identity
            or not all(_identifier(item[k]) for k in ("entity", "attribute", "value"))
            or type(item["revision"]) is not int
            or not 0 <= item["revision"] <= 10000
            or not isinstance(item["supersedes"], list)
            or len(item["supersedes"]) > 8
            or len(item["supersedes"]) != len(set(item["supersedes"]))
            or not all(_identifier(s) for s in item["supersedes"])
        ):
            raise ValueError("untrusted source event schema")
        if item["revision"] <= logical_revision:
            active[doc.identity] = (doc, observed, item)
    retired = set()
    for _, _, item in active.values():
        retired.update(item["supersedes"])
    if not retired.issubset({d.identity for d in documents}):
        raise ValueError("unknown correction ancestor")
    heads = {}
    for eid, (doc, observed, item) in active.items():
        if eid not in retired:
            heads.setdefault((item["entity"], item["attribute"]), []).append(
                (doc, observed, item)
            )
    facts = []
    omitted = {"corrected_or_multi_root": 0, "conflicting": 0}
    for (entity, attribute), candidates in sorted(heads.items()):
        if len(candidates) != 1:
            omitted["conflicting"] += 1
            continue
        doc, observed, item = candidates[0]
        if item["supersedes"]:
            omitted["corrected_or_multi_root"] += 1
            continue
        facts.append(SourceFact(
            doc.identity, doc.root, doc.scope, observed,
            "procedural" if attribute == "successful_mode" else "semantic",
            entity, attribute, item["value"], item["revision"],
        ))
    return tuple(facts), omitted


class PinnedTextProjection:
    """Frozen real or test encoder; shared deterministic JL projection.

    Encoder implementations must return finite ndarray [batch, input_dim] and
    expose .identity. A real pretrained.Encoder additionally has .tokenizer and
    .truncated_inputs. No call is allowed to truncate or train the base.
    """

    def __init__(self, encoder, *, dimension=64, seed=PROJECTION_SEED):
        if (
            not isinstance(encoder.identity, str) or not encoder.identity
            or type(dimension) is not int or not 2 <= dimension <= 256
            or type(seed) is not int or not 0 <= seed < 2**31
        ):
            raise ValueError("pinned encoder identity and projection required")
        self.encoder = encoder
        self.dimension, self.seed = dimension, seed
        self.identity = None
        self.input_dimension = None
        self._matrix = None
        self.cache = {}
        self.model_calls = 0
        self.encoded_texts = 0

    def encode(self, texts):
        if (
            not isinstance(texts, (tuple, list)) or not 1 <= len(texts) <= 512
            or any(not isinstance(x, str) or not x.strip()
                   or len(x.encode()) > 4096 for x in texts)
        ):
            raise ValueError("bounded nonempty text batch required")
        fresh = tuple(dict.fromkeys(x for x in texts if x not in self.cache))
        if fresh:
            tokenizer = getattr(self.encoder, "tokenizer", None)
            if tokenizer is not None and any(
                len(tokenizer.encode(x, add_special_tokens=True)) > 256
                for x in fresh
            ):
                raise ValueError("text would truncate under pretrained encoder")
            before = getattr(self.encoder, "truncated_inputs", None)
            matrix = np.asarray(self.encoder.encode(list(fresh)), dtype=np.float32)
            if (
                matrix.ndim != 2 or len(matrix) != len(fresh)
                or not 2 <= matrix.shape[1] <= 4096
                or not np.isfinite(matrix).all()
                or (before is not None
                    and getattr(self.encoder, "truncated_inputs", None) != before)
            ):
                raise ValueError("drifted, truncated or nonfinite frozen encoding")
            if self._matrix is None:
                self.input_dimension = matrix.shape[1]
                generator = torch.Generator(device="cpu").manual_seed(self.seed)
                projection = torch.randn(
                    self.input_dimension, self.dimension, generator=generator,
                ) / math.sqrt(self.input_dimension)
                self._matrix = projection.detach().numpy()
                pdigest = hashlib.sha256(self._matrix.tobytes()).hexdigest()
                self.identity = (
                    f"{self.encoder.identity}:proj:{self.dimension}:{self.seed}:"
                    f"{pdigest[:16]}"
                )
                if len(self.identity.encode()) > 256:
                    raise ValueError("projected encoder identity too long")
            if matrix.shape[1] != self.input_dimension:
                raise ValueError("frozen encoder width changed")
            values = matrix @ self._matrix
            norms = np.linalg.norm(values, axis=1, keepdims=True)
            if not np.isfinite(norms).all() or (norms < 1e-8).any():
                raise ValueError("zero-norm projected value")
            values = values / norms
            for text, row in zip(fresh, values, strict=True):
                self.cache[text] = tuple(float(v) for v in row)
            self.model_calls += 1
            self.encoded_texts += len(fresh)
        return tuple(self.cache[x] for x in texts)


def prepare_experiences(facts, projector, *, scope):
    if not facts or any(f.scope != scope for f in facts):
        raise ValueError("nonempty admitted single-scope facts required")
    cues = projector.encode([f.cue for f in facts])
    values = projector.encode([f.target for f in facts])
    return tuple(Experience(
        identity=f.identity, scope=f.scope, family=f.scope + ":" + f.identity,
        root=f.root, kind=f.kind, encoder_identity=projector.identity,
        observed_at=f.observed_at, cue=cues[i], value=values[i],
    ) for i, f in enumerate(facts))


def train_scope(experiences, documents, projector, *, steps=128, rank=4, lr=0.25):
    if (
        not experiences or not documents
        or {row.scope for row in experiences} != {d.scope for d in documents}
        or any(row.encoder_identity != projector.identity for row in experiences)
        or len(experiences) > 128
        or type(steps) is not int or not 1 <= steps <= 512
    ):
        raise ValueError("unbound or overbudget scope training")
    scope = experiences[0].scope
    through = max(_timestamp(d.observed_at) for d in documents)
    cut = TrainingCut(
        scope, projector.identity, through,
        frozenset(d.root for d in documents),
        frozenset(row.family for row in experiences),
        frozenset(), frozenset(),
        sha256(json.dumps({
            "profile": PROFILE, "roots": sorted(d.root for d in documents),
            "scope": scope, "through": through,
        }, sort_keys=True, separators=(",", ":")).encode()),
    )
    parent = AssociativeCell(projector.dimension, rank, projector.identity,
                             scope, kind="mixed", seed=313)
    candidate, receipt = parent.propose_update(
        experiences, cut, revoked=set(), steps=steps, lr=lr,
    )
    # Enumerating which head is unambiguous depends on the entire scope view,
    # including competing, retired and future-revision source records. Conservatively
    # bind ALL inspected source roots before publishing the candidate artifact.
    # This is a shadow research lineage extension, not an owner-issued proof.
    candidate.roots.update(d.root for d in documents)
    receipt = dict(receipt)
    receipt.update(
        candidate=sha256(candidate.export()),
        source_roots=len(candidate.roots),
        complete_inspected_scope_roots_bound=True,
    )
    return candidate, receipt


def direct_read(cell, projector, query_text, *, kind, as_of, revoked):
    if kind not in ("semantic", "procedural") or not isinstance(query_text, str):
        raise ValueError("bounded observable query kind/text required")
    cue = projector.encode([query_text])[0]
    query = ReadQuery(cell.scope, kind, projector.identity, as_of, cue)
    return cell.read(query, revoked=revoked)


def cosine(a, b):
    x, y = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    if x.shape != y.shape or x.ndim != 1 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("incompatible finite representations")
    na, nb = float(np.linalg.norm(x)), float(np.linalg.norm(y))
    return float(np.dot(x, y) / (na * nb)) if na > 1e-12 and nb > 1e-12 else None
