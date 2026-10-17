"""Post-answer weak native source-coverage ceiling on preregistered questions.

Native document-level support is NOT reviewed window-level entailment. Gold
annotations are accessed only after every answer is emitted; no policy,
retrieval, Reader prompt, training, or calibration depends on this module.
"""

from collections import defaultdict

from sessions import source_id

PHASES = ("select", "retention", "test", "transfer")


def retrospective_pool_ceiling(
    phase_questions, pools, targets, source_families, scored_policies, *, final_stage=48
):
    registered = {
        (phase, q.identity): q for phase in PHASES for q in phase_questions[phase]
    }
    all_ids = [q.identity for phase in PHASES for q in phase_questions[phase]]
    if (
        any(len(phase_questions[phase]) != 8 for phase in PHASES)
        or len(all_ids) != 32
        or len(set(all_ids)) != 32
        or len(registered) != 32
        or set(all_ids) != set(targets)
        or set(all_ids) != set(source_families)
    ):
        raise ValueError("unregistered retrospective 32-question cohort")
    frozen = {}
    for row in scored_policies:
        if row["stage"] != final_stage or row["arm"] != "frozen_rerank":
            continue
        key = row["phase"], row["question_id"]
        if key not in registered or key in frozen:
            raise ValueError("duplicate or unregistered frozen comparator")
        frozen[key] = row
    if set(frozen) != set(registered):
        raise ValueError("missing fixed-ranker retrospective outcome")
    by_phase = defaultdict(list)
    for key, q in registered.items():
        phase, qid = key
        t, f = targets[qid], frozen[key]
        if f["family"] != source_families[qid] or f["status"] not in (
            "succeeded",
            "failed",
        ):
            raise ValueError("family or status differs from registered policy")
        pool = pools.get(qid)
        supported_indices = ()
        if pool is not None:
            if any(w.scope != q.scope for w in pool.windows):
                raise ValueError("cross-scope candidate pool in retrospective audit")
            source_ids = {source_id(x) for x in t.evidence}
            supported_indices = tuple(
                i
                for i, w in enumerate(pool.windows)
                if source_id(w.source_id) in source_ids
            )
        valid = not t.unanswerable and bool(t.evidence) and not t.unresolved_evidence
        selected = f.get("selected")
        if selected is not None and (
            pool is None
            or type(selected) is not int
            or not 0 <= selected < len(pool.windows)
        ):
            raise ValueError("selected candidate detached from fixed pool")
        if (
            f["status"] == "succeeded"
            and pool is not None
            and pool.windows
            and selected is None
        ):
            raise ValueError("successful frozen policy omitted forced-top1 selection")
        if "pool_digest" in f and pool is not None and f["pool_digest"] != pool.seal():
            raise ValueError("fixed candidate pool was rewritten after answering")
        possible = bool(supported_indices) if valid and pool is not None else None
        picked = (
            selected in supported_indices
            if valid and selected is not None and pool is not None
            else None
        )
        row = dict(
            phase=phase,
            question_id=qid,
            source_family=source_families[qid],
            native_source_unanswerable=bool(t.unanswerable),
            unresolved_native_support=bool(t.unresolved_evidence),
            weak_native_support_resolved=valid,
            candidate_pool_available=pool is not None,
            candidate_count=None if pool is None else len(pool.windows),
            weak_support_window_count=(
                len(supported_indices) if valid and pool is not None else None
            ),
            native_support_available_in_pool=possible,
            frozen_selected_native_support=picked,
            frozen_failed_before_selection=selected is None,
            frozen_reader_execution_succeeded=f["status"] == "succeeded",
            missed_native_support_within_pool=(
                bool(possible and picked is False) if picked is not None else None
            ),
            source_content_or_gold_answers_exported=False,
            native_weak_support_not_window_entailment=True,
            independently_reviewed_source_sufficiency=False,
        )
        by_phase[phase].append(row)
    summary = {}
    for phase in PHASES:
        group = by_phase[phase]
        if len(group) != 8:
            raise ValueError("retrospective phase denominator changed")
        resolved = [r for r in group if r["weak_native_support_resolved"]]
        with_pool = [r for r in resolved if r["candidate_pool_available"]]
        summary[phase] = dict(
            attempted=len(group),
            native_source_resolved=len(resolved),
            native_unanswerable=sum(r["native_source_unanswerable"] for r in group),
            native_unresolved_support=sum(
                r["unresolved_native_support"] for r in group
            ),
            candidate_pool_missing=sum(
                not r["candidate_pool_available"] for r in group
            ),
            support_available_within_pool=sum(
                r["native_support_available_in_pool"] is True for r in group
            ),
            support_missing_from_pool=sum(
                r["native_support_available_in_pool"] is False for r in with_pool
            ),
            frozen_correct_source_choices=sum(
                r["frozen_selected_native_support"] is True for r in group
            ),
            frozen_missed_available_support=sum(
                r["missed_native_support_within_pool"] is True for r in group
            ),
            frozen_not_chosen_or_unobserved=sum(
                r["frozen_selected_native_support"] is None for r in group
            ),
            frozen_reader_failed=sum(
                not r["frozen_reader_execution_succeeded"] for r in group
            ),
            diagnostic_only_weak_source_evidence=True,
            independently_adjudicated_semantic_entailment=False,
        )
    return dict(
        schema="hepta.stem-post-policy-native-source-ceiling.v1",
        after_all_policy_answers=True,
        final_checkpoint=final_stage,
        fixed_reader_or_index_changed=False,
        independent_semantic_review_performed=False,
        phases=summary,
        decisions=[r for phase in PHASES for r in by_phase[phase]],
        prospective_window_qualified=False,
        production_accepted=False,
    )
