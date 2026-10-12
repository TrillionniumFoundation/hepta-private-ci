"""Match within-TRAIN Head fitting to held-out frozen-policy source choices.

Read-only *after* every original policy answer, Reader call, and original
scoring record has been saved. Do not train, select, route, threshold, cache,
alter native target labels, or treat weak document support as entailment.
"""

from collections import defaultdict
import math

from native import digest

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")


def train_to_heldout_gap(plan, learning, scored, targets):
    questions = plan["questions"]
    routes = plan["routes"]
    if (
        tuple(plan["arms"]) != ARMS
        or tuple(plan["curriculum_attempted_examples"]) != STAGES
        or tuple(plan["cells"]) != CELLS
        or set(questions) != {"train", *PHASES}
        or len(questions["train"]) != 48
        or any(len(questions[phase]) != 8 for phase in PHASES)
        or len(set(q for group in questions.values() for q in group)) != 80
        or set(routes) != set(q for group in questions.values() for q in group)
        or any(cell not in CELLS for cell in routes.values())
    ):
        raise ValueError("incomplete originally registered Stem curriculum")
    heldout_ids = {qid for phase in PHASES for qid in questions[phase]}
    if not isinstance(targets, dict) or set(targets) != heldout_ids:
        raise ValueError("only original 32 post-policy target bindings allowed")
    target_class = {}
    for qid, target in targets.items():
        if (
            type(target.unanswerable) is not bool
            or not isinstance(target.evidence, (tuple, list))
            or not isinstance(target.unresolved_evidence, (tuple, list))
        ):
            raise ValueError("invalid native answerability/support metadata")
        if target.unanswerable:
            target_class[qid] = "native-unanswerable"
        elif not target.evidence or target.unresolved_evidence:
            target_class[qid] = "native-support-unresolved"
        else:
            target_class[qid] = "answerable-native-document-support"
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in questions[phase]
        for arm in ARMS
    }
    predictions = {}
    for row in scored:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        if key not in expected or key in predictions:
            raise ValueError("duplicate or unregistered scored policy attempt")
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("invalid Reader-policy status")
        predictions[key] = row
    if set(predictions) != expected or len(scored) != 576:
        raise ValueError("all 576 policy rows required without imputation")
    fit = {}
    for row in learning:
        key = row["stage"], row["arm"], row["cell"]
        if (
            key in fit
            or key[0] not in STAGES
            or key[1] not in ARMS
            or key[2] not in CELLS
            or row["status"] not in ("succeeded", "failed")
        ):
            raise ValueError("unexpected or duplicate original Head checkpoint")
        if row["status"] == "succeeded" and row["arm"] != "frozen_rerank":
            dynamics = row.get("within_train_fit_dynamics")
            if (
                not isinstance(dynamics, dict)
                or dynamics["checkpoint"] != row["stage"]
                or dynamics["arm"] != row["arm"]
                or dynamics["cell"] != row["cell"]
                or dynamics["previous_head_sha256"] != row["before_sha256"]
                or dynamics["updated_head_sha256"] != row["after_sha256"]
                or dynamics["heldout_annotations_consulted"] is not False
                or dynamics["independent_generalization_established"] is not False
                or dynamics["production_accepted"] is not False
            ):
                raise ValueError("TRAIN-only measured Head update receipt mismatch")
        fit[key] = row
    if len(fit) != len(STAGES) * len(ARMS) * len(CELLS):
        raise ValueError("missing route/stage/Head training session")

    groups = defaultdict(list)
    for stage in STAGES:
        for phase in PHASES:
            for qid in questions[phase]:
                baseline = predictions[(stage, phase, qid, "frozen_rerank")]
                if baseline.get("cell") != routes[qid]:
                    raise ValueError("baseline route differs from registered Cell")
                for arm in ARMS[1:]:
                    learned = predictions[(stage, phase, qid, arm)]
                    if learned.get("cell") != baseline["cell"] or learned.get(
                        "family"
                    ) != baseline.get("family"):
                        raise ValueError(
                            "matched Cell/source-family changed across arms"
                        )
                    b_selection = "selected" in baseline
                    l_selection = "selected" in learned
                    if (
                        b_selection
                        and l_selection
                        and (
                            baseline.get("pool_digest") != learned.get("pool_digest")
                            or not baseline.get("pool_digest")
                        )
                    ):
                        raise ValueError("paired source candidate pool changed")
                    base_valid = baseline.get("source_choice_correct")
                    learned_valid = learned.get("source_choice_correct")
                    category = target_class[qid]
                    weak_native_source_support = (
                        category == "answerable-native-document-support"
                    )
                    native_scored = (
                        weak_native_source_support
                        and b_selection
                        and l_selection
                        and type(base_valid) is int
                        and base_valid in (0, 1)
                        and type(learned_valid) is int
                        and learned_valid in (0, 1)
                    )
                    abstention_scored = (
                        category == "native-unanswerable"
                        and b_selection
                        and l_selection
                        and type(base_valid) is int
                        and base_valid in (0, 1)
                        and type(learned_valid) is int
                        and learned_valid in (0, 1)
                    )
                    if abstention_scored and (
                        base_valid != int(baseline["selected"] is None)
                        or learned_valid != int(learned["selected"] is None)
                    ):
                        raise ValueError("native abstention label/selection mismatch")
                    good_pair = (
                        baseline["status"] == "succeeded"
                        and learned["status"] == "succeeded"
                    )
                    f1_delta = None
                    if good_pair:
                        b_receipt = baseline.get("receipt")
                        l_receipt = learned.get("receipt")
                        if (
                            not isinstance(b_receipt, dict)
                            or not isinstance(l_receipt, dict)
                            or not b_receipt.get("generator_identity")
                            or not b_receipt.get("generator_profile")
                            or b_receipt["generator_identity"]
                            != l_receipt.get("generator_identity")
                            or b_receipt["generator_profile"]
                            != l_receipt.get("generator_profile")
                            or not isinstance(b_receipt.get("observable_query"), dict)
                            or b_receipt["observable_query"]
                            != l_receipt.get("observable_query")
                            or b_receipt["observable_query"].get("identity") != qid
                        ):
                            raise ValueError(
                                "frozen-matched Reader model/prompt/query identity drift"
                            )
                        original_evidence = b_receipt.get("delivered_evidence")
                        learned_evidence = l_receipt.get("delivered_evidence")
                        if (
                            not isinstance(original_evidence, list)
                            or not isinstance(learned_evidence, list)
                            or len(original_evidence) > 1
                            or len(learned_evidence) > 1
                        ):
                            raise ValueError(
                                "matched Reader source evidence receipt invalid"
                            )
                        if (
                            b_selection
                            and l_selection
                            and baseline["selected"] == learned["selected"]
                            and original_evidence != learned_evidence
                        ):
                            raise ValueError(
                                "unchanged top-1 cannot change actual delivered Reader evidence"
                            )
                        # The exact cache key includes the pinned model, prompt,
                        # original question and delivered source bytes. Neither
                        # a forged cache receipt nor a changed answer to the SAME
                        # immutable request may be counted as model-learning gain.
                        for receipt, evidence in (
                            (b_receipt, original_evidence),
                            (l_receipt, learned_evidence),
                        ):
                            expected_request = digest(
                                (
                                    receipt["generator_identity"],
                                    receipt["generator_profile"],
                                    receipt["observable_query"],
                                    evidence,
                                )
                            )
                            if (
                                receipt.get("canonical_request_digest")
                                != expected_request
                                or receipt.get("question_digest")
                                != digest(receipt["observable_query"])
                                or any(
                                    not isinstance(receipt.get(key), str)
                                    or len(receipt[key]) != 64
                                    or any(
                                        ch not in "0123456789abcdef"
                                        for ch in receipt[key]
                                    )
                                    for key in (
                                        "input_ids_digest",
                                        "generated_ids_digest",
                                    )
                                )
                            ):
                                raise ValueError(
                                    "noncanonical Reader request or token receipt"
                                )
                        identical_request = (
                            b_receipt["canonical_request_digest"]
                            == l_receipt["canonical_request_digest"]
                        )
                        if identical_request and (
                            baseline.get("answer") != learned.get("answer")
                            or b_receipt["input_ids_digest"]
                            != l_receipt["input_ids_digest"]
                            or b_receipt["generated_ids_digest"]
                            != l_receipt["generated_ids_digest"]
                            or baseline.get("diagnostic_answer_f1")
                            != learned.get("diagnostic_answer_f1")
                        ):
                            raise ValueError(
                                "identical Reader request yielded inconsistent "
                                "answer, tokens or post-policy score"
                            )
                        orig_f1 = baseline.get("diagnostic_answer_f1")
                        new_f1 = learned.get("diagnostic_answer_f1")
                        if orig_f1 is not None and new_f1 is not None:
                            if any(
                                type(v) not in (float, int)
                                or not math.isfinite(v)
                                or not 0 <= v <= 1
                                for v in (orig_f1, new_f1)
                            ):
                                raise ValueError("invalid paired Reader token F1")
                            f1_delta = new_f1 - orig_f1
                    if not good_pair:
                        identical_request = None
                    paired_pool_digest = (
                        baseline["pool_digest"] if b_selection and l_selection else None
                    )
                    frozen_request_identity = (
                        (
                            b_receipt["generator_identity"],
                            b_receipt["generator_profile"],
                            digest(b_receipt["observable_query"]),
                        )
                        if good_pair
                        else None
                    )
                    row = dict(
                        stage=stage,
                        phase=phase,
                        arm=arm,
                        cell=routes[qid],
                        question_id=qid,
                        source_family=baseline["family"],
                        both_source_choices_observed=b_selection and l_selection,
                        matched_original_pool_digest=paired_pool_digest,
                        matched_reader_request_identity=frozen_request_identity,
                        identical_canonical_reader_request=identical_request,
                        native_source_label_category=category,
                        native_answerable_source_support=weak_native_source_support,
                        weak_native_source_labels_scored=native_scored,
                        native_abstention_scored=abstention_scored,
                        native_abstention_gain=(
                            learned_valid - base_valid if abstention_scored else None
                        ),
                        changed_top1=(
                            baseline["selected"] != learned["selected"]
                            if b_selection and l_selection
                            else None
                        ),
                        weak_support_gain=(
                            learned_valid - base_valid if native_scored else None
                        ),
                        both_original_reader_calls_succeeded=good_pair,
                        both_reader_answers_scored=f1_delta is not None,
                        diagnostic_answer_f1_delta=f1_delta,
                        semantic_citation_precision=None,
                    )
                    groups[(stage, arm, routes[qid], phase)].append(row)
    reports = {}
    for stage in STAGES:
        for arm in ARMS[1:]:
            for cell in CELLS:
                train = fit[(stage, arm, cell)]
                observed = train["status"] == "succeeded"
                head_probe = train["within_train_fit_dynamics"] if observed else None
                by_phase = {}
                for phase in PHASES:
                    rows = groups[(stage, arm, cell, phase)]
                    known = [
                        r["weak_support_gain"]
                        for r in rows
                        if r["weak_support_gain"] is not None
                    ]
                    abstentions = [
                        r["native_abstention_gain"]
                        for r in rows
                        if r["native_abstention_gain"] is not None
                    ]
                    f1 = [
                        r["diagnostic_answer_f1_delta"]
                        for r in rows
                        if r["diagnostic_answer_f1_delta"] is not None
                    ]
                    n = len(rows)
                    by_phase[phase] = dict(
                        planned=n,
                        source_compared=len(known),
                        source_unresolved_or_unselected=n - len(known),
                        answerable_native_document_support_rows=sum(
                            r["native_answerable_source_support"] for r in rows
                        ),
                        native_unanswerable_rows=sum(
                            r["native_source_label_category"] == "native-unanswerable"
                            for r in rows
                        ),
                        native_support_unresolved_rows=sum(
                            r["native_source_label_category"]
                            == "native-support-unresolved"
                            for r in rows
                        ),
                        observed_native_abstention_pairs=len(abstentions),
                        native_abstention_gains=sum(d == 1 for d in abstentions),
                        native_abstention_regressions=sum(d == -1 for d in abstentions),
                        native_support_gains=sum(delta == 1 for delta in known),
                        native_support_regressions=sum(delta == -1 for delta in known),
                        source_decision_changes=sum(
                            r["changed_top1"] is True for r in rows
                        ),
                        source_choice_not_observed=sum(
                            r["changed_top1"] is None for r in rows
                        ),
                        both_readers_succeeded=sum(
                            r["both_original_reader_calls_succeeded"] for r in rows
                        ),
                        identical_request_pairs=sum(
                            r["identical_canonical_reader_request"] is True
                            for r in rows
                        ),
                        changed_request_pairs=sum(
                            r["identical_canonical_reader_request"] is False
                            for r in rows
                        ),
                        request_identity_unknown_due_to_failure=sum(
                            r["identical_canonical_reader_request"] is None
                            for r in rows
                        ),
                        reader_f1_scored=len(f1),
                        reader_f1_unscored=n - len(f1),
                        paired_reader_f1_delta_mean=(
                            math.fsum(f1) / len(f1) if f1 else None
                        ),
                        all_planned_reader_f1_delta_bounds=(
                            [
                                (math.fsum(f1) - (n - len(f1))) / n,
                                (math.fsum(f1) + (n - len(f1))) / n,
                            ]
                            if n
                            else None
                        ),
                        independent_family_semantics_verified=False,
                    )
                heldout = [by_phase[phase] for phase in ("test", "transfer")]
                heldout_gains = sum(g["native_support_gains"] for g in heldout)
                heldout_regressions = sum(
                    g["native_support_regressions"] for g in heldout
                )
                heldout_source_coverage_complete = (
                    all(
                        g["source_compared"]
                        == g["answerable_native_document_support_rows"]
                        for g in heldout
                    )
                    and sum(g["source_compared"] for g in heldout) > 0
                )
                reports[f"{stage}/{arm}/{cell}"] = dict(
                    head_trained_checkpoint_succeeded=observed,
                    within_head_train_mean_weak_loss_delta=(
                        head_probe["mean_weak_loss_delta"] if head_probe else None
                    ),
                    within_head_train_weak_source_top1_gains=(
                        head_probe.get("weak_source_top1_gains") if head_probe else None
                    ),
                    within_head_train_mean_pair_margin_delta=(
                        head_probe.get(
                            "mean_positive_over_negative_candidate_margin_delta"
                        )
                        if head_probe
                        else None
                    ),
                    heldout_source_comparison_complete=heldout_source_coverage_complete,
                    heldout_answerable_source_scored=sum(
                        g["source_compared"] for g in heldout
                    ),
                    heldout_answerable_source_planned=sum(
                        g["answerable_native_document_support_rows"] for g in heldout
                    ),
                    heldout_test_transfer_native_support_net_gain=(
                        heldout_gains - heldout_regressions
                    ),
                    train_fit_but_no_heldout_native_source_net_gain=(
                        bool(
                            observed
                            and head_probe["mean_weak_loss_delta"] < 0
                            and heldout_gains <= heldout_regressions
                        )
                        if observed and heldout_source_coverage_complete
                        else None
                    ),
                    limited_development_question_count=sum(
                        g["planned"] for g in heldout
                    ),
                    comparison_includes_encoder_adaptation=(
                        arm in ("lineage_lora_gated", "independent_lora_gated")
                    ),
                    encoder_only_vs_head_effects_are_separate_elsewhere=True,
                    test_transfer_source_label_coverage=sum(
                        g["source_compared"] for g in heldout
                    ),
                    phases=by_phase,
                    authentic_independent_generalization=False,
                    source_document_support_not_entailment=True,
                    production_accepted=False,
                )
    # Exactly 16 unique test/transfer questions are repeated at each of
    # three training checkpoints. Preserve paired rows for unit-of-analysis
    # accounting; 48 repeated observations are NOT 48 independent subjects.
    heldout_panel = [
        dict(row)
        for stage in STAGES
        for arm in ARMS[1:]
        for phase in ("test", "transfer")
        for cell in CELLS
        for row in groups[(stage, arm, cell, phase)]
    ]
    if len(heldout_panel) != len(STAGES) * len(ARMS[1:]) * 16:
        raise ValueError("missing registered test/transfer repeated observations")
    # Repeated evaluations at 16/32/48 share the same native questions.
    # Do not count them as 48 independent test/transfer subjects per arm.
    # The final checkpoint is a single descriptive cohort, not a new test.
    final_panel = [row for row in heldout_panel if row["stage"] == STAGES[-1]]
    unique_native_questions = {
        (row["phase"], row["question_id"]) for row in final_panel
    }
    if len(unique_native_questions) != 16:
        raise ValueError("test/transfer effective independent question census drift")
    stage_question_units = {}
    for arm in ARMS[1:]:
        arm_final = [row for row in final_panel if row["arm"] == arm]
        if (
            len(arm_final) != 16
            or {(row["phase"], row["question_id"]) for row in arm_final}
            != unique_native_questions
        ):
            raise ValueError("final checkpoint missing frozen-matched question")
        source = [
            row["weak_support_gain"]
            for row in arm_final
            if row["weak_support_gain"] is not None
        ]
        f1 = [
            row["diagnostic_answer_f1_delta"]
            for row in arm_final
            if row["diagnostic_answer_f1_delta"] is not None
        ]
        missing_source = 16 - len(source)
        missing_f1 = 16 - len(f1)
        stage_question_units[arm] = dict(
            unique_test_transfer_questions=16,
            training_checkpoint_repeats_per_question=len(STAGES),
            observed_source_support_pairs=len(source),
            native_answerability_unknown_or_not_comparable=missing_source,
            native_source_net_gain=sum(source),
            native_source_all_planned_net_gain_bounds=[
                sum(source) - missing_source,
                sum(source) + missing_source,
            ],
            observed_reader_answer_pairs=len(f1),
            unanswered_or_unscored_reader_pairs=missing_f1,
            reader_f1_all_planned_bounds=[
                (math.fsum(f1) - missing_f1) / 16,
                (math.fsum(f1) + missing_f1) / 16,
            ],
            confidence_interval_not_claimed=True,
            independent_source_family_sampling_not_established=True,
        )
    return dict(
        schema="hepta.stem-train-heldout-diagnostic-gap.v5",
        planned_source_policy_rows=len(scored),
        planned_stages=STAGES,
        learned_arms=ARMS[1:],
        posthoc_source_annotations_only=True,
        native_document_support_vs_abstention_separate=True,
        actual_training_predictions_unmodified=True,
        metrics_not_for_hyperparameter_search=True,
        matched_reader_weights_prompt_and_question_required=True,
        canonical_request_and_deterministic_answer_receipt_verified=True,
        train_fit_not_proof_of_generalization=True,
        independent_semantic_evidence_review=False,
        by_checkpoint_cell_arm=reports,
        test_transfer_paired_panel_rows=heldout_panel,
        final_checkpoint_unique_question_units=stage_question_units,
        panel_observations_are_not_independent_subjects=True,
        production_accepted=False,
    )
