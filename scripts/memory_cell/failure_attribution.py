"""Deterministic per-question failure attribution for MemoryCell journals.

This module consumes already-recorded attempts and optional held-out annotations.
It never scores semantics, rewrites answers, or drops failed/negative attempts.
Stage names describe observable pipeline boundaries only; citation semantics stay
unknown (``semantic_citation_precision`` is always ``None``).
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from sessions import source_id

SCHEMA = "hepta.memory-cell.failure-attribution.v1"
# Keep this diagnostic import-free from torch-backed generation modules.
ABSTAIN = "I do not have enough evidence."
STAGES = (
    "history_ingress",
    "retrieval_or_window",
    "ranking",
    "generation",
    "abstention",
    "citation_structure",
    "time",
)


def _target_value(target: Any, name: str, default: Any = None):
    if isinstance(target, Mapping):
        return target.get(name, default)
    return getattr(target, name, default)


def _source_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    # Native source_id removes chunk/occurrence selectors while retaining
    # version identities. Window IDs are retained as-is when no native suffix.
    return source_id(value)


def _receipt(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("receipt")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("receipt must be an object")
    return value


def _target_sources(target: Any) -> set[str]:
    values = _target_value(target, "evidence", ())
    if not isinstance(values, (list, tuple, set)):
        raise ValueError("target evidence must be a sequence")
    result = {_source_key(value) for value in values}
    if None in result:
        raise ValueError("target evidence contains an invalid source")
    return result


def _answerable(target: Any, row: Mapping[str, Any]) -> bool | None:
    value = row.get("target_unanswerable")
    if value is None:
        value = _target_value(target, "unanswerable")
    if value is None:
        return None
    if type(value) is not bool:
        raise ValueError("target_unanswerable must be a boolean or null")
    return not value


def _candidate_sources(row: Mapping[str, Any]) -> set[str] | None:
    """Extract explicit candidate source identities, never infer from text."""
    values = row.get("candidate_source_ids")
    if values is None:
        values = row.get("candidate_sources")
    if values is None:
        # Selector receipts carry original source IDs for each delivered window.
        values = [
            source.get("original_id", source.get("id"))
            for source in _receipt(row).get("delivered_evidence", [])
            if isinstance(source, Mapping)
        ]
        if not values:
            return None
    if not isinstance(values, (list, tuple, set)):
        raise ValueError("candidate sources must be a sequence")
    result = {_source_key(value) for value in values}
    if None in result:
        raise ValueError("candidate sources contain an invalid identity")
    return result


def _selected_source(row: Mapping[str, Any]) -> str | None:
    direct = row.get("source_id")
    if direct is not None:
        return _source_key(direct)
    selected = row.get("selected")
    candidates = row.get("candidate_source_ids")
    if candidates is None:
        candidates = row.get("candidate_sources")
    if isinstance(selected, int) and isinstance(candidates, (list, tuple)):
        if not 0 <= selected < len(candidates):
            raise ValueError("selected candidate index out of range")
        return _source_key(candidates[selected])
    evidence = _receipt(row).get("delivered_evidence", [])
    if (
        isinstance(selected, int)
        and isinstance(evidence, list)
        and 0 <= selected < len(evidence)
    ):
        source = evidence[selected]
        if isinstance(source, Mapping):
            return _source_key(source.get("original_id", source.get("id")))
    if (
        isinstance(evidence, list)
        and len(evidence) == 1
        and isinstance(evidence[0], Mapping)
    ):
        return _source_key(evidence[0].get("original_id", evidence[0].get("id")))
    return None


def _answer_score(row: Mapping[str, Any]) -> float | None:
    value = row.get("f1")
    if value is None:
        return None
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise ValueError("f1 must be a finite score in [0,1]")
    return float(value)


def _parse_time(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _time_values(row: Mapping[str, Any], question: Mapping[str, Any] | None):
    query_time = row.get("question_time", row.get("query_time"))
    if query_time is None and question is not None:
        query_time = question.get("observed_at")
    evidence = _receipt(row).get("delivered_evidence", [])
    values = []
    if isinstance(evidence, list):
        for source in evidence:
            if isinstance(source, Mapping):
                value = _parse_time(source.get("observed_at"))
                if value is not None:
                    values.append(value)
    return _parse_time(query_time), values


def _citation_issue(row: Mapping[str, Any]) -> bool | None:
    queue = row.get("citation_audit")
    receipt = _receipt(row)
    if queue is None:
        return None
    if not isinstance(queue, Mapping) or not isinstance(receipt, Mapping):
        return True
    request = queue.get("request")
    if not isinstance(request, Mapping):
        return True
    if "answer" in request and request["answer"] != row.get("answer"):
        return True
    if "query_id" in request and request["query_id"] != row.get("question_id"):
        return True
    delivered = receipt.get("delivered_evidence")
    requested = request.get("sources")
    if delivered is not None and requested is not None and requested != delivered:
        return True
    return False


def _failure_stages(
    row: Mapping[str, Any], target: Any, question: Mapping[str, Any] | None
):
    stages: list[str] = []
    answerable = _answerable(target, row)
    score = _answer_score(row) if row.get("status") == "succeeded" else None
    if row.get("status") != "succeeded":
        explicit = row.get("stage")
        stages.append(
            explicit if isinstance(explicit, str) and explicit else "execution_failure"
        )
        if row.get("stage") == "native-history-ingress":
            stages.append("history_ingress")
        return stages, answerable, None, None

    selected = _selected_source(row)
    candidates = _candidate_sources(row)
    support = _target_sources(target)
    if answerable is True:
        if selected is None:
            stages.append("retrieval_or_window")
        elif (
            support
            and candidates is not None
            and not support.intersection(candidates)
        ):
            stages.append("retrieval_or_window")
        elif support and selected not in support:
            stages.append("ranking")
        if row.get("answer", "").strip() == ABSTAIN:
            stages.append("abstention")
        elif score is not None and score < 1.0 and not stages:
            stages.append("generation")
    elif answerable is False and row.get("answer", "").strip() != ABSTAIN:
        stages.append("abstention")

    citation = _citation_issue(row)
    if citation is True:
        stages.append("citation_structure")
    query_time, source_times = _time_values(row, question)
    if query_time is not None and any(value > query_time for value in source_times):
        stages.append("time")
    return stages, answerable, selected, score


def attribute(
    records: Sequence[Mapping[str, Any]],
    targets: Mapping[str, Any],
    *,
    questions: Mapping[str, Mapping[str, Any]] | None = None,
    planned: Sequence[tuple[str, str]] | None = None,
):
    """Return a complete census and structural stage attribution.

    ``planned`` may be supplied to require an exact expected (question, arm)
    census. All input rows are retained in ``records`` including failed attempts,
    empty evidence and unanswerable questions.
    """
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("records must be a sequence")
    seen: set[tuple[str, str]] = set()
    output = []
    counts = {stage: {"eligible": 0, "failures": 0} for stage in STAGES}
    denominators = {
        "planned": len(records),
        "succeeded": 0,
        "failed": 0,
        "answerable": 0,
        "unanswerable": 0,
        "unknown_answerability": 0,
        "empty_evidence": 0,
    }
    expected = set(planned) if planned is not None else None
    if expected is not None and len(expected) != len(planned):
        raise ValueError("duplicate planned census key")
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("record must be an object")
        qid, arm = raw.get("question_id"), raw.get("arm")
        if not isinstance(qid, str) or not qid or not isinstance(arm, str) or not arm:
            raise ValueError("record requires question_id and arm")
        key = (qid, arm)
        if key in seen:
            raise ValueError("duplicate question/arm record")
        seen.add(key)
        if qid not in targets:
            raise ValueError("missing target annotation")
        target = targets[qid]
        status = raw.get("status")
        if status not in ("succeeded", "failed"):
            raise ValueError("unknown execution status")
        question = questions.get(qid) if questions is not None else None
        stages, answerable, selected, score = _failure_stages(raw, target, question)
        if status == "succeeded":
            denominators["succeeded"] += 1
        else:
            denominators["failed"] += 1
        if answerable is True:
            denominators["answerable"] += 1
        elif answerable is False:
            denominators["unanswerable"] += 1
        else:
            denominators["unknown_answerability"] += 1
        receipt = _receipt(raw)
        if not receipt.get("delivered_evidence"):
            denominators["empty_evidence"] += 1
        for stage in stages:
            if stage in counts:
                counts[stage]["failures"] += 1
        query_time, source_times = _time_values(raw, question)
        for stage in STAGES:
            eligible = stage != "time" or (
                query_time is not None and bool(source_times)
            )
            if stage == "citation_structure":
                eligible = raw.get("citation_audit") is not None
            if stage in ("retrieval_or_window", "ranking", "generation"):
                eligible = answerable is True
            if stage == "abstention":
                eligible = answerable is not None
            if eligible:
                counts[stage]["eligible"] += 1
        output.append(
            {
                "question_id": qid,
                "arm": arm,
                "phase": raw.get("phase"),
                "family": raw.get("family"),
                "status": status,
                "answerable": answerable,
                "selected_source": selected,
                "f1": score,
                "failure_stages": stages,
                "negative_history": answerable is False,
            }
        )
    if expected is not None and seen != expected:
        raise ValueError("missing or surplus planned census record")
    for stage in counts:
        counts[stage]["semantic_citation_precision"] = None
    return {
        "schema": SCHEMA,
        "records": output,
        "denominators": denominators,
        "stage_counts": counts,
        "semantic_citation_precision": None,
        "production_accepted": False,
        "superiority_claim": False,
    }


def _read_json(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, (dict, list)):
        raise ValueError("JSON object or array required")
    return value


def _read_jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="JSONL attempt journal")
    parser.add_argument(
        "targets", type=Path, help="JSON mapping question IDs to targets"
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--questions", type=Path)
    args = parser.parse_args()
    targets = _read_json(args.targets)
    if not isinstance(targets, dict):
        raise SystemExit("targets must be a JSON object")
    questions = _read_json(args.questions) if args.questions else None
    if questions is not None and not isinstance(questions, dict):
        raise SystemExit("questions must be a JSON object")
    result = attribute(_read_jsonl(args.records), targets, questions=questions)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
