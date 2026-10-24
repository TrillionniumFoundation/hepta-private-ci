"""Pinned LoCoMo text-memory input, with gold isolated from retrieval objects.

Only original conversation text, speaker and session time enter the index.
Generated observations/summaries, QA answers, evidence IDs and question category
never enter a Corpus or Query. The benchmark is generated conversational data,
not authenticated production-user memory or a fresh longitudinal collection.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata

SOURCE_COMMIT = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
SOURCE_BLOB = "d95b872480b413d935821fdc3c84f8a8f5f29e73"
SOURCE_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
SOURCE_BYTES = 2_805_274
SOURCE_URL = f"https://raw.githubusercontent.com/snap-research/locomo/{SOURCE_COMMIT}/data/locomo10.json"
LICENSE_URL = f"https://github.com/snap-research/locomo/blob/{SOURCE_COMMIT}/LICENSE.txt"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class Turn:
    source_id: str
    session: str
    order: int
    speaker: str
    timestamp: str
    text: str
    has_image: bool

    def render(self):
        return f"[{self.source_id} | {self.session} | {self.timestamp} | {self.speaker}]\n{self.text}\n"


@dataclass(frozen=True)
class Corpus:
    group: str
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class Query:
    query_id: str
    group: str
    text: str


@dataclass(frozen=True)
class Gold:
    category: int
    evidence: tuple[str, ...]
    unresolved: tuple[str, ...]
    evidence_has_image: bool


def decode_source(rows):
    """Separate raw memory/query objects from evaluator-only annotations.

    Unresolved evidence stays unresolved. In particular, punctuation, zero
    padding and multiple IDs inside one annotation are never silently repaired.
    """
    corpora, queries, gold = {}, [], {}
    for row in rows:
        group = row["sample_id"]
        if not isinstance(group, str) or group in corpora:
            raise ValueError("duplicate or invalid conversation source group")
        conversation, turns = row["conversation"], []
        sessions = sorted((k for k in conversation if re.fullmatch(r"session_\d+", k)),
                          key=lambda k: int(k.split("_")[1]))
        for session in sessions:
            timestamp = conversation[session + "_date_time"]
            for order, turn in enumerate(conversation[session]):
                values = (turn["dia_id"], turn["speaker"], timestamp, turn["text"])
                if not all(isinstance(v, str) for v in values):
                    raise ValueError("non-text original conversation field")
                turns.append(Turn(*values[:1], session, order, values[1], values[2],
                                  values[3], bool(turn.get("img_url"))))
        by_id = {t.source_id: t for t in turns}
        if len(by_id) != len(turns) or not turns:
            raise ValueError("duplicate dialogue IDs or empty conversation")
        corpora[group] = Corpus(group, tuple(turns))
        for index, item in enumerate(row["qa"]):
            qid = f"{group}:qa:{index:04d}"
            if not isinstance(item["question"], str) or not item["question"].strip():
                raise ValueError("invalid question text")
            category, evidence = item["category"], item.get("evidence", [])
            if category not in (1, 2, 3, 4, 5) or not isinstance(evidence, list):
                raise ValueError("unsupported original QA annotation")
            if not all(isinstance(ref, str) for ref in evidence):
                raise ValueError("non-string evidence annotation")
            queries.append(Query(qid, group, item["question"]))
            gold[qid] = Gold(category, tuple(evidence),
                tuple(ref for ref in evidence if ref not in by_id),
                any(by_id[ref].has_image for ref in evidence if ref in by_id))
    return corpora, tuple(queries), gold


def load_source(path):
    data = Path(path).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if len(data) != SOURCE_BYTES or sha(data) != SOURCE_SHA256 or blob != SOURCE_BLOB:
        raise ValueError("LoCoMo source differs from independently pinned original bytes")
    result = decode_source(json.loads(data))
    if len(result[0]) != 10 or len(result[1]) != 1986:
        raise ValueError("original conversation/question census changed")
    return result


def source_partitions(corpora):
    if len(corpora) != 10:
        raise ValueError("fixed protocol requires all ten original conversations")
    ordered = sorted(corpora, key=lambda key: sha(("hepta-locomo-source-group-v1:" + key).encode()))
    return {"development": ordered[:2], "calibration": ordered[2:4], "evaluation": ordered[4:]}


def source_audit(corpora, queries, gold, partitions):
    seen, overlaps = {}, set()
    for group, corpus in corpora.items():
        for turn in corpus.turns:
            normalized = " ".join(unicodedata.normalize("NFKC", turn.text).casefold().split())
            if len(normalized.split()) < 10:
                continue
            pin = sha(normalized.encode())
            if pin in seen and seen[pin] != group:
                overlaps.add((pin, min(group, seen[pin]), max(group, seen[pin])))
            seen[pin] = group
    return {
        "groups": len(corpora), "questions": len(queries),
        "turns": sum(len(c.turns) for c in corpora.values()),
        "image_referenced_turns": sum(t.has_image for c in corpora.values() for t in c.turns),
        "unresolved_evidence_questions": sum(bool(g.unresolved) for g in gold.values()),
        "empty_evidence_questions": sum(not g.evidence for g in gold.values()),
        "cross_group_exact_text_overlaps_at_least_ten_words": len(overlaps),
        "declared_conversation_partitions": partitions,
        "source_group_independence_authenticated": False,
        "near_duplicate_or_pretraining_exposure_excluded": False,
        "images_loaded": False, "generated_summaries_used": False,
        "gold_answers_used": False,
    }
