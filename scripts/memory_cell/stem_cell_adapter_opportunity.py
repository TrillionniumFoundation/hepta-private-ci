"""Source-only census of LoRA pair opportunities along the Head curriculum.

Inputs are the registered, admitted TRAIN Supervision rows after feature
construction. No held-out annotations, inference, gradient updates, policy
tuning, or future-source admission change is performed here.
"""

from native import digest


STAGES = (16, 32, 48)
CELLS = ("general", "temporal")
ADAPTERS = ("lineage", "independent-general", "independent-temporal")


def eligible_pairs_by_stage(train_questions, rows, routes, adapter_receipts=None):
    registered = tuple(q.identity for q in train_questions)
    if (
        len(registered) != 48
        or len(set(registered)) != 48
        or set(routes) != set(registered)
        or any(routes[q] not in CELLS for q in registered)
        or (adapter_receipts is not None and set(adapter_receipts) != set(ADAPTERS))
    ):
        raise ValueError("incomplete registered TRAIN curriculum/Cell/Adapter binding")
    admitted = {}
    for row in rows:
        f = row.features
        qid = f.question_id
        n = len(f.candidate_ids)
        positive = row.positive_indices
        if (
            qid not in routes
            or qid in admitted
            or not isinstance(f.family, str)
            or not f.family
            or not 0 <= n <= 64
            or len(set(f.candidate_ids)) != n
            or len(set(positive)) != len(positive)
            or any(type(i) is not int or i < 0 or i >= n for i in positive)
        ):
            raise ValueError("duplicate, unregistered or invalid admitted training row")
        admitted[qid] = (bool(positive) and len(positive) < n, f.family)
    if not admitted or len(admitted) > 48:
        raise ValueError("no bounded admitted training cohort")
    results = {}
    for stage in STAGES:
        prefix = registered[:stage]
        stage_admitted = {q for q in prefix if q in admitted}
        pair_eligible = {q for q in stage_admitted if admitted[q][0]}
        by_cell = {}
        for cell in CELLS:
            attempted = {q for q in prefix if routes[q] == cell}
            seen = stage_admitted & attempted
            fit = pair_eligible & attempted
            by_cell[cell] = dict(
                attempted=len(attempted),
                admitted_weak_source_questions=len(seen),
                positive_negative_pair_eligible_questions=len(fit),
                admitted_but_pair_ineligible=len(seen - fit),
                unadmitted_training_questions=len(attempted - seen),
                eligible_source_families=len({admitted[q][1] for q in fit}),
            )
        results[str(stage)] = dict(
            attempted_questions=len(prefix),
            admitted_weak_source_questions=len(stage_admitted),
            positive_negative_pair_eligible_questions=len(pair_eligible),
            admitted_but_pair_ineligible=len(stage_admitted - pair_eligible),
            unadmitted_training_questions=len(prefix) - len(stage_admitted),
            eligible_source_families=len({admitted[q][1] for q in pair_eligible}),
            cells=by_cell,
        )
    warm = {q for q in registered[:16] if q in admitted and admitted[q][0]}
    if adapter_receipts is not None:
        lineage = adapter_receipts["lineage"]
        if set(lineage["prepared_questions"]) != warm:
            raise ValueError(
                "lineage actual warm start differs from registered pair eligibility"
            )
        for cell in CELLS:
            selected = {q for q in warm if routes[q] == cell}
            if (
                set(adapter_receipts["independent-" + cell]["prepared_questions"])
                != selected
            ):
                raise ValueError(
                    "independent LoRA warm start used wrong Cell questions"
                )
    return dict(
        schema="hepta.stem-pair-opportunity-census.v1",
        registered_train_count=48,
        observed_admitted_unique_count=len(admitted),
        actual_adapter_warm_pair_count=len(warm),
        adapter_warm_receipt_verified=adapter_receipts is not None,
        adapter_updated_after_warm_start=False,
        checkpoint_prefixes=results,
        train_cohort_order_sha256=digest(registered),
        label_source="native-document-support-not-independent-entailment",
        unseen_task_gain_measured_here=False,
        future_calendar_window_qualification=False,
        production_accepted=False,
    )
