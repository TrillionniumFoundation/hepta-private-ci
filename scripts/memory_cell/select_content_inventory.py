"""A separately registered SELECT donor inventory, not a repaired old result.

Only SELECT annotations may supply donors. Recipient questions are EXACTLY the
saved budget study's SELECT generation questions. Same-partition, cross-family,
equal-source-count and distinct-body rules are reused unchanged. No model score,
TRAIN/TEST target, nearest-length search or fallback donor is used. This remains
exposed development data, not independent semantic or prospective confirmation.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

import five_causal_experiments as c
import reader_content_swap as control
import source_time_evidence as metadata

PROFILE = "hepta.reader.select-donor-inventory.v1"
MAX_QUERIES = 4096
MAX_RECIPIENTS = 32


def source_partitions(benchmark):
    """Inspect partition/provenance metadata without touching any target."""
    c.require(0 < len(benchmark.questions) <= 20000, "bounded benchmark questions required")
    questions, scopes, families = {}, {}, {}
    for q in benchmark.questions:
        part = benchmark.partition(q)
        family = benchmark.families[q.family]
        c.require(part in ("train", "select", "test") and c.text_id(family)
                  and isinstance(q.identity, str) and q.identity and q.identity not in questions,
                  "invalid question/partition identity")
        c.require(scopes.setdefault(q.scope, part) == part, "source scope crosses partitions")
        c.require(families.setdefault(family, part) == part, "family crosses partitions")
        questions[q.identity] = (q, part, family)
    roots, ids = {}, set()
    documents = {}
    for d in benchmark.documents:
        c.require(d.scope in scopes and d.identity not in ids, "unbound or duplicate source identity")
        ids.add(d.identity)
        part = scopes[d.scope]
        c.require(roots.setdefault(d.root, part) == part, "source root crosses partitions")
        documents.setdefault(d.scope, []).append(d)
    c.require(all(q.scope in documents for q, _, _ in questions.values()), "question has no source history")
    return questions, documents, {"families": families, "roots": roots}


def collect_inventory(benchmark):
    """Census ALL SELECT questions before eligibility; reject, never replace.

    Ineligible weak annotations remain in the ledger. Length qualification is
    later, AFTER identity-based pairing, and cannot choose an easier donor.
    """
    questions, documents, provenance = source_partitions(benchmark)
    candidates = sorted((q for q, p, _ in questions.values() if p == "select"),
                        key=lambda q: c.digest(q.identity))
    c.require(0 < len(candidates) <= MAX_QUERIES, "bounded nonempty SELECT inventory required")
    records, census = [], []
    for q in candidates:
        # This is deliberately the only target lookup: q is already SELECT.
        target = benchmark.targets[q.identity]
        history = documents[q.scope]
        known = {d.identity: d for d in history}
        evidence = tuple(dict.fromkeys(target.evidence))
        reason = None
        if target.answer is None or target.unanswerable:
            reason = "missing_or_unanswerable_annotation"
        elif not isinstance(target.answer, str) or not target.answer.strip() or len(target.answer.encode()) > 8192:
            reason = "invalid_answer_body"
        elif not evidence or len(evidence) > 3 or target.unresolved_evidence or any(x not in known for x in evidence):
            reason = "missing_unresolved_or_out_of_bound_support"
        record = None
        if reason is None:
            selected = [known[x] for x in evidence]
            public = {"question": q.content, "options": [], "evidence": [
                {"id": metadata.source_id(d.identity), "modality": "text", "text": d.content,
                 "asset_sha256": None, "position": i} for i, d in enumerate(selected)]}
            try:
                c.validate_public(public)
                projected, receipt = metadata.project(public, history, metadata.SOURCE_TIME)
                record = {"question_id": c.digest(q.identity), "family": questions[q.identity][2],
                          "split": "select", "request": projected, "answer_body": target.answer.strip()}
                c.validate_public(projected)
            except (ValueError, TypeError, KeyError) as error:
                reason = "source_projection_invalid:" + str(error)[:256]
        if reason is None:
            records.append(record)
        census.append({"original_question_id": q.identity, "question_id": c.digest(q.identity),
                       "family": questions[q.identity][2], "split": "select", "eligible": reason is None,
                       "reason": reason, "support_count": len(evidence), "replacement_selected": False})
    c.require(len({r["question_id"] for r in census}) == len(census), "question digest collision")
    source_identity = [{"id": d.identity, "root": d.root, "scope": d.scope,
                        "session": d.session, "observed_at": d.observed_at,
                        "content_sha256": c.digest(d.content)}
                       for qscope in sorted(documents) if provenance_scope(qscope, questions) == "select"
                       for d in documents[qscope]]
    ledger = {"profile": PROFILE, "selected_before_eligibility": len(census), "eligible": len(records),
              "reasons": dict(Counter(r["reason"] for r in census if not r["eligible"])),
              "rows": census, "pool_sha256": c.digest(records),
              "source_inventory_sha256": c.digest(source_identity),
              "excluded_families": sorted(f for f, p in provenance["families"].items() if p != "select"),
              "source_partition_metadata_sha256": c.digest(provenance),
              "target_partitions_accessed": ["select"], "training_updates": 0,
              "independent_confirmation": False, "incompatibility_reviewed": False}
    return records, ledger


def provenance_scope(scope, questions):
    return next(p for q, p, _ in questions.values() if q.scope == scope)


def build_plan(benchmark, previous_cases):
    """Return fixed recipients, new inventory, and target-free generation cases."""
    c.require(isinstance(previous_cases, list) and previous_cases, "saved public input census required")
    before = c.digest(previous_cases)
    questions, _, _ = source_partitions(benchmark)
    kept = []
    for row in previous_cases:
        c.require(isinstance(row, dict) and set(row) == {"question_id", "family", "split", "condition", "request"},
                  "saved case fields changed")
        qid = row["question_id"]
        c.require(qid in questions and row["split"] == questions[qid][1]
                  and row["family"] == questions[qid][2] and row["split"] in ("train", "select"),
                  "saved recipient partition differs from original source")
        if row["split"] == "select" and row["condition"] in ("support_only", "no_evidence"):
            kept.append(deepcopy(row))
    recipient_ids = sorted({x["question_id"] for x in kept})
    c.require(0 < len(recipient_ids) <= MAX_RECIPIENTS, "bounded fixed SELECT recipient census required")
    pool, ledger = collect_inventory(benchmark)
    # Use the actual old comparator, rather than a looser new pairing predicate.
    all_comparisons = control.build_comparisons(pool) if pool else []
    available = {x["question_id"]: x for x in all_comparisons}
    recipients = []
    by_id = {x["question_id"]: x for x in ledger["rows"]}
    for qid in recipient_ids:
        key = c.digest(qid)
        c.require(key in by_id, "fixed recipient missing from full SELECT census")
        comparison = available.get(key)
        status = ("unavailable_recipient_annotation" if comparison is None else comparison["status"])
        recipients.append({"original_question_id": qid, "question_id": key,
                           "family": questions[qid][2], "split": "select", "status": status,
                           "annotation_reason": by_id[key]["reason"],
                           "donor_question_id": None if comparison is None else comparison["donor_question_id"]})
    keys = {c.digest(qid) for qid in recipient_ids}
    comparisons = [x for x in all_comparisons if x["question_id"] in keys]
    cases = control.generation_plan(kept, comparisons)
    c.require(c.digest(previous_cases) == before, "saved public inputs mutated")
    c.require(len(cases) == 3 * len(recipient_ids), "recipient condition denominator changed")
    coverage = {"planned_recipients": len(recipients),
                "reference_bearing_recipients": len(comparisons),
                "paired_recipients": sum(x["status"] == "available" for x in comparisons),
                "missing_recipient_annotations": sum(x["status"] == "unavailable_recipient_annotation" for x in recipients),
                "donor_reuse_independent": False, "token_qualification_completed": False,
                "old_study_missingness_unchanged": True}
    return {"profile": PROFILE, "pool": pool, "inventory": ledger,
            "recipients": recipients, "comparisons": comparisons, "public_cases": cases,
            "saved_public_input_sha256": before, "coverage": coverage,
            "complete_public_cases_sha256": c.digest(cases), "production_accepted": False}


def readiness(plan, compiled_ids):
    """Avoid paying model costs when the NEW required comparisons are absent."""
    expected = {x["question_id"] for x in plan["comparisons"]}
    paired = {x["question_id"] for x in plan["comparisons"] if x["status"] == "available"}
    compiled = set(compiled_ids)
    c.require(compiled <= expected, "unregistered compiled recipient")
    return {"reference_bearing_recipients": len(expected), "paired_recipients": len(paired),
            "compiled_recipients": len(compiled), "all_reference_bearing_ready": bool(expected) and expected == paired == compiled,
            "all_planned_recipients_reference_bearing": len(expected) == len(plan["recipients"]),
            "missing_or_uncompiled_ids": sorted(expected - compiled),
            "qualification_is_coverage_only": True, "reader_adequacy_established": False}


def paired_readout(by_arm, baseline="frozen_reader"):
    """Descriptive, same-recipient differences; never donor-iid confidence bars."""
    c.require(baseline in by_arm and by_arm[baseline], "baseline audit census required")
    lookup = {}
    for arm, rows in by_arm.items():
        c.require(len({r["question_id"] for r in rows}) == len(rows), "duplicate audit recipient")
        lookup[arm] = {r["question_id"]: r for r in rows}
    keys = set(lookup[baseline])
    c.require(all(set(rows) == keys for rows in lookup.values()), "unequal paired audit denominators")
    comparisons = []
    for arm in sorted(lookup):
        if arm == baseline:
            continue
        deltas, missing = {}, []
        for key in sorted(keys):
            a, b = lookup[arm][key], lookup[baseline][key]
            c.require(a["family"] == b["family"] and a["donor_question_id"] == b["donor_question_id"],
                      "different donor or recipient across model arms")
            if a["status"] != "succeeded" or b["status"] != "succeeded":
                missing.append(key)
                continue
            values = [x["audit"]["difference_in_differences"] for x in (a, b)]
            c.require(all(c.finite(v, -1e9, 1e9) for v in values), "nonfinite interaction")
            deltas.setdefault(a["family"], []).append(values[0] - values[1])
        flat = [x for xs in deltas.values() for x in xs]
        comparisons.append({"candidate": arm, "baseline": baseline, "planned_recipients": len(keys),
            "jointly_scored": len(flat), "missing_or_failed_ids": missing,
            "mean_delta": sum(flat)/len(flat) if flat else None,
            "family_macro_delta": sum(sum(xs)/len(xs) for xs in deltas.values())/len(deltas) if deltas else None,
            "positive_deltas": sum(x > 0 for x in flat), "negative_deltas": sum(x < 0 for x in flat),
            "means_conditional_on_joint_success": True, "confidence_interval": None,
            "independent_confirmation": False, "semantic_accuracy": None})
    return comparisons
