"""Native benchmark ingress. History and held-out annotations have distinct types.

These are read-only evaluation adapters, not cognitive.store writers. A published
benchmark is not automatically a prospective, independent production experiment.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_BYTES = 512 * 1024 * 1024


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def text(value: Any, name: str, limit: int = 1_000_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class Document:
    identity: str
    root: str
    scope: str
    session: str
    observed_at: str
    content: str
    assets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Question:
    identity: str
    family: str
    scope: str
    content: str
    observed_at: str


@dataclass(frozen=True)
class Target:
    answer: str | None
    category: str
    evidence: tuple[str, ...]
    unanswerable: bool


@dataclass(frozen=True)
class Benchmark:
    name: str
    source_sha256: str
    documents: tuple[Document, ...]
    questions: tuple[Question, ...]
    targets: dict[str, Target]
    # Root-connected families, not an arbitrary new root name for every copy.
    families: dict[str, str]

    def history(self, query: Question) -> tuple[Document, ...]:
        return tuple(d for d in self.documents if d.scope == query.scope)

    def partition(self, query: Question) -> str:
        bucket = int(digest(self.families[query.family])[:8], 16) % 10
        return "train" if bucket < 6 else "select" if bucket < 8 else "test"


def load(path: Path, kind: str, expected_sha256: str | None = None) -> Benchmark:
    with path.open("rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("benchmark byte limit")
    sha = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError("benchmark digest mismatch")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result
    data = json.loads(payload, object_pairs_hook=unique_object)
    if not isinstance(data, list) or not 1 <= len(data) <= 10_000:
        raise ValueError("invalid benchmark top-level/count")
    docs: list[Document] = []
    queries: list[Question] = []
    targets: dict[str, Target] = {}
    for sample in data:
        if kind == "longmemeval":
            qid = text(sample["question_id"], "question id", 256)
            scope = f"longmemeval:{qid}"
            sessions = sample["haystack_sessions"]
            ids = sample["haystack_session_ids"]
            dates = sample["haystack_dates"]
            if not len(sessions) == len(ids) == len(dates) or len(ids) > 10_000 or len(set(ids)) != len(ids):
                raise ValueError("misaligned/duplicate sessions")
            known = set()
            for sid, date, turns in zip(ids, dates, sessions, strict=True):
                sid = text(sid, "session id", 256)
                date = text(date, "session date", 256)
                if not isinstance(turns, list) or not 1 <= len(turns) <= 10_000:
                    raise ValueError("invalid session turns")
                clean = []
                for turn in turns:
                    if turn["role"] not in ("user", "assistant", "system"):
                        raise ValueError("unknown history role")
                    # Never copy has_answer or any other benchmark label.
                    clean.append((turn["role"], text(turn["content"], "turn")))
                root = "session:" + digest((sid, clean))
                identity = f"{scope}/{sid}"
                known.add(identity)
                docs.append(Document(identity, root, scope, sid, date,
                                     "\n".join(f"{role}: {content}" for role, content in clean)))
            query = Question(scope, scope, scope, text(sample["question"], "question"),
                             text(sample["question_date"], "question date", 256))
            support = tuple(f"{scope}/{sid}" for sid in sample["answer_session_ids"])
            if not set(support).issubset(known):
                raise ValueError("dangling LongMemEval evidence")
            target = Target(str(sample["answer"]), text(sample["question_type"], "question type", 128), support, qid.endswith("_abs"))
            queries.append(query)
            if query.identity in targets:
                raise ValueError("duplicate question")
            targets[query.identity] = target
        elif kind == "locomo":
            family = "locomo:" + text(str(sample["sample_id"]), "sample id", 256)
            conversation = sample["conversation"]
            sessions = sorted((k for k in conversation if k.startswith("session_") and k[8:].isdigit()), key=lambda k: int(k[8:]))
            known = set()
            for session in sessions:
                date = text(conversation[session + "_date_time"], "session date", 256)
                for turn in conversation[session]:
                    did = text(turn["dia_id"], "dialog id", 256)
                    identity = f"{family}/{did}"
                    if identity in known:
                        raise ValueError("duplicate dialog id")
                    known.add(identity)
                    content = f"{text(turn['speaker'], 'speaker', 256)}: {text(turn['text'], 'turn')}"
                    caption = turn.get("blip_caption")
                    if caption:
                        content += "\n[provided image caption; not observed pixels] " + text(caption, "caption")
                    asset = turn.get("img_url")
                    assets = tuple(asset) if isinstance(asset, list) else (asset,) if asset else ()
                    if any(not isinstance(a, str) for a in assets):
                        raise ValueError("invalid image reference")
                    docs.append(Document(identity, family, family, session, date, content, assets))
            if not sessions:
                raise ValueError("missing LoCoMo sessions")
            for index, qa in enumerate(sample["qa"]):
                qid = f"{family}/q{index}"
                category = qa["category"]
                if category not in (1, 2, 3, 4, 5):
                    raise ValueError("unknown LoCoMo category")
                evidence = tuple(f"{family}/{x}" for x in qa.get("evidence", []))
                if not set(evidence).issubset(known):
                    raise ValueError("dangling LoCoMo evidence")
                queries.append(Question(qid, family, family, text(qa["question"], "question"), conversation[sessions[-1] + "_date_time"]))
                if qid in targets:
                    raise ValueError("duplicate sample/question")
                # Adversarial answers are distractors, NEVER an expected factual answer.
                targets[qid] = Target(None if category == 5 else str(qa["answer"]), str(category), evidence, category == 5)
        else:
            raise ValueError("unsupported native benchmark")
        if len(docs) > 250_000 or len(queries) > 20_000:
            raise ValueError("benchmark item limit")
    if len({d.identity for d in docs}) != len(docs):
        raise ValueError("duplicate document identity")
    parents = {q.family: q.family for q in queries}
    scope_family = {q.scope: q.family for q in queries}
    def find(x):
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x
    roots: dict[str, str] = {}
    for doc in docs:
        family = scope_family[doc.scope]
        previous = roots.setdefault(doc.root, family)
        left, right = sorted((find(previous), find(family)))
        parents[right] = left
    families = {family: find(family) for family in parents}
    return Benchmark(kind, sha, tuple(docs), tuple(queries), targets, families)


def export_inputs(benchmark: Benchmark, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    for name, values in (("history", benchmark.documents), ("queries", benchmark.questions)):
        with (directory / f"{name}.jsonl").open("x") as out:
            for value in values:
                out.write(json.dumps(asdict(value), ensure_ascii=False) + "\n")
    (directory / "manifest.json").write_text(json.dumps({
        "schema": "hepta.memory-benchmark-input.v1", "benchmark": benchmark.name,
        "source_sha256": benchmark.source_sha256, "families": benchmark.families,
        "annotations_in_model_input": False, "visual_mode": "provided-captions-only",
    }, indent=2))
