"""Runnable source-only BM25/code-token plus path-overlap retrieval baseline."""

from collections import Counter, defaultdict
from datetime import datetime
import math
from pathlib import Path
import re
import sqlite3
import time

from budget_ledger import canonical, digest


CONFIG = dict(k1=1.2, b=0.75, path_boost=1.5, top_k=5)


def tokens(text):
    words = re.findall(r"[a-z0-9_]+", text.casefold())
    code = re.findall(r"(?:[a-z0-9_.-]+/)+[a-z0-9_.-]+", text.casefold())
    return words + ["path:" + value for value in code]


def moment(value):
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("source availability needs a timezone")
    return when


def build(path, documents, *, train_until, excluded_groups=()):
    """Only admitted historical text enters postings; all source bytes retained."""
    path = Path(path)
    if path.exists():
        raise ValueError("index creation never overwrites an evaluated baseline")
    if not documents:
        raise ValueError("nonempty historical corpus required")
    before, cpu = time.perf_counter_ns(), time.process_time_ns()
    approved, seen = [], set()
    fields = {
        "doc_id",
        "group_id",
        "path",
        "text",
        "available_at",
        "origin",
        "source_sha256",
    }
    for row in documents:
        if (
            set(row) != fields
            or row["doc_id"] in seen
            or row["group_id"] in excluded_groups
        ):
            raise ValueError(
                "closed, distinct, source-only document admission required"
            )
        if moment(row["available_at"]) > moment(train_until):
            raise ValueError("future or final document cannot enter the source index")
        import hashlib

        if hashlib.sha256(row["text"].encode()).hexdigest() != row["source_sha256"]:
            raise ValueError("source text differs from pinned bytes")
        seen.add(row["doc_id"])
        approved.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE documents(id TEXT PRIMARY KEY, body BLOB, length INTEGER, path_tokens BLOB);"
            "CREATE TABLE postings(term TEXT, doc INTEGER, tf INTEGER, PRIMARY KEY(term,doc));"
            "CREATE TABLE metadata(name TEXT PRIMARY KEY, value BLOB);"
        )
        for row in approved:
            counts = Counter(tokens(row["text"]))
            inserted = db.execute(
                "INSERT INTO documents VALUES (?,?,?,?)",
                (
                    row["doc_id"],
                    canonical(row),
                    sum(counts.values()),
                    canonical(tokens(row["path"])),
                ),
            )
            db.executemany(
                "INSERT INTO postings VALUES (?,?,?)",
                [(t, inserted.lastrowid, c) for t, c in counts.items()],
            )
        metadata = dict(
            config=CONFIG,
            train_until=train_until,
            source_sha256=digest(approved),
            excluded_groups=list(excluded_groups),
            documents=len(approved),
            answer_gold_input=False,
        )
        db.execute(
            "INSERT INTO metadata VALUES ('manifest', ?)", (canonical(metadata),)
        )
    return dict(
        **metadata,
        wall_ns=time.perf_counter_ns() - before,
        cpu_ns=time.process_time_ns() - cpu,
        source_bytes=sum(len(row["text"].encode()) for row in approved),
        index_bytes=path.stat().st_size,
    )


class Retriever:
    def __init__(self, path):
        import json

        self.path = Path(path)
        self.db = sqlite3.connect(f"file:{self.path.resolve()}?mode=ro", uri=True)
        self.manifest = json.loads(
            self.db.execute(
                "SELECT value FROM metadata WHERE name='manifest'"
            ).fetchone()[0]
        )
        if self.manifest["config"] != CONFIG:
            raise ValueError("retrieval recipe changed after freeze")
        self.lengths = dict(self.db.execute("SELECT id,length FROM documents"))
        self.average = sum(self.lengths.values()) / len(self.lengths)

    def close(self):
        self.db.close()

    def query(self, request):
        import json

        if (
            set(request) != {"task_id", "text", "paths"}
            or type(request["paths"]) is not list
        ):
            raise ValueError(
                "inference request contains only original failure and paths"
            )
        if (
            not isinstance(request["text"], str)
            or len(request["text"].encode()) > 1024 * 1024
        ):
            raise ValueError("bounded original task input required")
        before, cpu = time.perf_counter_ns(), time.process_time_ns()
        words = Counter(tokens(request["text"]))
        path_words = set(tokens(" ".join(request["paths"])))
        scores, n = defaultdict(float), len(self.lengths)
        for term in words:
            matches = list(
                self.db.execute(
                    "SELECT d.id,p.tf FROM postings p JOIN documents d ON d.rowid=p.doc WHERE p.term=?",
                    (term,),
                )
            )
            idf = math.log(1 + (n - len(matches) + 0.5) / (len(matches) + 0.5))
            for doc, tf in matches:
                denominator = tf + CONFIG["k1"] * (
                    1
                    - CONFIG["b"]
                    + CONFIG["b"] * self.lengths[doc] / max(self.average, 1)
                )
                scores[doc] += idf * tf * (CONFIG["k1"] + 1) / denominator
        if path_words:
            for doc, raw in self.db.execute("SELECT id,path_tokens FROM documents"):
                overlap = len(set(json.loads(raw)) & path_words) / len(path_words)
                scores[doc] += CONFIG["path_boost"] * overlap
        ranked = sorted(
            ((score, doc) for doc, score in scores.items() if score > 0),
            key=lambda x: (-x[0], x[1]),
        )[: CONFIG["top_k"]]
        results = []
        for score, doc in ranked:
            source = json.loads(
                self.db.execute(
                    "SELECT body FROM documents WHERE id=?", (doc,)
                ).fetchone()[0]
            )
            results.append(dict(score=score, document=source))
        return dict(
            task_id=request["task_id"],
            request_sha256=digest(request),
            results=results,
            source_manifest_sha256=self.manifest["source_sha256"],
            config=CONFIG,
            wall_ns=time.perf_counter_ns() - before,
            cpu_ns=time.process_time_ns() - cpu,
            source_bytes_returned=sum(
                len(r["document"]["text"].encode()) for r in results
            ),
            decoder_queries=0,
            feature_forwards=0,
            final_gold_input=False,
        )
