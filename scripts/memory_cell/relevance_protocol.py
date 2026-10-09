"""Bounded query/evidence selection. Ranking is not semantic adjudication.

The protocol keeps native source offsets and training-family cuts. It neither
changes previous answers nor permits missing annotations to become true labels.
"""

from dataclasses import dataclass
import math
import re

from citation_audit import MARKER
from grounded_protocol import Quote
from native import Document, Question, Target, digest
from sessions import source_id

MAX_CANDIDATES = 64


def candidate_pool(documents: tuple[Document, ...], query: Question, revoked: set[str]):
    if not 1 <= len(documents) <= 8 or any(
        d.scope != query.scope or d.root in revoked for d in documents
    ) or len({d.identity for d in documents}) != len(documents):
        raise ValueError("candidate count, scope, duplicate or withdrawn source")
    sources, options = [], []
    for number, doc in enumerate(documents, 1):
        text = doc.content[:768]
        if not isinstance(doc.content, str) or "\0" in text:
            raise ValueError("invalid delivered source")
        text.encode("utf-8", "strict")
        label = f"E{number}"
        sources.append(dict(id=doc.identity, root=doc.root, label=label,
                            excerpt=text, partial=text != doc.content,
                            observed_at=doc.observed_at))
        cursor, emitted = 0, 0
        for part in re.split(r"(?<=[.!?])\s+|\n+", text):
            start = text.find(part, cursor)
            cursor = start + len(part)
            left = len(part) - len(part.lstrip())
            body = part.strip()
            if not body or len(body) > 240 or MARKER.search(body.encode()) or any(
                ord(c) < 32 for c in body
            ):
                continue
            if text != doc.content and cursor == len(text) and not body.endswith((".", "!", "?")):
                continue
            start += left
            options.append(Quote(label, doc.identity, doc.root,
                                 len(text[:start].encode()),
                                 len(text[:start + len(body)].encode()), body))
            emitted += 1
            if emitted == 8:
                break
    if len(options) > MAX_CANDIDATES:
        raise ValueError("candidate limit")
    return sources, tuple(options)


def passages(options, sources):
    by_id = {s["id"]: s for s in sources}
    result = []
    for option in options:
        source = by_id[option.source_id]
        if source["excerpt"].encode()[option.start:option.end].decode() != option.text:
            raise ValueError("detached candidate bytes")
        # Context and time are model inputs, never invented answer text.
        result.append(f"Observed {source['observed_at']}. "
                      f"Context: {source['excerpt'][:96]}\nPassage: {option.text}")
    return result


def choose(scores, options):
    if len(scores) != len(options) or not options or any(
        not math.isfinite(float(s)) for s in scores
    ):
        raise ValueError("empty or nonfinite relevance ranking")
    return min(range(len(scores)), key=lambda i: (-float(scores[i]), options[i].render()))


@dataclass(frozen=True)
class RankPair:
    family: str
    question_id: str
    question: str
    positive: Document
    negative: Document

    def content(self):
        return dict(family=self.family, question_id=self.question_id,
                    question=self.question, positive=self.positive.__dict__,
                    negative=self.negative.__dict__)


def training_pairs(queries, views, targets, phases, families):
    """Consume annotated support only for predeclared training families.

Unlabelled negatives are weak supervision, not certified non-entailment. Missing
or ambiguous support does not produce a positive or alter evaluation census.
"""
    owners, result = {}, []
    for query in queries:
        phase, family = phases[query.identity], families[query.family]
        if phase not in ("train", "select", "test") or owners.setdefault(family, phase) != phase:
            raise ValueError("family crosses phases")
        if phase != "train":
            continue
        truth: Target = targets[query.identity]
        docs = views[query.identity]
        if truth.unanswerable or truth.unresolved_evidence or not truth.evidence:
            continue
        if any(d.scope != query.scope for d in docs):
            raise ValueError("training view scope")
        supported = {source_id(i) for i in truth.evidence}
        positives = [d for d in docs if source_id(d.identity) in supported]
        negatives = [d for d in docs if source_id(d.identity) not in supported]
        if positives and negatives:
            result.append(RankPair(family, query.identity, query.content,
                                   positives[0], negatives[0]))
    return tuple(result)


def validate_training(pairs, permitted_questions, permitted_families, forbidden_roots, revoked):
    if not pairs or len(pairs) > 256:
        raise ValueError("no bounded train-only pairs")
    seen = set()
    for p in pairs:
        if p.question_id not in permitted_questions or p.family not in permitted_families:
            raise ValueError("nontraining query or family")
        if p.question_id in seen or not p.question.strip() or len(p.question.encode()) > 16384:
            raise ValueError("duplicate/invalid training question")
        seen.add(p.question_id)
        if p.positive.scope != p.negative.scope or p.positive.content == p.negative.content:
            raise ValueError("invalid source contrast")
        for doc in (p.positive, p.negative):
            if doc.root in forbidden_roots or doc.root in revoked:
                raise ValueError("held-out or withdrawn training source")
    return digest([p.content() for p in pairs])
