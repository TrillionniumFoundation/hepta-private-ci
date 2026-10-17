"""Research-only publisher-source citation accounting after a sealed Reader run.

A syntactically delivered source address is not human semantic entailment.
Never consume publisher evidence labels in an inference or retrieval worker.
"""
from __future__ import annotations

from collections import defaultdict
import re

import memory_reader_causal_panel as base

SCHEMA = "hepta.memory-reader-original-source-citation-audit.research.v1"
CANONICAL_CITATION = re.compile(r"\[E([1-9][0-9]*)\]")
POSSIBLE_CITATION = re.compile(r"\[E[^\]\n]*\]")
SOURCE_ID = re.compile(r"D[0-9]+:[0-9]+\Z")


def publisher_sources(originals, plan):
    """Read original publisher evidence *only* in the postseal reviewer."""
    if not isinstance(originals, dict) or not isinstance(plan, dict):
        raise ValueError("publisher/original plan unavailable")
    annotated = {}
    for request in plan["requests"]:
        qid, family = request["question_id"], request["family"]
        if family not in originals or not qid.startswith(family + "/q"):
            raise ValueError("publisher family/question mismatch")
        qa = originals[family]["qa"][int(qid.rsplit("q", 1)[1])]
        evidence = qa.get("evidence")
        if isinstance(evidence, list) and evidence and all(
            isinstance(v, str) and SOURCE_ID.fullmatch(v) for v in evidence
        ):
            value = frozenset(evidence)
        else:
            value = None
        if qid in annotated and annotated[qid] != value:
            raise ValueError("publisher evidence inconsistent across repeated arms")
        annotated[qid] = value
    return annotated


def audit(plan, rows, original_sources):
    """Numbered citations -> delivered source IDs -> publisher evidence addresses.

    Only counts original answer bytes already checked by model's sealed record
    validator. Caller MUST first validate full original corpus, exact plan,
    complete model output, tokenizer and before-effect evidence.
    """
    if (not isinstance(plan, dict) or not isinstance(rows, list)
        or len(rows) != len(plan.get("requests", []))
        or len(rows) != 120 or not isinstance(original_sources, dict)):
        raise ValueError("original source citation population unbound")
    metrics = defaultdict(lambda: dict(
        planned=0, original_publisher_evidence_available=0,
        original_publisher_evidence_complete_in_delivery=0,
        original_publisher_evidence_any_in_delivery=0,
        model_succeeded=0, model_citation_emitting=0,
        citation_markers=0, canonical_in_range_citation_markers=0,
        invalid_or_foreign_citation_markers=0,
        in_range_markers_on_publisher_evidence=0,
        in_range_markers_off_publisher_evidence=0,
        in_range_markers_when_publisher_evidence_unknown=0))
    for request, row in zip(plan["requests"], rows, strict=True):
        arm = request["arm"]
        if (arm not in base.ARMS or row["request_id"] != request["request_id"]
            or row["status"] not in ("succeeded", "unavailable", "failed")):
            raise ValueError("question/arm/Reader record identity drift")
        seen = metrics[arm]
        seen["planned"] += 1
        published = original_sources.get(request["question_id"])
        if request["question_id"] not in original_sources:
            raise ValueError("missing publisher annotation")
        delivered = [e["source_id"] for e in request["evidence"]]
        if len(delivered) != len(set(delivered)):
            raise ValueError("duplicate delivered source evidence")
        if published is not None:
            if not isinstance(published, frozenset):
                raise ValueError("publisher evidence malformed")
            seen["original_publisher_evidence_available"] += 1
            seen["original_publisher_evidence_complete_in_delivery"] += int(
                published <= set(delivered))
            seen["original_publisher_evidence_any_in_delivery"] += int(
                bool(published & set(delivered)))
        if row["status"] != "succeeded":
            if row["answer"] is not None:
                raise ValueError("unavailable/failed Reader answer forged")
            continue
        answer = row["answer"]
        if not isinstance(answer, str):
            raise ValueError("missing original Reader answer")
        seen["model_succeeded"] += 1
        tags = POSSIBLE_CITATION.findall(answer)
        seen["model_citation_emitting"] += int(bool(tags))
        for tag in tags:
            seen["citation_markers"] += 1
            match = CANONICAL_CITATION.fullmatch(tag)
            if match is None:
                seen["invalid_or_foreign_citation_markers"] += 1
                continue
            slot = int(match.group(1))
            if not 1 <= slot <= len(delivered):
                seen["invalid_or_foreign_citation_markers"] += 1
                continue
            seen["canonical_in_range_citation_markers"] += 1
            if published is None:
                seen["in_range_markers_when_publisher_evidence_unknown"] += 1
            elif delivered[slot-1] in published:
                seen["in_range_markers_on_publisher_evidence"] += 1
            else:
                seen["in_range_markers_off_publisher_evidence"] += 1
    output = {}
    for arm in base.ARMS:
        item = dict(metrics[arm])
        if item["planned"] != plan["planned_questions"]:
            raise ValueError("missing citation audit arm")
        denom = item["in_range_markers_on_publisher_evidence"] + item[
            "in_range_markers_off_publisher_evidence"]
        item["publisher_address_agreement_among_known_in_range_citations"] = (
            item["in_range_markers_on_publisher_evidence"] / denom if denom else None)
        output[arm] = item
    return {
        "schema": SCHEMA, "by_arm": output, "human_semantic_entailment_verified": False,
        "publisher_labels_human_sufficiency_certified": False,
        "citation_precision_when_none_emitted_is_null": True,
        "production_accepted": False,
    }
