"""Research accounting; targets are consumed only after policy outputs are sealed."""

from collections import defaultdict
import json
import math
import os
import re

from selector_evaluation import correctness, diagnose
from sessions import source_id

ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")
CURVE = (16, 32, 48)


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


def oracle_sources(source, query, target):
    """Privileged diagnostic only; never use this to select/train policy arms.

    A native supporting source plus literal reference-answer span is not an
    independently adjudicated entailment label. Missing spans stay unavailable;
    no answer annotation is ever inserted into the source text.
    """
    if target.unanswerable:
        return (), "annotated-unanswerable"
    if target.unresolved_evidence or not target.answer or not target.evidence:
        return None, "unresolved-reference"
    supported = {source_id(s) for s in target.evidence}
    for doc in sorted(source.history(query), key=lambda d: d.identity):
        if source_id(doc.identity) not in supported or doc.observed_at > query.observed_at:
            continue
        match = re.search(re.escape(target.answer), doc.content, re.IGNORECASE)
        if match is None or match.end() - match.start() > 512:
            continue
        start, end = max(0, match.start() - 192), min(len(doc.content), match.end() + 192)
        return (dict(label="E1", id=doc.identity, original_id=doc.identity,
                     root=doc.root, scope=doc.scope, excerpt=doc.content[start:end],
                     source_start=start, source_end=end, observed_at=doc.observed_at),), "native-source-literal-span"
    return None, "no-admitted-literal-reference-span"


def score_attempt(item, pool, target):
    result = dict(item)
    if item["status"] == "succeeded":
        result["source_choice_correct"] = correctness(pool, target, item["selected"])
        result["diagnostic_answer_f1"] = diagnose(item["answer"], target)
        labels = re.findall(r"\[E(\d+)\]", item["answer"])
        delivered = {s["label"] for s in item["receipt"]["delivered_evidence"]}
        valid = sum("E" + label in delivered for label in labels)
        result["citation_structure"] = dict(
            markers=len(labels), delivered_markers=valid,
            precision=None if not labels else valid / len(labels),
            semantic_precision=None,
        )
    else:
        # Failures remain zero in unconditional scores, not silently discarded.
        result.update(source_choice_correct=0, diagnostic_answer_f1=0.0,
                      citation_structure=dict(markers=0, delivered_markers=0,
                                              precision=None, semantic_precision=None))
    return result


def summarize(attempts):
    grouped = defaultdict(list)
    for row in attempts:
        grouped[(row["stage"], row["phase"], row["arm"])].append(row)
    reports = {}
    for key, rows in sorted(grouped.items()):
        valid_source = [r["source_choice_correct"] for r in rows
                        if r["source_choice_correct"] is not None]
        valid_f1 = [r["diagnostic_answer_f1"] for r in rows
                    if r["diagnostic_answer_f1"] is not None]
        latencies = sorted(r["head_seconds"] for r in rows if "head_seconds" in r)
        markers = sum(r["citation_structure"]["markers"] for r in rows)
        delivered = sum(r["citation_structure"]["delivered_markers"] for r in rows)
        reports["/".join(map(str, key))] = dict(
            attempted=len(rows), succeeded=sum(r["status"] == "succeeded" for r in rows),
            failed=sum(r["status"] != "succeeded" for r in rows),
            source_scored=len(valid_source), source_unresolved=len(rows) - len(valid_source),
            source_accuracy=None if not valid_source else sum(valid_source) / len(valid_source),
            answer_scored=len(valid_f1), answer_unscored=len(rows) - len(valid_f1),
            diagnostic_f1=None if not valid_f1 else sum(valid_f1) / len(valid_f1),
            head_p95_seconds=None if not latencies else latencies[math.ceil(.95 * len(latencies)) - 1],
            emitted_citation_markers=markers, delivered_citation_markers=delivered,
            citation_structural_precision=None if not markers else delivered / markers,
            semantic_citation_precision=None,
        )
    # Family clusters, not question rows or execution shards, set the interval size.
    contrasts = {}
    comparisons = max(1, len(CURVE) * 4 * (len(ARMS) - 1))
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
            if r["source_choice_correct"] is not None and b["source_choice_correct"] is not None:
                families[r["family"]].append(r["source_choice_correct"] - b["source_choice_correct"])
        means = [sum(v) / len(v) for v in families.values()]
        mean = None if not means else sum(means) / len(means)
        radius = None if not means else math.sqrt(2 * math.log(2 * comparisons / .05) / len(means))
        contrasts[f"{stage}/{phase}/{arm}"] = dict(
            family_count=len(means), mean_source_delta=mean,
            simultaneous_conditional_95_interval=None if mean is None else
                [max(-1.0, mean - radius), min(1.0, mean + radius)],
            family_independence_authenticated=False,
            superiority_claim=False,
        )
    return dict(metrics=reports, contrasts=contrasts)
