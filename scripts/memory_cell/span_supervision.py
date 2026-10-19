"""Externally authored SQuAD-v2 spans, not native document-level pseudo-labels.

The original crowdsourced answer offsets/unanswerability are independent of this
selector. A window lacking an annotated span is NOT certified non-entailment.
Dataset admission, pretraining contamination and independent production review
remain separate from this read-only, byte-pinned development adapter.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from native import Document, Question, digest
from selector_head import Supervision

SQUAD_REVISION = "eee5fdbf62f8613a7812b03419e6b29617b74fd1"
SQUAD_BLOBS = {
    "train": "312f804dbf85888fdce3299eaa58d6ec3f0bb6b7",
    "dev": "c6fa1a89a12c90b7fbfa8f6fb437cfff27af41ca",
}
MAX_BYTES = 64 * 1024 * 1024


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate annotation field")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite annotation value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


@dataclass(frozen=True)
class SpanTarget:
    question_id: str
    source_id: str
    source_digest: str
    spans: tuple[tuple[int, int, str], ...]
    unanswerable: bool
    annotation_digest: str

    def indices(self, query, pool):
        pool.revalidate(query, set())
        if self.question_id != query.identity or type(self.unanswerable) is not bool:
            raise ValueError("annotation query binding")
        if self.unanswerable != (not self.spans):
            raise ValueError("missing annotation cannot become no-answer")
        if any(w.source_id != self.source_id for w in pool.windows):
            raise ValueError("SQuAD labels cover only the supplied paragraph")
        # The unread suffix is not falsely claimed to have been delivered.
        positives = []
        for i, window in enumerate(pool.windows):
            for start, end, text in self.spans:
                if window.start <= start < end <= window.end:
                    local = window.text.encode()[
                        start - window.start : end - window.start
                    ]
                    if local.decode("utf-8", "strict") != text:
                        raise ValueError("answer span detached from original bytes")
                    positives.append(i)
                    break
        return tuple(positives)


@dataclass(frozen=True)
class SpanCorpus:
    split: str
    sha256: str
    queries: tuple[Question, ...]
    documents: dict[str, Document]
    targets: dict[str, SpanTarget]


def parse_corpus(raw: bytes, split: str, *, expected_blob: str) -> SpanCorpus:
    if split not in SQUAD_BLOBS or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError("SQuAD split/byte bound")
    git_blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    if git_blob != expected_blob:
        raise ValueError("external annotation blob pin mismatch")
    data = strict_json(raw.decode("utf-8", "strict"))
    if data.get("version") != "v2.0" or not isinstance(data.get("data"), list):
        raise ValueError("native SQuAD 2.0 schema")
    queries, docs, targets = [], {}, {}
    for article in data["data"]:
        title = article["title"]
        if not isinstance(title, str) or not title or len(title.encode()) > 2048:
            raise ValueError("article family")
        family = "squad:article:" + digest(title.casefold())
        for paragraph in article["paragraphs"]:
            context = paragraph["context"]
            if (
                not isinstance(context, str)
                or not context.strip()
                or len(context.encode()) > 65536
            ):
                raise ValueError("paragraph bound")
            root = "squad:context:" + digest(context)
            doc = Document(root, root, root, root, "undated-source", context)
            docs[root] = doc
            for row in paragraph["qas"]:
                qid, question = row["id"], row["question"]
                if not isinstance(qid, str) or not qid or len(qid) > 128:
                    raise ValueError("native question identity")
                qid = "squad:" + qid
                if (
                    qid in targets
                    or not isinstance(question, str)
                    or not question.strip()
                    or len(question.encode()) > 65536
                ):
                    raise ValueError("duplicate/invalid native question")
                null = row["is_impossible"]
                if type(null) is not bool or not isinstance(row["answers"], list):
                    raise ValueError("native unanswerability type")
                if null != (not row["answers"]):
                    raise ValueError("contradictory or missing native answer")
                spans = set()
                for a in row["answers"]:
                    start, text = a["answer_start"], a["text"]
                    if (
                        type(start) is not int
                        or not isinstance(text, str)
                        or not text
                        or not 0 <= start < start + len(text) <= len(context)
                    ):
                        raise ValueError("native answer offset")
                    if context[start : start + len(text)] != text:
                        raise ValueError("native answer text mismatch")
                    begin = len(context[:start].encode())
                    spans.add((begin, begin + len(text.encode()), text))
                queries.append(Question(qid, family, root, question, "undated-source"))
                targets[qid] = SpanTarget(
                    qid, root, digest(context), tuple(sorted(spans)), null, digest(row)
                )
                if len(queries) > 200_000:
                    raise ValueError("question census bound")
    if not queries:
        raise ValueError("empty external corpus")
    return SpanCorpus(
        split, hashlib.sha256(raw).hexdigest(), tuple(queries), docs, targets
    )


def load_corpus(path: Path, split: str) -> SpanCorpus:
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular annotation file required")
    with path.open("rb") as stream:
        return parse_corpus(
            stream.read(MAX_BYTES + 1), split, expected_blob=SQUAD_BLOBS[split]
        )


def sample_families(queries, allowed, count):
    """Balanced deterministic ID sampling, with no answerability/answer input."""
    groups = {}
    for q in queries:
        if q.family in allowed:
            groups.setdefault(q.family, []).append(q)
    for group in groups.values():
        group.sort(key=lambda q: digest(q.identity))
    result, position = [], 0
    while len(result) < count:
        offered = [
            groups[f][position]
            for f in sorted(groups, key=digest)
            if position < len(groups[f])
        ]
        if not offered:
            raise ValueError("insufficient planned questions")
        result.extend(offered[: count - len(result)])
        position += 1
    return tuple(result)


def partitions(train: SpanCorpus, dev: SpanCorpus):
    """Freeze article-isolated train/selection cuts before feature extraction."""
    families = sorted({q.family for q in train.queries}, key=digest)
    dev_families = {q.family for q in dev.queries}
    if len(families) < 24 or set(families) & dev_families:
        raise ValueError("article train/development overlap or insufficient families")
    if set(train.documents) & set(dev.documents):
        raise ValueError("shared context across official split")
    # Contexts reused under different titles may not cross train/selection cuts.
    owners = {}
    for q in train.queries:
        owners.setdefault(q.scope, set()).add(q.family)
    if any(len(fs) > 1 for fs in owners.values()):
        raise ValueError("shared paragraphs require family-component resolution")
    return {
        "train": sample_families(train.queries, set(families[:16]), 128),
        "select": sample_families(train.queries, set(families[16:24]), 32),
        "squad_test": sample_families(dev.queries, dev_families, 16),
    }


def supervised_rows(queries, corpus, pools, features, cut):
    rows, dispositions = [], []
    for q in queries:
        # Check permissions BEFORE looking at an annotation.
        if q.identity not in cut.question_ids or q.family not in cut.families:
            raise ValueError("outside external training cut")
        pool, f = pools[q.identity], features[q.identity]
        target = corpus.targets[q.identity]
        doc = corpus.documents[q.scope]
        if (
            digest(doc.content) != target.source_digest
            or target.source_id != doc.identity
        ):
            raise ValueError("source identity/content drift")
        if (
            f.pool_digest != pool.seal()
            or f.question_id != q.identity
            or f.family != q.family
        ):
            raise ValueError("annotation-feature binding")
        positive = target.indices(q, pool)
        item = dict(
            question_id=q.identity,
            annotation_digest=target.annotation_digest,
            pool_digest=pool.seal(),
            positive_ids=[pool.windows[i].identity() for i in positive],
            unanswerable=target.unanswerable,
        )
        if not positive and not target.unanswerable:
            item["status"] = "annotated_span_not_visible_not_a_null_target"
        else:
            rows.append(Supervision(f, positive))
            item["status"] = "external_human_span_supervision"
        dispositions.append(item)
    return tuple(rows), dispositions
