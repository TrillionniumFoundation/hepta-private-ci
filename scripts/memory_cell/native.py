"""Native benchmark ingress. History and held-out annotations have distinct types.

These are read-only evaluation adapters, not cognitive.store writers. A published
benchmark is not automatically a prospective, independent production experiment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from sessions import normalize_sessions, source_id

MAX_BYTES = 512 * 1024 * 1024


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


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
    unresolved_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Benchmark:
    name: str
    source_sha256: str
    documents: tuple[Document, ...]
    questions: tuple[Question, ...]
    targets: dict[str, Target]
    families: dict[str, str]
    ingress_issues: tuple[dict, ...] = ()
    ingress_failures: dict[str, dict] = field(default_factory=dict)

    def history(self, query: Question) -> tuple[Document, ...]:
        return tuple(d for d in self.documents if d.scope == query.scope)

    def partition(self, query: Question) -> str:
        families = sorted(set(self.families.values()), key=digest)
        if len(families) < 3:
            raise ValueError("fewer than three independent source families")
        rank = families.index(self.families[query.family])
        train_end = min(len(families) - 2, max(1, len(families) * 6 // 10))
        select_end = min(len(families) - 1, max(train_end + 1, len(families) * 8 // 10))
        return (
            "train" if rank < train_end else "select" if rank < select_end else "test"
        )


def load(
    path: Path,
    kind: str,
    expected_sha256: str | None = None,
    *,
    allow_unresolved_evidence: bool = False,
    session_conflicts: str = "reject",
    invalid_history: str = "reject",
) -> Benchmark:
    if invalid_history not in ("reject", "quarantine-question"):
        raise ValueError("unknown invalid-history profile")
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
    ingress_issues = []
    ingress_failures = {}
    session_origins = {}
    for sample in data:
        if kind == "longmemeval":
            qid = text(sample["question_id"], "question id", 256)
            scope = f"longmemeval:{qid}"
            sessions, ids, dates = (
                sample["haystack_sessions"],
                sample["haystack_session_ids"],
                sample["haystack_dates"],
            )
            try:
                normalized, duplicates = normalize_sessions(
                    sessions, ids, dates, conflict_policy=session_conflicts
                )
            except ValueError as error:
                if invalid_history == "reject":
                    raise
                # Keep the native question/target and exact bad-history identity.
                # No partial or fabricated history is released to any model arm.
                ingress_failures[scope] = {
                    "stage": "native-history-ingress",
                    "error_type": type(error).__name__,
                    "error_digest": digest(str(error)),
                    "history_digest": digest((sessions, ids, dates)),
                }
                normalized, duplicates = (
                    [],
                    [
                        {
                            "identity": scope,
                            "disposition": "question-retained-history-quarantined",
                            **ingress_failures[scope],
                        }
                    ],
                )
            original_ids = {
                version: row["identity"]
                for row in duplicates
                for version in row.get("versioned_identities", [])
            }
            ingress_issues.extend({"question_id": qid, **row} for row in duplicates)
            known = set()
            for turns, sid, date in normalized:
                sid = text(sid, "session occurrence id", 512)
                date = text(date, "session date", 256)
                if not isinstance(turns, list) or not 1 <= len(turns) <= 10_000:
                    raise ValueError("invalid session turns")
                clean = []
                for turn in turns:
                    if turn["role"] not in ("user", "assistant", "system"):
                        raise ValueError("unknown history role")
                    clean.append((turn["role"], text(turn["content"], "turn")))
                native_sid = original_ids.get(sid, source_id(sid))
                # Repeated/edited copies of one native source are one family.
                root = "session:" + digest(clean)
                identity = f"{scope}/{sid}"
                known.add(source_id(identity))
                session_origins[identity] = native_sid
                docs.append(
                    Document(
                        identity,
                        root,
                        scope,
                        native_sid,
                        date,
                        "\n".join(f"{role}: {content}" for role, content in clean),
                    )
                )
            query = Question(
                scope,
                scope,
                scope,
                text(sample["question"], "question"),
                text(sample["question_date"], "question date", 256),
            )
            answer_ids = sample["answer_session_ids"]
            if not isinstance(answer_ids, list) or len(answer_ids) > 10_000:
                raise ValueError("invalid LongMemEval answer session IDs")
            support = tuple(
                f"{scope}/{text(sid, 'answer session id', 256)}" for sid in answer_ids
            )
            missing = tuple(sorted(set(support) - known))
            if missing and not allow_unresolved_evidence:
                raise ValueError(f"dangling LongMemEval evidence: {missing[:4]}")
            target = Target(
                str(sample["answer"]),
                text(sample["question_type"], "question type", 128),
                support,
                qid.endswith("_abs"),
                missing,
            )
            queries.append(query)
            if query.identity in targets:
                raise ValueError("duplicate question")
            targets[query.identity] = target
        elif kind == "locomo":
            family = "locomo:" + text(str(sample["sample_id"]), "sample id", 256)
            conversation = sample["conversation"]
            sessions = sorted(
                (
                    k
                    for k in conversation
                    if k.startswith("session_") and k[8:].isdigit()
                ),
                key=lambda k: int(k[8:]),
            )
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
                        content += (
                            "\n[provided image caption; not observed pixels] "
                            + text(caption, "caption")
                        )
                    asset = turn.get("img_url")
                    assets = (
                        tuple(asset)
                        if isinstance(asset, list)
                        else (asset,)
                        if asset
                        else ()
                    )
                    if any(not isinstance(a, str) for a in assets):
                        raise ValueError("invalid image reference")
                    docs.append(
                        Document(
                            identity, family, family, session, date, content, assets
                        )
                    )
            if not sessions:
                raise ValueError("missing LoCoMo sessions")
            for index, qa in enumerate(sample["qa"]):
                qid = f"{family}/q{index}"
                category = qa["category"]
                if category not in (1, 2, 3, 4, 5):
                    raise ValueError("unknown LoCoMo category")
                evidence = tuple(f"{family}/{x}" for x in qa.get("evidence", []))
                missing = tuple(sorted(set(evidence) - known))
                if missing and not allow_unresolved_evidence:
                    raise ValueError(f"dangling LoCoMo evidence: {missing[:4]}")
                queries.append(
                    Question(
                        qid,
                        family,
                        family,
                        text(qa["question"], "question"),
                        conversation[sessions[-1] + "_date_time"],
                    )
                )
                if qid in targets:
                    raise ValueError("duplicate sample/question")
                targets[qid] = Target(
                    None if category == 5 else str(qa["answer"]),
                    str(category),
                    evidence,
                    category == 5,
                    missing,
                )
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
        keys = [doc.root]
        if kind == "longmemeval":
            keys.append("native-session:" + digest(session_origins[doc.identity]))
        for key in keys:
            previous = roots.setdefault(key, family)
            left, right = sorted((find(previous), find(family)))
            parents[right] = left
    families = {family: find(family) for family in parents}
    return Benchmark(
        kind,
        sha,
        tuple(docs),
        tuple(queries),
        targets,
        families,
        tuple(ingress_issues),
        ingress_failures,
    )


def export_inputs(benchmark: Benchmark, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    for name, values in (
        ("history", benchmark.documents),
        ("queries", benchmark.questions),
    ):
        with (directory / f"{name}.jsonl").open("x") as out:
            for value in values:
                out.write(json.dumps(asdict(value), ensure_ascii=False) + "\n")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "hepta.memory-benchmark-input.v1",
                "benchmark": benchmark.name,
                "source_sha256": benchmark.source_sha256,
                "families": benchmark.families,
                "annotations_in_model_input": False,
                "visual_mode": "provided-captions-only",
            },
            indent=2,
        )
    )
