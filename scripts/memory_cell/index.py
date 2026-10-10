"""Persistent scope-isolated FTS5 + cached dense retrieval, with explicit cuts.

One index per source scope. No per-query rebuild, hidden remote embedder or
mutable owner writes. Revoking any indexed support invalidates this projection.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from native import Document, Question, digest
from sessions import source_id


@dataclass(frozen=True)
class RetrievalPolicy:
    top_k: int = 8
    channel_k: int = 64
    lexical_weight: float = 0.5
    rrf_constant: int = 60

    def validate(self):
        if (
            not 1 <= self.top_k <= self.channel_k <= 512
            or not 0 <= self.lexical_weight <= 1
            or not 1 <= self.rrf_constant <= 1000
        ):
            raise ValueError("invalid retrieval policy")


MAX_VECTOR_BYTES = 512 * 1024 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024 * 1024


def index_digest(path: Path) -> str:
    """Physical projection identity, including the FTS shadow tables."""
    if not 1 <= path.stat().st_size <= MAX_INDEX_BYTES:
        raise ValueError("index file byte limit")
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class PersistentIndex:
    def __init__(
        self,
        path: Path,
        expected_cut: str,
        revoked: set[str],
        *,
        expected_file_digest: str,
        expected_encoder: str,
    ):
        # Caller binds these values from its immutable projection manifest, not
        # from a possibly corrupted index's own metadata. Path is owner-protected.
        if not expected_encoder or index_digest(path) != expected_file_digest:
            raise ValueError("index artifact/encoder binding mismatch")
        self.file_digest = expected_file_digest
        self.path = path
        self.db = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
        try:
            self.db.execute("PRAGMA query_only=ON")
            self.meta = json.loads(
                self.db.execute("SELECT value FROM meta").fetchone()[0]
            )
            if (
                self.meta["cut"] != expected_cut
                or self.meta["schema"] != "hepta.memory-index.v2"
                or self.meta["encoder"] != expected_encoder
            ):
                raise ValueError("index cut/schema mismatch")
            count = self.db.execute("SELECT count(*) FROM docs").fetchone()[0]
            shape = self.meta.get("shape")
            if (
                not isinstance(shape, list)
                or len(shape) != 2
                or any(type(n) is not int for n in shape)
                or not 1 <= count == shape[0] <= 250_000
                or not 1 <= shape[1] <= 4096
                or shape[0] * shape[1] * 4 > MAX_VECTOR_BYTES
            ):
                raise ValueError("index dimensions exceed resource profile")
            if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("index database integrity")
            records = self.db.execute(
                "SELECT record, vector FROM docs ORDER BY rowid"
            ).fetchall()
            decoded = [json.loads(row[0]) for row in records]
            self.documents = tuple(
                Document(**(d | {"assets": tuple(d["assets"])})) for d in decoded
            )
            if (
                not records
                or digest([asdict(d) for d in self.documents])
                != self.meta["source_digest"]
            ):
                raise ValueError("index source projection corruption")
            lexical = self.db.execute(
                "SELECT rowid, content FROM lexical ORDER BY rowid"
            ).fetchall()
            if lexical != [(i, d.content) for i, d in enumerate(self.documents, 1)]:
                raise ValueError("lexical projection does not match source records")
            if len({d.identity for d in self.documents}) != count or {
                d.scope for d in self.documents
            } != {self.meta["scope"]}:
                raise ValueError("index identity/scope mismatch")
            self.vectors = np.stack(
                [np.frombuffer(row[1], dtype="<f4") for row in records]
            )
            if (
                list(self.vectors.shape) != self.meta["shape"]
                or not np.isfinite(self.vectors).all()
                or digest(self.vectors.tobytes().hex()) != self.meta["vector_digest"]
            ):
                raise ValueError("index vector corruption")
            self.roots = {d.root for d in self.documents}
            self.revalidate(expected_cut, revoked)
        except BaseException:
            self.db.close()
            raise

    @staticmethod
    def build(
        path: Path,
        documents: tuple[Document, ...],
        vectors: np.ndarray,
        encoder: str,
        cut: str,
    ):
        if (
            not documents
            or len(documents) > 250_000
            or len({d.scope for d in documents}) != 1
            or len({d.identity for d in documents}) != len(documents)
        ):
            raise ValueError("index count/scope mismatch")
        vectors = np.asarray(vectors, dtype="<f4")
        if (
            vectors.ndim != 2
            or vectors.shape[0] != len(documents)
            or not 1 <= vectors.shape[1] <= 4096
            or not np.isfinite(vectors).all()
            or vectors.nbytes > MAX_VECTOR_BYTES
        ):
            raise ValueError("index embedding shape/value")
        vectors = vectors / np.maximum(
            np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12
        )
        with path.open("xb"):
            pass
        db = sqlite3.connect(path)
        try:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE meta(value TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE docs(rowid INTEGER PRIMARY KEY, record TEXT NOT NULL, vector BLOB NOT NULL)"
            )
            db.execute(
                "CREATE VIRTUAL TABLE lexical USING fts5(content, tokenize='unicode61')"
            )
            for i, (doc, vector) in enumerate(zip(documents, vectors, strict=True), 1):
                db.execute(
                    "INSERT INTO docs VALUES(?,?,?)",
                    (i, json.dumps(asdict(doc), sort_keys=True), vector.tobytes()),
                )
                db.execute(
                    "INSERT INTO lexical(rowid,content) VALUES(?,?)", (i, doc.content)
                )
            meta = {
                "schema": "hepta.memory-index.v2",
                "scope": documents[0].scope,
                "cut": cut,
                "encoder": encoder,
                "shape": list(vectors.shape),
                "source_digest": digest([asdict(d) for d in documents]),
                "vector_digest": digest(vectors.tobytes().hex()),
            }
            db.execute(
                "INSERT INTO meta VALUES(?)", (json.dumps(meta, sort_keys=True),)
            )
            db.commit()
        finally:
            db.close()
        return index_digest(path)

    def revalidate(self, cut: str, revoked: set[str]):
        if cut != self.meta["cut"] or self.roots.intersection(revoked):
            raise ValueError("stale or revoked index; owner rebuild required")

    def query(
        self,
        query: Question,
        vector: np.ndarray,
        policy: RetrievalPolicy,
        *,
        current_cut: str,
        revoked: set[str],
    ):
        start = time.perf_counter_ns()
        policy.validate()
        self.revalidate(current_cut, revoked)
        if query.scope != self.meta["scope"]:
            raise ValueError("cross-scope retrieval")
        x = np.asarray(vector, dtype=np.float32)
        if x.shape != self.vectors.shape[1:] or not np.isfinite(x).all():
            raise ValueError("query embedding incompatible")
        terms = list(dict.fromkeys(re.findall(r"\w+", query.content.lower())))[:128]
        lexical = []
        if terms:
            expression = " OR ".join(
                '"' + word.replace('"', '""') + '"' for word in terms
            )
            lexical = [
                row[0] - 1
                for row in self.db.execute(
                    "SELECT rowid FROM lexical WHERE lexical MATCH ? ORDER BY bm25(lexical), rowid LIMIT ?",
                    (expression, policy.channel_k),
                )
            ]
        similarities = self.vectors @ (x / max(float(np.linalg.norm(x)), 1e-12))
        dense = np.argsort(-similarities, kind="stable")[: policy.channel_k].tolist()
        scores = {}
        for channel, weight in (
            (lexical, policy.lexical_weight),
            (dense, 1 - policy.lexical_weight),
        ):
            for rank, i in enumerate(channel):
                scores[i] = scores.get(i, 0.0) + weight / (policy.rrf_constant + rank)
        ranked = sorted(scores, key=lambda i: (-scores[i], self.documents[i].identity))[
            : policy.top_k
        ]
        return [self.documents[i] for i in ranked], {
            "query_ns": time.perf_counter_ns() - start,
            "dense_dot_products": len(self.documents),
            "lexical_candidates": len(lexical),
            "dense_candidates": len(dense),
            "index_file_bytes": self.path.stat().st_size,
            "resident_vector_bytes": self.vectors.nbytes,
            "projection_cut": current_cut,
            "index_artifact_digest": self.file_digest,
            "encoder_identity": self.meta["encoder"],
            "policy": asdict(policy),
        }

    def close(self):
        self.db.close()


def tune_policy(cases, targets, indices, embeddings, cut, revoked, *, family_ids=None):
    """Only selection families may tune. Chunk hits are scored at native source granularity."""
    if not cases or any(partition != "select" for _, partition in cases):
        raise ValueError("tuning requires a nonempty selection-only view")
    candidates = [
        RetrievalPolicy(top_k=top_k, lexical_weight=weight)
        for top_k in (8,)
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    records = []
    for policy in candidates:
        family_recalls = {}
        for q, _ in cases:
            truth = targets[q.identity]
            if truth.unanswerable or not truth.evidence or truth.unresolved_evidence:
                continue
            docs, _ = indices[q.scope].query(
                q, embeddings[q.identity], policy, current_cut=cut, revoked=revoked
            )
            recalled = {source_id(d.identity) for d in docs}
            support = {source_id(identity) for identity in truth.evidence}
            family = family_ids[q.identity] if family_ids is not None else q.family
            family_recalls.setdefault(family, []).append(
                len(recalled.intersection(support)) / len(support)
            )
        recalls = [sum(values) / len(values) for values in family_recalls.values()]
        records.append((sum(recalls) / len(recalls) if recalls else -1.0, policy))
    best = max(
        records, key=lambda pair: (pair[0], -pair[1].top_k, pair[1].lexical_weight)
    )
    if best[0] < 0:
        raise ValueError("selection view has no supported evidence")
    return best[1], {
        "selection_ids": [q.identity for q, _ in cases],
        "objective": "equal-source-family-mean-annotated-evidence-recall-at-8",
        "selected_top_k": 8,
        "candidates": [{"recall": score, "policy": asdict(p)} for score, p in records],
    }
