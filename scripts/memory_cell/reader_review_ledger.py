"""Fail-closed case-level human Reader review accounting for the research gate.

This verifies structural provenance and aggregate reconciliation, NOT semantic
correctness, human identity or reviewer independence. Those require separately
owner-approved original evidence and independently vetted signing keys.
"""

import re

CONDITIONS = (
    "no_evidence",
    "ordinary_retrieval",
    "human_sufficient",
    "critical_premise_removed",
)
REQUIRED_FIELDS = frozenset(
    (
        "item_id",
        "condition",
        "question_sha256",
        "prompt_input_ids_sha256",
        "raw_answer_sha256",
        "delivered_source_sha256",
        "cited_source_sha256",
        "grounded_and_cited",
        "exact_refusal",
    )
)


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _fingerprints(values):
    return (
        type(values) is list
        and len(values) <= 64
        and all(_sha(x) for x in values)
        and len(set(values)) == len(values)
    )


def audit_case_ledger(cohort, conditions, reviewed_items):
    """Return None only for a complete, internally coherent signed review census.

    Every (item_id, condition) must have ONE signed verdict and hashes for the
    exact prompt, answer and delivered ORIGINAL source identities/bytes. Source
    hashes are attestations, not a substitute for externally pinned raw bytes.
    The claimed four-arm summary is always recomputed from individual verdicts.
    """
    if (
        type(cohort) is not list
        or any(type(q) is not str or not q for q in cohort)
        or len(set(cohort)) != len(cohort)
        or type(conditions) is not dict
        or set(conditions) != set(CONDITIONS)
    ):
        return "invalid-case-ledger-cohort-or-conditions"
    expected = {(qid, condition) for qid in cohort for condition in CONDITIONS}
    if type(reviewed_items) is not list or len(reviewed_items) != len(expected):
        return "missing-or-incomplete-case-review-ledger"
    seen = {}
    questions = {}
    counts = {condition: [0, 0] for condition in CONDITIONS}
    for row in reviewed_items:
        if type(row) is not dict or set(row) != REQUIRED_FIELDS:
            return "invalid-case-review-row-schema"
        qid, condition = row["item_id"], row["condition"]
        if (
            type(qid) is not str
            or type(condition) is not str
            or (qid, condition) not in expected
            or (qid, condition) in seen
        ):
            return "duplicate-or-unregistered-reviewed-case"
        if any(
            not _sha(row[field])
            for field in (
                "question_sha256",
                "prompt_input_ids_sha256",
                "raw_answer_sha256",
            )
        ):
            return "unbound-reviewed-question-prompt-or-answer"
        sources, cited = row["delivered_source_sha256"], row["cited_source_sha256"]
        if not _fingerprints(sources) or not _fingerprints(cited):
            return "invalid-reviewed-source-fingerprints"
        if not set(cited).issubset(set(sources)):
            return "citation-not-bound-to-delivered-source"
        grounded, refusal = row["grounded_and_cited"], row["exact_refusal"]
        if type(grounded) is not bool or type(refusal) is not bool:
            return "invalid-reviewed-verdict-type"
        if grounded and (refusal or not cited):
            return "grounded-verdict-without-valid-source-citation"
        if refusal and cited:
            return "exact-refusal-with-citations"
        if condition == "no_evidence" and (sources or cited or grounded):
            return "no-evidence-condition-delivered-source"
        if condition == "human_sufficient" and not sources:
            return "sufficient-evidence-condition-is-empty"
        if condition == "critical_premise_removed" and grounded:
            return "removed-premise-was-scored-as-grounded"
        qhash = row["question_sha256"]
        if qid in questions and questions[qid] != qhash:
            return "question-identity-changed-across-review-conditions"
        questions[qid] = qhash
        seen[qid, condition] = row
        counts[condition][0] += int(grounded)
        counts[condition][1] += int(refusal)
    if set(seen) != expected:
        return "missing-or-duplicated-case-review"
    for qid in cohort:
        full = set(seen[qid, "human_sufficient"]["delivered_source_sha256"])
        removed = set(seen[qid, "critical_premise_removed"]["delivered_source_sha256"])
        # A premise-removal intervention must ONLY remove previously
        # delivered evidence; introducing or replacing sources confounds
        # both refusal and grounded-answer comparisons.
        if not removed < full:
            return "critical-premise-not-actually-removed"
    for condition in CONDITIONS:
        claimed = conditions[condition]
        if (
            type(claimed) is not dict
            or claimed.get("grounded_and_cited") != counts[condition][0]
            or claimed.get("exact_refusal") != counts[condition][1]
        ):
            return "review-ledger-aggregate-disagrees-with-signed-cases"
    return None
