"""Research accounting; targets are consumed only after policy outputs are sealed."""

from collections import defaultdict
import json
import math
import os
import re

from selector_evaluation import correctness, diagnose
from sessions import source_id

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
CURVE = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def append(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def validate_census(attempts, plan):
    expected = {
        (stage, phase, qid, arm)
        for stage in CURVE
        for phase in PHASES
        for qid in plan["questions"][phase]
        for arm in ARMS
    }
    actual = [(r["stage"], r["phase"], r["question_id"], r["arm"]) for r in attempts]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("missing, duplicate or extra policy attempt")
    for row in attempts:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown policy execution status")
        if row["family"] != plan["question_families"][row["question_id"]]:
            raise ValueError("policy source-family drift")
    return dict(planned=len(expected), recorded=len(actual), complete=True)


def oracle_sources(source, query, target):
    """Privileged reference-SPAN diagnostic, not an accepted gold-evidence oracle.

    Native supporting source plus literal reference-answer text is not independent
    entailment adjudication. The answer-dependent window is deliberately labelled
    privileged and cannot be compared as an ordinary retrieval policy. No answer
    annotation is inserted into source text; missing spans stay unavailable.
    """
    if target.unanswerable:
        return (), "annotated-unanswerable"
    if target.unresolved_evidence or not target.answer or not target.evidence:
        return None, "unresolved-reference"
    supported = {source_id(s) for s in target.evidence}
    for doc in sorted(source.history(query), key=lambda d: d.identity):
        if (
            source_id(doc.identity) not in supported
            or doc.observed_at > query.observed_at
        ):
            continue
        match = re.search(re.escape(target.answer), doc.content, re.IGNORECASE)
        if match is None or match.end() - match.start() > 512:
            continue
        start = max(0, match.start() - 192)
        end = min(len(doc.content), match.end() + 192)
        # All other MemoryCell source positions refer to original UTF-8 bytes.
        byte_start = len(doc.content[:start].encode("utf-8"))
        byte_end = len(doc.content[:end].encode("utf-8"))
        evidence = dict(
            label="E1",
            id=doc.identity,
            original_id=doc.identity,
            root=doc.root,
            scope=doc.scope,
            excerpt=doc.content[start:end],
            source_start=byte_start,
            source_end=byte_end,
            observed_at=doc.observed_at,
            offset_encoding="original-utf8-bytes",
        )
        return (evidence,), "native-source-literal-span"
    return None, "no-admitted-literal-reference-span"


def score_attempt(item, pool, target):
    result = dict(item)
    # Reader failure must not erase an already observed correct selector choice.
    result["source_choice_correct"] = (
        correctness(pool, target, item["selected"]) if "selected" in item else 0
    )
    if item["status"] == "succeeded":
        result["diagnostic_answer_f1"] = diagnose(item["answer"], target)
        labels = re.findall(r"\[E(\d+)\]", item["answer"])
        delivered = {s["label"] for s in item["receipt"]["delivered_evidence"]}
        valid = sum("E" + label in delivered for label in labels)
        result["citation_structure"] = dict(
            markers=len(labels),
            delivered_markers=valid,
            precision=None if not labels else valid / len(labels),
            semantic_precision=None,
        )
    else:
        result.update(
            diagnostic_answer_f1=0.0,
            citation_structure=dict(
                markers=0, delivered_markers=0, precision=None, semantic_precision=None
            ),
        )
    return result


def summarize(attempts):
    grouped = defaultdict(list)
    for row in attempts:
        grouped[(row["stage"], row["phase"], row["arm"])].append(row)
    reports = {}
    for key, rows in sorted(grouped.items()):
        valid_source = [
            r["source_choice_correct"]
            for r in rows
            if r["source_choice_correct"] is not None
        ]
        valid_f1 = [
            r["diagnostic_answer_f1"]
            for r in rows
            if r["diagnostic_answer_f1"] is not None
        ]
        latencies = sorted(r["head_seconds"] for r in rows if "head_seconds" in r)
        markers = sum(r["citation_structure"]["markers"] for r in rows)
        delivered = sum(r["citation_structure"]["delivered_markers"] for r in rows)
        reports["/".join(map(str, key))] = dict(
            attempted=len(rows),
            succeeded=sum(r["status"] == "succeeded" for r in rows),
            failed=sum(r["status"] != "succeeded" for r in rows),
            source_scored=len(valid_source),
            source_unresolved=len(rows) - len(valid_source),
            source_accuracy=None
            if not valid_source
            else sum(valid_source) / len(valid_source),
            source_all_planned_bounds=[
                sum(valid_source) / len(rows),
                (sum(valid_source) + len(rows) - len(valid_source)) / len(rows),
            ],
            answer_scored=len(valid_f1),
            answer_unscored=len(rows) - len(valid_f1),
            diagnostic_f1=None if not valid_f1 else sum(valid_f1) / len(valid_f1),
            answer_all_planned_bounds=[
                sum(valid_f1) / len(rows),
                (sum(valid_f1) + len(rows) - len(valid_f1)) / len(rows),
            ],
            head_p95_seconds=(
                None
                if not latencies
                else latencies[math.ceil(0.95 * len(latencies)) - 1]
            ),
            emitted_citation_markers=markers,
            delivered_citation_markers=delivered,
            citation_structural_precision=None if not markers else delivered / markers,
            semantic_citation_precision=None,
        )
    contrasts = {}
    comparisons = len(CURVE) * len(PHASES) * (len(ARMS) - 1)
    for (stage, phase, arm), rows in sorted(grouped.items()):
        if arm == ARMS[0]:
            continue
        base = {r["question_id"]: r for r in grouped[(stage, phase, ARMS[0])]}
        if set(base) != {r["question_id"] for r in rows}:
            raise ValueError("incomplete paired experimental census")
        families = defaultdict(list)
        for r in rows:
            b = base[r["question_id"]]
            if r["family"] != b["family"]:
                raise ValueError("paired source-family drift")
            candidate, baseline = r["source_choice_correct"], b["source_choice_correct"]
            low = (0 if candidate is None else candidate) - (
                1 if baseline is None else baseline
            )
            high = (1 if candidate is None else candidate) - (
                0 if baseline is None else baseline
            )
            families[r["family"]].append((low, high))
        lows = [sum(v[0] for v in group) / len(group) for group in families.values()]
        highs = [sum(v[1] for v in group) / len(group) for group in families.values()]
        low, high = sum(lows) / len(lows), sum(highs) / len(highs)
        radius = math.sqrt(2 * math.log(2 * comparisons / 0.05) / len(families))
        contrasts[f"{stage}/{phase}/{arm}"] = dict(
            family_count=len(families),
            mean_source_delta=low if low == high else None,
            all_planned_family_delta_bounds=[low, high],
            simultaneous_conditional_95_interval=[
                max(-1.0, low - radius),
                min(1.0, high + radius),
            ],
            family_independence_authenticated=False,
            superiority_claim=False,
        )
    return dict(metrics=reports, contrasts=contrasts)
