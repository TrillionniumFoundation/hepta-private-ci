"""Pinned post-retrieval literal-answer accessibility on public LoCoMo.

The two frozen policies must be fixed and sealed BEFORE evaluation labels are
opened. Exact answer-string occurrence is a narrow lexical diagnostic, neither
semantic support nor independent source/citation adjudication. No model runs.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import unicodedata

from locomo_ninearm_source_replay import (
    ZIPS, canonical, read_zip, sha, strict_json,
)

ARMS = ("lexical_k4", "lexical_k8")
PLANNED = 16


def normalized_literal(text, *, byte_limit=8192):
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > byte_limit:
        raise ValueError("missing or unbounded published literal answer")
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def literal_occurs(answer, content):
    """Literal boundary-aware match, NOT a proof of question entailment."""
    if not isinstance(content, str) or len(content.encode("utf-8")) > 1048576:
        raise ValueError("unbounded source document for literal-only diagnostic")
    if not content.strip():
        return False
    needle, haystack = normalized_literal(answer), normalized_literal(
        content, byte_limit=1048576
    )
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def sealed_candidates(cases, documents, decisions):
    if (
        not isinstance(cases, list) or len(cases) != PLANNED
        or len({q["question_id"] for q in cases}) != PLANNED
        or len({q["family_proxy_digest"] for q in cases}) != 2
        or not isinstance(documents, dict)
    ):
        raise ValueError("nonoriginal LoCoMo evaluation/source family census")
    expected = {(q["question_id"], arm) for q in cases for arm in ARMS}
    subset = {k: v for k, v in decisions.items() if k in expected}
    if set(subset) != expected:
        raise ValueError("missing original frozen k4/k8 selections")
    plan = []
    for case in cases:
        qid, scope = case["question_id"], case["scope"]
        source_ids = case["source_ids"]
        if (
            not isinstance(source_ids, list) or len(source_ids) < 8
            or len(source_ids) != len(set(source_ids))
            or any(s not in documents or documents[s]["scope"] != scope
                   for s in source_ids)
        ):
            raise ValueError("invalid source census or cross-scope original")
        selected = []
        for arm, k in (("lexical_k4", 4), ("lexical_k8", 8)):
            row = subset[(qid, arm)]
            source_keys = row["selected"]
            if (
                row["arm"] != arm or row["question_id"] != qid
                or row["family_proxy_digest"] != case["family_proxy_digest"]
                or row["source_census_sha256"] != case["source_census_sha256"]
                or not isinstance(source_keys, list)
                or len(source_keys) != k or len(set(source_keys)) != k
                or not set(source_keys).issubset(source_ids)
                or row["selected_source_bytes"] != sum(
                    len(documents[s]["content"].encode("utf-8")) for s in source_keys
                )
            ):
                raise ValueError("reordered, mutated or unpinned original source selections")
            selected.append(source_keys)
        if selected[0] != selected[1][:4]:
            raise ValueError("k4 was not the original prefix of frozen k8")
        plan.append(dict(
            question_id=qid,
            family_proxy_digest=case["family_proxy_digest"],
            source_census_sha256=case["source_census_sha256"],
            scope=scope,
            source_ids=source_ids,
            lexical_k4=selected[0],
            lexical_k8=selected[1],
        ))
    return dict(
        schema="hepta.locomo-literal-postreplay-prelabel-lock.v1",
        original_public_zip_sha256=ZIPS["public"][1],
        original_decisions_zip_sha256=ZIPS["decisions"][1],
        source_only_record_count=PLANNED,
        arms=list(ARMS),
        label_bytes_read_before_seal=False,
        original_frozen_ranking_or_source_bytes_changed=False,
        source_selection_sha256=sha(canonical(plan)),
        cases=plan,
    )


def audit_locked_literal_capacity(lock, documents, targets):
    cases = lock["cases"]
    if (
        lock.get("schema") != "hepta.locomo-literal-postreplay-prelabel-lock.v1"
        or lock.get("label_bytes_read_before_seal") is not False
        or lock.get("original_frozen_ranking_or_source_bytes_changed") is not False
        or len(cases) != PLANNED or len({x["question_id"] for x in cases}) != PLANNED
        or lock.get("source_selection_sha256") != sha(canonical(cases))
        or not isinstance(targets, dict)
        or set(targets) != {q["question_id"] for q in cases}
    ):
        raise ValueError("target data opened without a sealed 16-question source plan")
    rows = []
    totals = {arm: defaultdict(int) for arm in ARMS}
    for case in cases:
        target = targets[case["question_id"]]
        if (
            type(target.get("unanswerable")) is not bool
            or not isinstance(target.get("support"), list)
            or not isinstance(target.get("unresolved_support"), list)
            or any(not isinstance(x, str) or not x
                   for x in target["support"] + target["unresolved_support"])
        ):
            raise ValueError("unregistered published source support")
        support = target["support"]
        outside = not set(support).issubset(case["source_ids"])
        answerable = (
            not target["unanswerable"] and bool(support)
            and not target["unresolved_support"] and not outside
        )
        answer = target.get("answer")
        literal_available = (
            answerable and isinstance(answer, str) and bool(answer.strip())
            and len(answer.encode("utf-8")) <= 8192
        )
        source_literal_found = (
            any(literal_occurs(answer, documents[s]["content"])
                for s in case["source_ids"]) if literal_available else None
        )
        for arm in ARMS:
            selected = case[arm]
            contains_all_support = (
                set(support).issubset(selected) if answerable else None
            )
            selected_literal = (
                any(literal_occurs(answer, documents[s]["content"]) for s in selected)
                if literal_available else None
            )
            support_literal = (
                any(literal_occurs(answer, documents[s]["content"])
                    for s in selected if s in support)
                if literal_available else None
            )
            row = dict(
                question_id=case["question_id"], arm=arm,
                family_proxy_digest=case["family_proxy_digest"],
                weak_document_support_evaluable=answerable,
                weak_full_document_support_selected=contains_all_support,
                literal_answer_comparable=literal_available,
                literal_answer_in_original_source_pool=source_literal_found,
                literal_answer_in_selected_source_text=selected_literal,
                literal_answer_in_selected_annotated_support=support_literal,
                native_unanswerable=target["unanswerable"],
                native_support_unresolved_or_outside_pool=(
                    not target["unanswerable"] and not answerable
                ),
                original_answer_text_exported=False,
                source_byte_values_exported=False,
                entailment_independently_judged=False,
            )
            rows.append(row)
            t = totals[arm]
            t["planned"] += 1
            t["native_unanswerable"] += row["native_unanswerable"]
            t["weak_document_support_evaluable"] += answerable
            t["full_weak_source_covered"] += contains_all_support is True
            t["literal_answer_comparable"] += literal_available
            t["literal_in_original_pool"] += source_literal_found is True
            t["literal_in_selected_sources"] += selected_literal is True
            t["literal_in_selected_annotated_support"] += support_literal is True
            t["literal_missing_from_source_pool"] += source_literal_found is False
    for arm in ARMS:
        if totals[arm]["planned"] != PLANNED:
            raise ValueError("missing frozen literal contrast cases")
    return dict(
        schema="hepta.locomo-frozen-source-literal-accessibility.v1",
        original_source_plan_sha256=lock["source_selection_sha256"],
        original_public_zip_sha256=lock["original_public_zip_sha256"],
        original_decisions_zip_sha256=lock["original_decisions_zip_sha256"],
        evaluation_target_zip_sha256=ZIPS["evaluation"][1],
        preregistered_evaluation_questions=PLANNED,
        original_lexical_k4_prefix_of_lexical_k8=True,
        per_arm={a: dict(totals[a]) for a in ARMS},
        rows=rows,
        literal_match_is_only_lower_bound_on_answer_surface_availability=True,
        answer_literal_missing_does_not_prove_semantic_absence=True,
        literal_presence_not_evidence_entailment=True,
        selected_original_source_bytes_not_verified_reader_prompt_tokens=True,
        actual_reader_prompt_delivery_not_measured_here=True,
        independent_source_family_qualification=False,
        reader_executions=0,
        learned_parameter_updates=0,
        raw_answers_exported=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--public-zips", type=Path, required=True)
    p.add_argument("--evaluation-zips", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    # Critical sequence: seal and persist all source-only choices before
    # opening a single native answer annotation.
    from locomo_frozen_reader_pair import source_plan, write_once
    cases, documents, decisions = source_plan(args.public_zips)
    sealed = sealed_candidates(cases, documents, decisions)
    args.output.mkdir(parents=True, exist_ok=False)
    write_once(args.output / "prelabel-source-plan.json", canonical(sealed) + b"\n")
    target_bytes = read_zip(args.evaluation_zips, "evaluation")["targets.json"]
    targets = strict_json(target_bytes)
    result = audit_locked_literal_capacity(sealed, documents, targets)
    result["original_pinned_target_bytes_sha256"] = sha(target_bytes)
    write_once(args.output / "report.json", canonical(result) + b"\n")
    print(json.dumps(
        {key: result[key] for key in ("schema", "per_arm", "production_accepted")},
        sort_keys=True, ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
