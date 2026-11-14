"""Post-seal citation grounding and blinded adjudication for real Reader outputs.

SHADOW_ONLY / DENY_ALL. Checks literal spans and label delivery, not semantic
entailment. Independently judged semantic support is intentionally NULL until
external qualified adjudicators actually produce authenticated findings.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

import associative_graph_causal as graph

SCHEMA = "hepta.reader-grounding-postseal.shadow.v1"
MARKER = re.compile(r"\[E([0-9]{1,3})\]")
QUOTED = re.compile(r'["“]([^"”\r\n]{16,240})["”]')
WORDS = re.compile(r"[A-Za-z0-9]+")
LITERAL_QUOTE_MIN_TOKENS = 3
MAX_ANSWER_BYTES = 16384
MAX_WORKLIST_BYTES = 512 * 1024


def _exact_whitespace(text):
    # Collapse only Unicode whitespace, not spelling/case/punctuation.
    return " ".join(unicodedata.normalize("NFC", text).split())


def _validate_evidence(evidence):
    if not isinstance(evidence, list) or len(evidence) > 8:
        raise ValueError("invalid delivered evidence list")
    seen = set()
    for i, e in enumerate(evidence, 1):
        if (not isinstance(e, dict)
                or set(e) != {"label", "source_id", "text"}
                or e["label"] != f"E{i}"
                or not isinstance(e["source_id"], str)
                or not re.fullmatch(r"D\d+:\d+", e["source_id"])
                or not isinstance(e["text"], str)
                or not 0 < len(e["text"].encode("utf-8")) <= 1500
                or e["source_id"] in seen):
            raise ValueError("unbound, duplicate, or incorrectly scoped source")
        seen.add(e["source_id"])


def inspect_answer(answer, evidence):
    """Perform conservative structural checks without judging semantic truth.

    A matching literal quotation establishes only that *those bytes* appeared in
    the actually supplied excerpt, not that the rest of the answer is entailed.
    """
    _validate_evidence(evidence)
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode("utf-8")) > MAX_ANSWER_BYTES:
        raise ValueError("bounded unchanged nonempty model output required")
    by_label = {e["label"]: e for e in evidence}
    found = [(m.group(0), "E" + m.group(1), m.start(), m.end()) for m in MARKER.finditer(answer)]
    valid = [label for _token, label, _start, _end in found if label in by_label]
    invalid = [label for _token, label, _start, _end in found if label not in by_label]
    # A label appearing *inside* a quoted string may be a transcription, not a citation.
    quotes = list(QUOTED.finditer(answer))
    quoted_tokens = [q for q in quotes if len(WORDS.findall(q.group(1))) >= LITERAL_QUOTE_MIN_TOKENS]
    echo_markers = sum(any(q.start() <= start < q.end() for q in quotes)
                       for _token, _label, start, _end in found)
    spans = []
    for q in quoted_tokens:
        # Associate only immediately neighboring labels: no free-form sentence
        # similarity, cherry-picked source from a different citation or model.
        neighbors = [label for _token, label, start, end in found
                     if (0 <= start - q.end() <= 16 or 0 <= q.start() - end <= 16)
                     and label in by_label]
        observed_sources = []
        for label in neighbors:
            if _exact_whitespace(q.group(1)) in _exact_whitespace(by_label[label]["text"]):
                observed_sources.append(by_label[label]["source_id"])
        spans.append({
            "quoted_span_sha256": hashlib.sha256(q.group(1).encode("utf-8")).hexdigest(),
            "adjacent_delivered_citation_count": len(neighbors),
            "verbatim_in_adjacent_delivered_source": bool(observed_sources),
            "matching_source_ids": sorted(set(observed_sources)),
        })
    # 'strict_full_quote' only describes the narrow textual form and byte match.
    # It does NOT certify semantic entailment, real-world truth, or the claim scope.
    strict_full_quote = False
    if len(spans) == 1 and spans[0]["verbatim_in_adjacent_delivered_source"]:
        full = re.fullmatch(r'\s*["“][^"”\r\n]{16,240}["”]\s*\[E([1-8])\]\s*[.!]?\s*', answer)
        strict_full_quote = full is not None and "E" + full.group(1) in by_label
    return {
        "emitted_citation_count": len(found),
        "valid_delivered_citation_count": len(valid),
        "out_of_scope_or_malformed_citation_count": len(invalid),
        "possible_citation_text_echo_count": echo_markers,
        "unlabeled_answer": not found,
        "all_emitted_citations_delivered": bool(found) and not invalid,
        "quote_citation_pair_count": sum(s["adjacent_delivered_citation_count"] > 0 for s in spans),
        "quoted_spans_checked": len(spans),
        "verbatim_quote_pairs_with_presented_source": sum(
            s["verbatim_in_adjacent_delivered_source"] for s in spans),
        "strict_whole_output_is_cited_literal_quote": strict_full_quote,
        "spans": spans,
        "complete_answer_semantic_entailment": None,
        "independent_semantic_verdict": None,
    }


def _validate_receipt(receipt, plan_seal, journal_seal):
    if (not isinstance(receipt, dict)
            or receipt.get("schema") != "hepta.reader-citation-grammar.shadow.v1"
            or receipt.get("plan_sha256") != plan_seal["sha256"]
            or receipt.get("original_reader_sha256") != journal_seal["journal_sha256"]
            or receipt.get("replayed_model_calls") != 40
            or receipt.get("planned") != 40
            or receipt.get("production_accepted") is not False
            or receipt.get("citation_labels_are_not_semantic_entailment") is not True):
        raise ValueError("no verified exact-plan original Reader replay receipt")


def audit(plan_dir, original_reader_run, completed_replay_receipt, output_dir):
    """Consumes only sealed source snapshots and already-replayed original answers.

    No publisher answer/gold annotations, model weights or model invocation here.
    The receipt is an exact SHA accounting link, NOT an independent signature.
    """
    import reader_citation_protocol as source

    plan, plan_seal = source._read_plan(plan_dir)
    rows, seal = source._read_journal(plan, plan_seal, original_reader_run)
    receipt = graph.strict_load(graph.regular_bytes(completed_replay_receipt))
    _validate_receipt(receipt, plan_seal, seal)
    by_input = {(x["question_id"], x["arm"]): x for x in plan["rows"]}
    counts = {arm: Counter() for arm in source.ARMS}
    case_ids = set()
    details = []
    blinded = []
    for row in rows:
        key = (row["question_id"], row["arm"])
        src = by_input[key]
        stats = counts[row["arm"]]
        stats["planned"] += 1
        status = row["result"]["status"]
        stats[status] += 1
        if status != "succeeded":
            # Failures remain in the original 40-case denominator.
            continue
        output = row["result"]["answer"]
        findings = inspect_answer(output, src["evidence"])
        for name in ("emitted_citation_count", "valid_delivered_citation_count",
                     "out_of_scope_or_malformed_citation_count",
                     "possible_citation_text_echo_count", "quoted_spans_checked",
                     "verbatim_quote_pairs_with_presented_source", "quote_citation_pair_count"):
            stats[name] += findings[name]
        for name in ("unlabeled_answer", "all_emitted_citations_delivered",
                     "strict_whole_output_is_cited_literal_quote"):
            stats[name] += int(findings[name])
        commitment = graph.canonical({
            "question_id": src["question_id"],
            "arm": src["arm"],
            "answer": output,
            "evidence": src["evidence"],
            "source_plan_sha256": plan_seal["sha256"],
            "journal_sha256": seal["journal_sha256"],
        })
        case_id = hashlib.sha256(b"hepta.blinded-adjudication.v1\0" + commitment).hexdigest()
        if case_id in case_ids:
            raise ValueError("duplicate source/answer adjudication identity")
        case_ids.add(case_id)
        details.append({
            "case_id": case_id,
            "family": src["family"],
            "question_id": src["question_id"],
            "arm": src["arm"],
            "answer_sha256": graph.digest(output.encode("utf-8")),
            "source_excerpt_identity_sha256": graph.digest(graph.canonical(src["evidence"])),
            "mechanical": findings,
        })
        blinded.append({
            "case_id": case_id,
            "question": src["question"],
            "unchanged_answer": output,
            "delivered_evidence": src["evidence"],
            "independent_support_judgment": None,
            "independent_citation_entailment_judgment": None,
            "status": "awaiting_external_adjudication",
        })
    if (len(rows) != 40 or len(case_ids) != sum(counts[a]["succeeded"] for a in source.ARMS)
            or any(counts[a]["planned"] != 10 for a in source.ARMS)):
        raise ValueError("original complete 40-call grounding audit census missing")
    # Deterministic, stable but arm-blinded order. This is not secure blinding
    # against an evaluator with the original question/answer journal.
    blinded.sort(key=lambda x: x["case_id"])
    report = {
        "schema": SCHEMA,
        "source_plan_sha256": plan_seal["sha256"],
        "model_journal_sha256": seal["journal_sha256"],
        "postseal_reader_replay_receipt_sha256": graph.digest(
            graph.regular_bytes(completed_replay_receipt)),
        "planned": 40,
        "source_groups": 10,
        "succeeded_for_blinded_review": len(blinded),
        "by_arm": {arm: dict(counts[arm]) for arm in source.ARMS},
        "per_response": details,
        "verbatim_quote_checks_are_not_semantic_entailment": True,
        "external_independent_reviewer_count": 0,
        "semantic_answer_correctness": None,
        "citation_entailment_precision": None,
        "statistical_superiority": False,
        "full_lifecycle_TCO_measured": False,
        "source_authority_granted": False,
        "final_use_authorized": False,
        "production_accepted": False,
    }
    worklist = {
        "schema": SCHEMA,
        "source_plan_sha256": plan_seal["sha256"],
        "model_journal_sha256": seal["journal_sha256"],
        "cases": blinded,
        "original_gold_answers_present": False,
        "no_independent_verdicts_fabricated": True,
        "production_accepted": False,
    }
    target = Path(output_dir)
    target.mkdir(exist_ok=False)
    graph.create_only(target / "grounding-report.json", report)
    raw = graph.canonical(worklist)
    if len(raw) > MAX_WORKLIST_BYTES:
        raise ValueError("bounded blinded evaluator worklist exceeded")
    graph.create_only(target / "blinded-worklist.json", worklist)
    return {"schema": SCHEMA, "planned": 40,
            "grounding_report_sha256": graph.digest(graph.canonical(report)),
            "blinded_worklist_sha256": graph.digest(raw),
            "semantic_entailment_completed": False,
            "production_accepted": False}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 5 or args[0] != "audit":
        raise SystemExit("audit EXACT_PLAN ORIGINAL_READER_RUN COMPLETED_REPLAY_RECEIPT NEW_OUTPUT_DIR")
    print(json.dumps(audit(args[1], args[2], args[3], args[4]), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
