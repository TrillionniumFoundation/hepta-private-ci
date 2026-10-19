"""Shadow-only source-family and temporal admission for frozen vector MemoryCell.

Pretrained encoder vectors must be generated outside this module and pinned by
the caller. This does not certify provenance, training rights, or semantic truth.
"""
from dataclasses import dataclass
import json
import math

from associative_cell import AssociativeCell, Experience, ReadQuery, TrainingCut, sha256


@dataclass(frozen=True)
class FrozenCohort:
    train: tuple[Experience, ...]
    future: tuple[Experience, ...]
    cut: TrainingCut


def admit(rows, *, scope, encoder_identity, train_through, future_after,
          admission_digest):
    if (not isinstance(rows, (list, tuple)) or not 2 <= len(rows) <= 2048
            or type(train_through) is not int or type(future_after) is not int
            or not 0 <= train_through < future_after):
        raise ValueError("bounded, chronological training cut required")
    train, future, ids = [], [], set()
    fields = {"split", "identity", "scope", "family", "root", "kind",
              "encoder_identity", "observed_at", "cue", "value"}
    for item in rows:
        if (not isinstance(item, dict) or set(item) != fields
                or item["split"] not in ("train", "future")
                or not isinstance(item["cue"], list)
                or not isinstance(item["value"], list)):
            raise ValueError("invalid frozen-vector record")
        r = Experience(item["identity"], item["scope"], item["family"],
                       item["root"], item["kind"], item["encoder_identity"],
                       item["observed_at"], tuple(item["cue"]), tuple(item["value"]))
        if (not isinstance(r.identity, str) or not r.identity or r.identity in ids
                or not isinstance(r.root, str) or not r.root
                or not isinstance(r.family, str) or not r.family
                or r.scope != scope or r.encoder_identity != encoder_identity
                or r.kind not in ("semantic", "procedural")
                or type(r.observed_at) is not int
                or not 2 <= len(r.cue) == len(r.value) <= 256
                or any(type(x) not in (int, float) or not math.isfinite(x)
                       or abs(x) > 8 for x in (*r.cue, *r.value))):
            raise ValueError("duplicate, incompatible or invalid vector")
        ids.add(r.identity)
        if item["split"] == "train":
            if not 0 <= r.observed_at <= train_through:
                raise ValueError("future or invalid training observation")
            train.append(r)
        else:
            if r.observed_at <= future_after:
                raise ValueError("future observation outside declared window")
            future.append(r)
    if not train or not future or len(train) > 512:
        raise ValueError("both windows required; training cap exceeded")
    train_roots, future_roots = {r.root for r in train}, {r.root for r in future}
    train_families = {r.family for r in train}
    future_families = {r.family for r in future}
    if train_roots & future_roots or train_families & future_families:
        raise ValueError("source-root or correlated-family leakage")
    if ({(r.kind, r.cue, r.value) for r in train}
            & {(r.kind, r.cue, r.value) for r in future}):
        raise ValueError("exact repeated training example")
    cut = TrainingCut(scope, encoder_identity, train_through,
                      frozenset(train_roots), frozenset(train_families),
                      frozenset(future_roots), frozenset(future_families),
                      admission_digest)
    cut.validate()
    return FrozenCohort(tuple(train), tuple(future), cut)


def read_jsonl(raw, **kwargs):
    if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
        raise ValueError("corpus input too large")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    return admit([json.loads(line, object_pairs_hook=unique)
                  for line in raw.splitlines()], **kwargs)


def cosine_neighbor(train, query, *, typed):
    eligible = [r for r in train if not typed or r.kind == query.kind]
    if not eligible:
        raise ValueError("empty typed neighbor control")
    def similarity(row):
        dot = sum(a*b for a, b in zip(row.cue, query.cue, strict=True))
        n1 = math.sqrt(sum(a*a for a in row.cue))
        n2 = math.sqrt(sum(b*b for b in query.cue))
        return dot / (n1 * n2) if n1 and n2 else -1.0
    return max(eligible, key=lambda r: (similarity(r), r.identity)).value


def mse(output, target):
    return sum((a-b)**2 for a, b in zip(output, target, strict=True)) / len(target)


def compare(cohort, *, steps=256):
    """Run matched input vector prediction arms; not a text RAG comparison."""
    if not isinstance(cohort, FrozenCohort):
        raise ValueError("admitted cohort required")
    train, future, cut = cohort.train, cohort.future, cohort.cut
    if ({r.kind for r in train} != {"semantic", "procedural"}
            or {r.kind for r in future} != {"semantic", "procedural"}):
        raise ValueError("both semantic and procedural kinds required")
    dimension = len(train[0].cue)
    if any(len(row.cue) != dimension for row in (*train, *future)):
        raise ValueError("mixed vector dimension")
    parent = AssociativeCell(dimension, 10, cut.encoder_identity, cut.scope, seed=7341)
    trained, receipt = parent.propose_update(train, cut, revoked=set(), steps=steps)
    arms = {a: [] for a in ("frozen", "trained", "cosine_neighbor",
                            "typed_cosine_neighbor")}
    for row in future:
        query = ReadQuery(row.scope, row.kind, row.encoder_identity,
                          row.observed_at, row.cue)
        outputs = {
            "frozen": parent.read(query, revoked=set()),
            "trained": trained.read(query, revoked=set()),
            "cosine_neighbor": cosine_neighbor(train, row, typed=False),
            "typed_cosine_neighbor": cosine_neighbor(train, row, typed=True),
        }
        for name, output in outputs.items():
            arms[name].append(mse(output, row.value))
    return {
        "schema": "hepta.associative-frozen-vector-shadow.v1",
        "train_count": len(train), "future_count": len(future),
        "parameter_count": trained.parameter_count(),
        "candidate_sha256": sha256(trained.export()),
        "mean_squared_error": {k: sum(v)/len(v) for k, v in arms.items()},
        "optimizer_steps": receipt["steps"],
        "pretrained_encoder_verified": False,
        "independent_outcome_verified": False,
        "strong_text_rag_executed": False,
        "reader_executed": False,
        "production_qualified": False,
        "superiority_claim": False,
    }
