"""Read-only original-output echo/citation-budget diagnostic (DENY_ALL).

An exact source/weight replay must be completed separately before this result
is treated as a verified original model observation. Strings copied from the
prompt are warning flags, not semantic correctness or plagiarism judgments.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import re
import sys

import associative_graph_causal as graph
import reader_premise_format as premise

SCHEMA = "hepta.reader-premise-echo-diagnostic.v1"
MARKER = re.compile(r"\[E([1-8])\]")


def characterize(row, result):
    """Describe the *unchanged* response: never rewrite or attach citations."""
    if not isinstance(row, dict) or not isinstance(result, dict):
        raise ValueError("expected original source plan and frozen model result")
    status = result.get("status")
    if status not in ("succeeded", "failed", "unavailable"):
        raise ValueError("unknown original model status")
    answer = result.get("answer")
    if status != "succeeded":
        if answer is not None:
            raise ValueError("failed result cannot manufacture model answer")
        return {"status": status}
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("missing actual model output")
    inputs = row["evidence"]
    labels = {f"E{i}" for i in range(1, len(inputs) + 1)}
    emitted = [f"E{i}" for i in MARKER.findall(answer)]
    head = answer.strip().lower()
    # These lexical flags are *diagnostics* only. A quoted source may also be
    # a valid answer, so neither flag is counted as an incorrect answer.
    looks_like_json_prompt = head.startswith(('{"question"', "{'question'"))
    repeated_question = len(row["question"]) >= 12 and row["question"].lower() in head
    source_prefix = any(
        len(item["text"]) >= 16 and head.startswith(item["text"][:16].lower())
        for item in inputs
    )
    budget = result.get("generated_tokens")
    n_input = result.get("input_tokens")
    if (
        type(n_input) is not int
        or not 1 <= n_input <= 8192
        or type(budget) is not int
        or not 1 <= budget <= premise.MAX_TOKENS
    ):
        raise ValueError("missing bounded actual token accounting")
    return {
        "status": status,
        "input_tokens": n_input,
        "generated_tokens": budget,
        "hit_generation_ceiling": budget == premise.MAX_TOKENS,
        "json_prompt_echo_shape": looks_like_json_prompt,
        "exact_question_repeated": repeated_question,
        "starts_with_evidence_source": source_prefix,
        "any_citation_marker": bool(emitted),
        "invalid_citation_marker": any(label not in labels for label in emitted),
        "all_emitted_markers_delivered": bool(emitted)
        and all(label in labels for label in emitted),
    }


def audit(plan_dir, run_dir, report_path):
    plan, plan_seal = premise._read_plan(plan_dir)
    records, seal = premise._read_journal(plan, plan_seal, run_dir)
    if seal["journal_sha256"] != graph.digest(
        graph.regular_bytes(Path(run_dir) / "reader.json")
    ):
        raise ValueError("changed original journal bytes")
    mapping = {(e["question_id"], e["arm"]): e for e in plan["entries"]}
    counts = {arm: Counter() for arm in premise.ARMS}
    for item in records:
        arm = item["arm"]
        row = mapping[(item["question_id"], arm)]
        profile = characterize(row, item["result"])
        stats = counts[arm]
        stats["planned"] += 1
        stats[profile["status"]] += 1
        if profile["status"] != "succeeded":
            continue
        for field in (
            "input_tokens",
            "generated_tokens",
            "hit_generation_ceiling",
            "json_prompt_echo_shape",
            "exact_question_repeated",
            "starts_with_evidence_source",
            "any_citation_marker",
            "invalid_citation_marker",
            "all_emitted_markers_delivered",
        ):
            stats[field] += int(profile[field])
    if any(c["planned"] != premise.Q_COUNT for c in counts.values()):
        raise ValueError("original 40-call cohort was filtered")
    result = {
        "schema": SCHEMA,
        "original_plan_sha256": plan_seal["plan_sha256"],
        "original_journal_sha256": seal["journal_sha256"],
        "planned": premise.PLANNED,
        "by_arm": {arm: dict(counts[arm]) for arm in premise.ARMS},
        "lexical_echo_is_not_independent_semantic_error": True,
        "citation_marker_is_not_entailment": True,
        "requires_separate_actual_model_replay": True,
        "production_accepted": False,
        "statistical_superiority": False,
    }
    graph.create_only(report_path, result)
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 4 or argv[0] != "audit":
        raise SystemExit("audit SEALED_PLAN SEALED_READER_RUN NEW_ECHO_REPORT")
    print(json.dumps(audit(*argv[1:]), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
