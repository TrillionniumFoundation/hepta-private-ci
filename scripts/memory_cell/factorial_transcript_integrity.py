#!/usr/bin/env python3
"""Bind MemoryCell factorial claims to original delivered bytes and raw answers.

This is a deterministic, read-only audit of externally produced transcripts.
It neither calls a model nor authenticates a claimed model call, reviewer, or
real-world source; source/model trust needs independent evidence.
"""

import argparse
import hashlib
from pathlib import Path

from factorial_evidence_gate import (
    ARMS,
    CONDITIONS,
    READERS,
    analyze,
    canonical,
    load,
    require,
    sha,
)


def text_sha(value):
    require(isinstance(value, str), "original UTF-8 text required")
    return hashlib.sha256(value.encode("utf-8", "strict")).hexdigest()


def hex64(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_sources(value, admitted):
    require(
        isinstance(value, list) and len(value) <= 32,
        "bounded ordered evidence required",
    )
    seen = set()
    for item in value:
        require(
            isinstance(item, dict) and set(item) == {"id", "text"},
            "original source shape",
        )
        identity, content = item["id"], item["text"]
        require(
            isinstance(identity, str)
            and 1 <= len(identity) <= 256
            and identity not in seen
            and isinstance(content, str)
            and len(content.encode("utf-8", "strict")) <= 16384
            and "\x00" not in content,
            "invalid, duplicated, or oversized source",
        )
        seen.add(identity)
        require(
            admitted.get(identity) == text_sha(content),
            "unregistered source bytes",
        )
    return sha(value)


def validate_case_sources(case):
    admitted = case.get("admitted_evidence")
    require(
        isinstance(admitted, list) and 1 <= len(admitted) <= 64,
        "frozen evidence catalogue required",
    )
    result = {}
    for entry in admitted:
        require(
            isinstance(entry, dict)
            and set(entry) == {"id", "sha256"}
            and isinstance(entry["id"], str)
            and 1 <= len(entry["id"]) <= 256
            and entry["id"] not in result
            and hex64(entry["sha256"]),
            "invalid frozen evidence identity",
        )
        result[entry["id"]] = entry["sha256"]
    require(
        hex64(case.get("question_sha256")),
        "frozen question byte pin required",
    )
    return result


def audit(plan, observations, transcripts):
    """Require an exact, byte-matched complete factorial transcript census.

    Raw textual evidence is never promoted to authorization; the source
    catalogue only commits to what may be delivered. Hash matches are necessary
    but not sufficient to prove semantic completeness or trust.
    """
    result = analyze(plan, observations)
    require(isinstance(transcripts, list), "original transcript list required")
    cases = {case["id"]: case for case in plan["cases"]}
    admitted = {cid: validate_case_sources(case) for cid, case in cases.items()}
    expected = {
        (cid, arm, condition, reader)
        for cid in cases
        for arm in ARMS
        for condition in CONDITIONS
        for reader in READERS
    }
    by_row = {(r["id"], r["arm"], r["condition"], r["reader"]): r for r in observations}
    traced = {}
    for record in transcripts:
        require(isinstance(record, dict), "original transcript entry required")
        key = tuple(record.get(name) for name in ("id", "arm", "condition", "reader"))
        require(
            key in expected and key not in traced,
            "unexpected or duplicate raw transcript",
        )
        cid, arm, condition, reader = key
        row = by_row[key]
        case = cases[cid]
        require(
            text_sha(record.get("question")) == case["question_sha256"],
            "question bytes changed after preregistration",
        )
        require(
            text_sha(record.get("raw_answer")) == row["answer_digest"],
            "raw answer and scored claim diverged",
        )
        require(
            text_sha(record.get("prompt_template")) == row["prompt_digest"],
            "prompt-template bytes not bound to observation",
        )
        require(
            record.get("reader_revision") == row["reader_revision"],
            "reader revision not bound to raw transcript",
        )
        evidence = record.get("delivered_evidence")
        require(
            validate_sources(evidence, admitted[cid]) == row["source_digest"],
            "delivered source text differs from scored claim",
        )
        if condition == "none" or arm == "knowledge_only":
            require(
                not evidence,
                "no-evidence / parametric-only arm received source text",
            )
        traced[key] = record
    require(set(traced) == expected, "incomplete original transcript matrix")
    lesions = 0
    for cid, case in cases.items():

        def context(arm, condition, reader):
            return traced[(cid, arm, condition, reader)]["delivered_evidence"]

        original = context("hybrid_rag", "oracle", "frozen")
        require(
            sha(original) == case["oracle_source_sha256"],
            "oracle bytes differ from frozen plan",
        )
        premise = [
            source
            for source in original
            if text_sha(source["text"]) == case["premise_sha256"]
        ]
        require(
            len(premise) == 1,
            "oracle lacks one unique frozen prerequisite",
        )
        remaining = [source for source in original if source["id"] != premise[0]["id"]]
        for reader in READERS:
            for arm in ARMS:
                if arm != "knowledge_only":
                    require(
                        context(arm, "oracle", reader) == original,
                        "oracle differs by arm or reader",
                    )
                    require(
                        context(arm, "ablated", reader) == remaining,
                        "ablation must remove exactly the frozen prerequisite",
                    )
            require(
                not context("knowledge_only", "hybrid", reader),
                "knowledge-only received raw evidence",
            )
        lesions += 1
    return {
        "schema": "hepta.memory-factorial.transcript-integrity.v1",
        "plan_sha256": sha(plan),
        "transcript_count": len(transcripts),
        "oracle_and_exact_lesion_case_count": lesions,
        "all_original_answers_and_sources_byte_bound": True,
        "source_authenticity_independently_verified": False,
        "model_execution_independently_attested": False,
        "human_semantic_sufficiency_certified": False,
        "human_premise_necessity_certified": False,
        "independent_task_success_adjudicated": False,
        "parameter_learning_qualified": False,
        "production_accepted": False,
        "diagnostic_disposition": result["four_stage_disposition"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(
        load(args.plan),
        load(args.observations),
        load(args.transcripts),
    )
    require(not args.output.exists(), "cannot overwrite original audit")
    args.output.write_bytes(canonical(report) + b"\n")


if __name__ == "__main__":
    main()
