"""Bounded, local SuperGLUE-v2 MultiRC input and exact grouped metrics.

Provenance: https://super.gluebenchmark.com/faq/ and the official archive below.
The SuperGLUE schema is passage/label; original MultiRC paragraph/isAnswer is
accepted explicitly but is not interchangeable with the benchmark's splits.
Labels and evidence annotations are never included in public_text or its hash.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re

OFFICIAL_URL = "https://dl.fbaipublicfiles.com/glue/superglue/data/v2/MultiRC.zip"
OFFICIAL_ZIP_SHA256 = "b3cd440856e72eb166b2edcd37b798455f1ebd51f2c3de64c0c2a4e1971d2737"
HF_REVISION = "c52aab6a51814a72f4bd18cd83630d98aab1e97d"
HF_FILES = {
    "multirc/train-00000-of-00001.parquet": "ced6d731a335a0e4fbd29f6f382f291518952c0f449448361d294000c39e6728",
    "multirc/validation-00000-of-00001.parquet": "5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada",
}
DEFAULT_PARTITIONS = (("train", 50), ("tune", 10), ("verifier_fit", 10),
                      ("critic_fit", 15), ("critic_calibration", 15))
_MARKER = re.compile(r"<b>\s*Sent\s+(\d+)\s*:?[ \t]*</b>", re.I)
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])|(?<=[.!?][\"'])\s+(?=[A-Z0-9\"'])")


def _hash(value):
    return sha256(value.encode("utf-8")).hexdigest()


def _id(value):
    if (type(value) not in (str, int) or not str(value) or len(str(value)) > 256):
        raise ValueError("invalid source index")
    return str(value)


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"br", "p"}:
            self.parts.append("\n")


def _plain(value):
    parser = _Plain()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def _facts(text):
    matches = list(_MARKER.finditer(text))
    if matches:
        pieces, ids = [], []
        prefix = _plain(text[:matches[0].start()]).strip()
        if prefix:
            pieces.append(prefix)
            ids.append(None)
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            pieces.append(_plain(text[match.end():end]))
            ids.append(int(match[1]))
        mode = "source-sent-markers"
    else:
        lines = [line for line in _plain(text).splitlines() if line.strip()]
        pieces = lines if len(lines) > 1 else _BOUNDARY.split(lines[0] if lines else "")
        ids = [None] * len(pieces)
        mode = "source-lines" if len(lines) > 1 else "punctuation-v1"
    pairs = [(" ".join(piece.split()), idx) for piece, idx in zip(pieces, ids)]
    if any(not value for value, _ in pairs):
        raise ValueError("empty sentence chunk")
    return tuple(value for value, _ in pairs), tuple(idx for _, idx in pairs), mode


@dataclass(frozen=True)
class ReaderCase:
    paragraph_id: str
    question_id: str
    answer_id: str
    question: str
    candidate: str
    facts: tuple
    label: int
    source_split: str
    source_hash: str
    sentence_ids: tuple = ()
    evidence_sentence_indices: tuple = ()
    segmentation: str = "unknown"

    def __post_init__(self):
        for name in ("paragraph_id", "question_id", "answer_id"):
            object.__setattr__(self, name, _id(getattr(self, name)))
        for name in ("facts", "sentence_ids", "evidence_sentence_indices"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if (type(self.label) is not int or self.label not in (0, 1)
                or self.source_split not in ("train", "validation")
                or re.fullmatch(r"[0-9a-f]{64}", self.source_hash) is None):
            raise ValueError("binary label and explicit source provenance required")
        if (not isinstance(self.question, str) or not self.question.strip()
                or not isinstance(self.candidate, str)
                or not self.facts or any(not isinstance(f, str) or not f.strip() for f in self.facts)
                or self.sentence_ids and len(self.sentence_ids) != len(self.facts)):
            raise ValueError("complete question, candidate and immutable facts required")

    @property
    def case_id(self):
        return json.dumps([self.source_split, self.paragraph_id, self.question_id, self.answer_id], separators=(",", ":"))

    @property
    def question_key(self):
        return self.source_split, self.paragraph_id, self.question_id

    @property
    def public_text(self):
        return "\n".join(("[QUESTION]", self.question, "[CANDIDATE]", self.candidate, "[PASSAGE]", *self.facts))

    @property
    def feature_source_hash(self):
        return _hash(self.public_text)


@dataclass(frozen=True)
class RejectedParagraph:
    paragraph_id: str
    reason: str
    candidates: int


@dataclass(frozen=True)
class DatasetLoad:
    cases: tuple
    rejected: tuple
    sha256: str
    paragraphs_seen: int
    schema_counts: tuple

    @property
    def counts(self):
        return dict(paragraphs_seen=self.paragraphs_seen,
                    accepted_paragraphs=len({(c.source_split, c.paragraph_id) for c in self.cases}),
                    accepted_candidates=len(self.cases), rejected_paragraphs=len(self.rejected),
                    empty_candidate_texts=sum(not c.candidate for c in self.cases),
                    rejected_candidates=sum(r.candidates for r in self.rejected),
                    rejection_reasons=dict(Counter(r.reason for r in self.rejected)))


def load_jsonl(path, source_split, *, max_facts=64, max_sentence_chars=4096,
               max_cases=100000, max_bytes=64 * 1024 * 1024):
    """Read all source bytes; reject complete paragraphs rather than truncate.

    Unknown/schema-invalid rows and all their candidates are recorded as rejected.
    Duplicate source indices are fatal. Only official train/validation are labeled.
    The file digest includes every original byte, including rejected rows.
    """
    if source_split not in ("train", "validation"):
        raise ValueError("only labeled train and validation sources are admitted")
    if any(type(v) is not int or v < 1 for v in (max_facts, max_sentence_chars, max_cases, max_bytes)):
        raise ValueError("positive integer bounds required")
    if Path(path).stat().st_size > max_bytes:
        raise ValueError("source file byte bound exceeded")
    cases, rejected, seen, schemas = [], [], set(), Counter()
    digest, byte_count, paragraphs = sha256(), 0, 0
    with Path(path).open("rb") as stream:
        for raw in stream:
            byte_count += len(raw)
            if byte_count > max_bytes or len(raw) > 2 * 1024 * 1024:
                raise ValueError("source byte or paragraph-line bound exceeded")
            digest.update(raw)
            if not raw.strip():
                continue
            paragraphs += 1
            if paragraphs > 100000:
                raise ValueError("source paragraph bound exceeded")
            paragraph_id, candidate_count = f"line:{paragraphs}", 0
            try:
                row = json.loads(raw)
                paragraph_id = _id(row["idx"])
                if paragraph_id in seen:
                    raise RuntimeError("duplicate paragraph index")
                seen.add(paragraph_id)
                if "passage" in row and "paragraph" not in row:
                    passage, label_key, schema = row["passage"], "label", "superglue-v2"
                elif "paragraph" in row and "passage" not in row:
                    passage, label_key, schema = row["paragraph"], "isAnswer", "original-multirc"
                else:
                    raise ValueError("ambiguous paragraph schema")
                schemas[schema] += 1
                text, questions = passage["text"], passage["questions"]
                if not isinstance(text, str) or not text.strip() or not isinstance(questions, list) or not 1 <= len(questions) <= 256:
                    raise ValueError("invalid paragraph or question list")
                candidate_count = sum(len(q.get("answers", [])) for q in questions if isinstance(q, dict))
                facts, sentence_ids, segmentation = _facts(text)
                if len(facts) > max_facts:
                    rejected.append(RejectedParagraph(paragraph_id, "facts_limit", candidate_count))
                    continue
                if any(len(f) > max_sentence_chars for f in facts):
                    rejected.append(RejectedParagraph(paragraph_id, "sentence_chars_limit", candidate_count))
                    continue
                current, qids = [], set()
                for question in questions:
                    qid, query, answers = _id(question["idx"]), question["question"], question["answers"]
                    if qid in qids or not isinstance(query, str) or not query.strip() or len(query) > max_sentence_chars:
                        raise ValueError("invalid or duplicate question")
                    qids.add(qid)
                    if not isinstance(answers, list) or not 1 <= len(answers) <= 128:
                        raise ValueError("invalid answer list")
                    annotations = question.get("sentences_used", ())
                    if not isinstance(annotations, (list, tuple)) or any(type(i) is not int for i in annotations):
                        raise ValueError("invalid evidence annotation")
                    aids = set()
                    for answer in answers:
                        aid, candidate, label = _id(answer["idx"]), answer["text"], answer[label_key]
                        if (aid in aids or not isinstance(candidate, str)
                                or len(candidate) > max_sentence_chars or type(label) not in (int, bool) or label not in (0, 1)):
                            raise ValueError("invalid or duplicate answer")
                        aids.add(aid)
                        current.append(ReaderCase(paragraph_id, qid, aid, query, candidate, facts, int(label),
                            source_split, _hash(text), sentence_ids, tuple(annotations), segmentation))
                if len(cases) + len(current) > max_cases:
                    rejected.append(RejectedParagraph(paragraph_id, "cases_limit", candidate_count))
                else:
                    cases.extend(current)
            except RuntimeError:
                raise ValueError("duplicate paragraph index") from None
            except (KeyError, TypeError, ValueError, AttributeError):
                rejected.append(RejectedParagraph(paragraph_id, "invalid_schema", candidate_count))
    return DatasetLoad(tuple(cases), tuple(rejected), digest.hexdigest(), paragraphs, tuple(sorted(schemas.items())))


def partition_cases(cases, *, seed=41, fractions=DEFAULT_PARTITIONS):
    """Hash entire source paragraphs, independent of labels/candidate ordering."""
    if (type(seed) is not int or not fractions or sum(weight for _, weight in fractions) != 100
            or any(not isinstance(name, str) or not name or name == "final" or type(weight) is not int or weight <= 0
                   for name, weight in fractions) or len({name for name, _ in fractions}) != len(fractions)):
        raise ValueError("unique positive partition weights must total 100")
    result = {name: [] for name, _ in fractions}
    result["final"] = []
    provenance, ids = {}, set()
    for case in cases:
        if case.case_id in ids:
            raise ValueError("duplicate candidate identifier")
        ids.add(case.case_id)
        previous = provenance.setdefault(case.source_hash, case.source_split)
        if previous != case.source_split:
            raise ValueError("paragraph content overlaps official train/validation")
        if case.source_split == "validation":
            name = "final"
        else:
            bucket = int(_hash(f"multirc-v2/{seed}/{case.source_hash}"), 16) % 100
            stop = 0
            for name, weight in fractions:
                stop += weight
                if bucket < stop:
                    break
        result[name].append(case)
    return {name: tuple(rows) for name, rows in result.items()}


def score_multirc(cases, predictions):
    """Score all supplied candidates: global positive F1 and per-question EM.

    F1a and EM match SuperGLUE's definitions. F1m uses the union of labels and
    predictions present within each question, as sklearn macro-F1 does. This
    reports a supplied cohort, not an attestation of complete benchmark coverage.
    """
    cases, predictions = tuple(cases), tuple(predictions)
    if not cases or len(cases) != len(predictions) or any(type(p) is not int or p not in (0, 1) for p in predictions):
        raise ValueError("one binary prediction per nonempty reference candidate required")
    grouped, seen = defaultdict(list), set()
    for case, prediction in zip(cases, predictions):
        if case.case_id in seen:
            raise ValueError("duplicate candidate identifier")
        seen.add(case.case_id)
        grouped[case.question_key].append((case.label, prediction))
    def f1(rows, positive):
        tp = sum(gold == pred == positive for gold, pred in rows)
        denominator = sum(gold == positive for gold, _ in rows) + sum(pred == positive for _, pred in rows)
        return 2 * tp / denominator if denominator else 0.0
    all_rows = [(case.label, pred) for case, pred in zip(cases, predictions)]
    macros = [sum(f1(rows, label) for label in {v for pair in rows for v in pair}) /
              len({v for pair in rows for v in pair}) for rows in grouped.values()]
    return dict(candidates=len(cases), questions=len(grouped), paragraphs=len({(c.source_split, c.paragraph_id) for c in cases}),
                f1_a=f1(all_rows, 1), exact_match=sum(all(g == p for g, p in rows) for rows in grouped.values()) / len(grouped),
                f1_m=sum(macros) / len(macros), accuracy=sum(g == p for g, p in all_rows) / len(all_rows))
