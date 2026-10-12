"""Read-only refusal-to-promote gate on native Stem results.

An all-success CI status is operational evidence, not transferable learning.
Require actual matched source/answer outcomes and independently judged citation
support before a scaling claim. Never turn missing reviewer evidence into zero.
"""

from collections import defaultdict
import math

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)


def audit_nonpromotion(report):
    metrics = report["metrics"]
    expected = {
        f"{stage}/{phase}/{arm}" for stage in STAGES for phase in PHASES for arm in ARMS
    }
    if set(metrics) != expected or report.get("logical_policy_attempts") != 576:
        raise ValueError("incomplete or modified original 576-policy census")
    if report.get("production_accepted") is not False:
        raise ValueError("unqualified native run promoted itself")
    by_arm = defaultdict(
        lambda: dict(
            compared_phase_checkpoints=0,
            identical_source_accuracy=0,
            identical_answer_f1=0,
            support_source_accuracy_superior=0,
            reader_answer_f1_superior=0,
            paired_answer_f1_unscored=0,
        )
    )
    total_attempts, failed_attempts, citations = 0, 0, 0
    for stage in STAGES:
        for phase in PHASES:
            base = metrics[f"{stage}/{phase}/frozen_rerank"]
            for arm in ARMS:
                row = metrics[f"{stage}/{phase}/{arm}"]
                if (
                    row["attempted"] != 8
                    or row["succeeded"] + row["failed"] != 8
                    or row["emitted_citation_markers"] < 0
                    or row["delivered_citation_markers"] < 0
                    or row["delivered_citation_markers"]
                    > row["emitted_citation_markers"]
                ):
                    raise ValueError("corrupt policy success/citation denominator")
                total_attempts += row["attempted"]
                failed_attempts += row["failed"]
                citations += row["emitted_citation_markers"]
                if arm == "frozen_rerank":
                    continue
                group = by_arm[arm]
                group["compared_phase_checkpoints"] += 1
                for field, name, higher in (
                    (
                        "source_accuracy",
                        "identical_source_accuracy",
                        "support_source_accuracy_superior",
                    ),
                    (
                        "diagnostic_f1",
                        "identical_answer_f1",
                        "reader_answer_f1_superior",
                    ),
                ):
                    a, b = row[field], base[field]
                    if a is None or b is None:
                        group["paired_answer_f1_unscored"] += 1
                    elif not all(
                        type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1
                        for v in (a, b)
                    ):
                        raise ValueError("nonfinite native outcome")
                    elif a == b:
                        group[name] += 1
                    elif a > b:
                        group[higher] += 1
    if total_attempts != 576:
        raise ValueError("policy denominator drift")
    results = dict(by_arm)
    observed_outcome_improvement = any(
        x["support_source_accuracy_superior"] or x["reader_answer_f1_superior"]
        for x in results.values()
    )
    return dict(
        schema="hepta.stem-native-nonpromotion-gate.v1",
        status="not-qualified",
        audited_policy_attempts=total_attempts,
        policy_execution_failures=failed_attempts,
        citation_markers=citations,
        learning_arms=results,
        any_aggregate_source_or_answer_gain=bool(observed_outcome_improvement),
        aggregate_equivalence_not_proof_of_identical_question_choices=True,
        independent_semantic_citation_precision=None,
        production_accepted=False,
        scale_out_permitted=False,
        next_required_evidence=(
            "exact per-question frozen-paired source changes, heldout answer gain, "
            "independent semantic citation audit and per-arm TCO"
        ),
    )


def audit_exact_paired_choices(
    plan, raw, scored, report, train_fit, source_ceiling, effective_panel
):
    """Audit every real decision, not just aggregates with cancelling gains.

    All evidence is from the exact archived completed run; original answers and
    native labels were only joined after generation. No policy is rerun.
    """
    phases = {phase: plan["questions"][phase] for phase in PHASES}
    all_questions = [q for ids in plan["questions"].values() for q in ids]
    if (
        tuple(plan["arms"]) != ARMS
        or tuple(plan["curriculum_attempted_examples"]) != STAGES
        or len(plan["questions"]["train"]) != 48
        or any(len(ids) != 8 for ids in phases.values())
        or len(all_questions) != len(set(all_questions)) != 80
        or len(raw) != 576
        or len(scored) != 576
    ):
        raise ValueError("incomplete 80-question/576-attempt preregistration")
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in phases[phase]
        for arm in ARMS
    }
    original, official = {}, {}
    for rows, dest in ((raw, original), (scored, official)):
        for row in rows:
            key = row["stage"], row["phase"], row["question_id"], row["arm"]
            if key not in expected or key in dest:
                raise ValueError("duplicate or unregistered strict-native attempt")
            dest[key] = row
    if set(original) != expected or set(official) != expected:
        raise ValueError("missing strict-native paired attempt")

    training_journal = {}
    for row in report["learning"]:
        key = row["stage"], row["arm"], row["cell"]
        if (
            key in training_journal
            or key[0] not in STAGES
            or key[1] not in ARMS
            or key[2] not in ("general", "temporal")
            or row["status"] != "succeeded"
            or not row["other_head_states_unchanged"]
        ):
            raise ValueError("mismatched or incomplete actual Head training journal")
        training_journal[key] = row
    if len(training_journal) != 36:
        raise ValueError("missing actual Head training checkpoint")
    if (
        not isinstance(plan.get("routes"), dict)
        or set(plan["routes"])
        != {qid for phase in PHASES for qid in phases[phase]}
        | set(plan["questions"]["train"])
        or any(v not in ("general", "temporal") for v in plan["routes"].values())
    ):
        raise ValueError("registered exact Cell/question route census drift")
    n_citations = 0
    for key in sorted(expected):
        source, evaluated = original[key], official[key]
        cell = source.get("cell")
        if (
            type(cell) is not str
            or cell not in ("general", "temporal")
            or plan.get("routes", {}).get(key[2]) != cell
        ):
            raise ValueError("invalid matched Cell route in original policy record")
        bound_head = training_journal.get((key[0], key[3], cell))
        if bound_head is None:
            raise ValueError("policy Head missing from pinned training checkpoint")
        if (
            source["status"] != evaluated["status"]
            or source["status"] != "succeeded"
            or not all(
                source.get(k) == evaluated.get(k)
                for k in (
                    "selected",
                    "answer",
                    "pool_digest",
                    "feature_digest",
                    "head_sha256",
                    "encoder_identity",
                )
            )
            or source.get("cell") != evaluated.get("cell")
            or source.get("family") != evaluated.get("family")
            or source.get("head_sha256") != bound_head["after_sha256"]
            or source["receipt"] != evaluated["receipt"]
            or not source["receipt"].get("generator_identity")
            or not source["receipt"].get("generator_profile")
            or source["receipt"].get("observable_query", {}).get("identity") != key[2]
        ):
            raise ValueError(
                "evaluated answer differs from exact original Reader receipt"
            )
        correctness = evaluated.get("source_choice_correct")
        if correctness is not None and (
            type(correctness) is not int or correctness not in (0, 1)
        ):
            raise ValueError("invalid native source-support annotation")
        value = evaluated.get("diagnostic_answer_f1")
        if value is not None and (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError("invalid diagnostic answer token score")
        cite = evaluated["citation_structure"]
        if (
            type(cite["markers"]) is not int
            or cite["markers"] < 0
            or type(cite["delivered_markers"]) is not int
            or not 0 <= cite["delivered_markers"] <= cite["markers"]
            or cite["semantic_precision"] is not None
        ):
            raise ValueError("semantic citations cannot self-certify")
        n_citations += cite["markers"]

    learned = {}
    for arm in ARMS[1:]:
        selected, answers, regressions, gains, per_phase = 0, 0, 0, 0, {}
        for phase in PHASES:
            moved, changed_answer, better, worse = 0, 0, 0, 0
            for stage in STAGES:
                for qid in phases[phase]:
                    reference = official[(stage, phase, qid, ARMS[0])]
                    experiment = official[(stage, phase, qid, arm)]
                    if (
                        reference["pool_digest"] != experiment["pool_digest"]
                        or reference["family"] != experiment["family"]
                        or reference["cell"] != experiment["cell"]
                        or reference["receipt"]["generator_identity"]
                        != experiment["receipt"]["generator_identity"]
                        or reference["receipt"]["generator_profile"]
                        != experiment["receipt"]["generator_profile"]
                        or reference["receipt"]["observable_query"]
                        != experiment["receipt"]["observable_query"]
                    ):
                        raise ValueError(
                            "mismatched frozen/learned question/pool/Reader"
                        )
                    moved += reference["selected"] != experiment["selected"]
                    changed_answer += reference["answer"] != experiment["answer"]
                    a, b = (
                        reference["source_choice_correct"],
                        experiment["source_choice_correct"],
                    )
                    if a is not None and b is not None:
                        better += b > a
                        worse += b < a
            per_phase[phase] = dict(
                matched_checkpoint_question_pairs=24,
                changed_source_top1=moved,
                changed_original_answer_bytes=changed_answer,
                weak_native_support_gains=better,
                weak_native_support_regressions=worse,
                independent_question_units=8,
                repeated_checkpoint_observations=3,
            )
            selected += moved
            answers += changed_answer
            gains += better
            regressions += worse
        learned[arm] = dict(
            matched_policy_pairs=96,
            changed_source_top1=selected,
            changed_original_answer_bytes=answers,
            weak_native_support_gains=gains,
            weak_native_support_regressions=regressions,
            observed_test_transfer_net_source_gain=sum(
                per_phase[x]["weak_native_support_gains"]
                - per_phase[x]["weak_native_support_regressions"]
                for x in ("test", "transfer")
            ),
            phase_census=per_phase,
        )
    if (
        len(train_fit["checkpoints"]) != 30
        or effective_panel["independent_question_ids_per_arm"] != 16
        or effective_panel["repeated_question_evaluations_per_arm"] != 48
        or effective_panel["source_family_sampling_independence_certified"] is not False
        or any(source_ceiling["phases"][phase]["attempted"] != 8 for phase in PHASES)
        or report["production_accepted"] is not False
        or report["semantic_citation_precision"] is not None
    ):
        raise ValueError("incomplete or falsely certified training/heldout evidence")
    fits = {}
    for item in train_fit["checkpoints"]:
        key = item["checkpoint"], item["arm"], item["cell"]
        if (
            key in fits
            or item["checkpoint"] not in STAGES
            or item["arm"] not in ARMS[1:]
            or item["cell"] not in ("general", "temporal")
            or item["heldout_annotations_consulted"] is not False
            or item["production_accepted"] is not False
            or type(item["changed_train_top1_rows"]) is not int
            or item["changed_train_top1_rows"] < 0
            or not math.isfinite(item["mean_weak_loss_delta"])
            or item["previous_head_sha256"] != training_journal[key]["before_sha256"]
            or item["updated_head_sha256"] != training_journal[key]["after_sha256"]
        ):
            raise ValueError("invalid measured Head training/checkpoint")
        fits[key] = item
    if len(fits) != 30:
        raise ValueError("incomplete Head fit matrix")

    # These are ceilings on weak annotated DOCUMENT membership, not actual
    # achievable Reader/citation accuracy. A top1-only Head cannot repair a
    # missing retrieved source or abstain on native-unanswerable questions.
    phase_bottlenecks = {}
    for phase in PHASES:
        src = source_ceiling["phases"][phase]
        if (
            type(src["attempted"]) is not int
            or src["attempted"] != 8
            or any(
                type(src[field]) is not int or src[field] < 0
                for field in (
                    "native_source_resolved",
                    "native_unanswerable",
                    "native_unresolved_support",
                    "support_available_within_pool",
                    "support_missing_from_pool",
                    "frozen_correct_source_choices",
                    "frozen_missed_available_support",
                )
            )
            or src["native_source_resolved"]
            + src["native_unanswerable"]
            + src["native_unresolved_support"]
            != 8
            or src["support_available_within_pool"] + src["support_missing_from_pool"]
            > src["native_source_resolved"]
            or src["frozen_correct_source_choices"]
            + src["frozen_missed_available_support"]
            > src["support_available_within_pool"]
        ):
            raise ValueError(
                "unbound or fabricated native retrieval opportunity ceiling"
            )
        phase_bottlenecks[phase] = dict(
            planned_original_questions=8,
            published_answerable_source_labels=src["native_source_resolved"],
            published_native_unanswerable=src["native_unanswerable"],
            published_source_label_unresolved=src["native_unresolved_support"],
            weak_source_missing_from_fixed_candidate_pool=src[
                "support_missing_from_pool"
            ],
            weak_source_present_in_fixed_candidate_pool=src[
                "support_available_within_pool"
            ],
            frozen_picked_weak_native_support=src["frozen_correct_source_choices"],
            maximum_additional_source_supported_choices_for_same_pool_top1_head=(
                src["support_available_within_pool"]
                - src["frozen_correct_source_choices"]
            ),
            native_abstentions_impossible_under_forced_top1=src["native_unanswerable"],
            independent_entailment_verified=False,
            observed_or_preregistered_intervention_gain=False,
        )
    heldout = [phase_bottlenecks[p] for p in ("test", "transfer")]
    rerank_bound = sum(
        x["maximum_additional_source_supported_choices_for_same_pool_top1_head"]
        for x in heldout
    )
    return dict(
        schema="hepta.stem-strict-exact-paired-nonpromotion.v1",
        full_policy_attempts=len(original),
        exact_original_scored_receipt_matches=len(official),
        full_policy_execution_failures=0,
        raw_emitted_citation_markers=n_citations,
        source_ceiling_by_phase=phase_bottlenecks,
        heldout_test_transfer_unique_questions=16,
        heldout_potential_additional_weak_source_top1_choices_rerank_only=rerank_bound,
        heldout_native_sources_absent_from_fixed_pool=sum(
            x["weak_source_missing_from_fixed_candidate_pool"] for x in heldout
        ),
        heldout_native_unanswerable_forced_top1=sum(
            x["native_abstentions_impossible_under_forced_top1"] for x in heldout
        ),
        these_are_upper_bounds_not_observed_task_gains=True,
        head_training_checkpoints=len(fits),
        head_checkpoints_with_top1_train_change=sum(
            x["changed_train_top1_rows"] > 0 for x in fits.values()
        ),
        head_checkpoints_with_lower_weak_loss=sum(
            x["mean_weak_loss_delta"] < 0 for x in fits.values()
        ),
        retrieval_support_missing_by_phase={
            phase: source_ceiling["phases"][phase]["support_missing_from_pool"]
            for phase in PHASES
        },
        unique_test_transfer_questions_per_arm=16,
        repeated_test_transfer_observations_per_arm=48,
        learned_arms=learned,
        independently_verified_semantic_entailment=False,
        answer_accuracy_from_public_benchmark_not_prospective=True,
        any_observed_native_source_gain_not_independent_qualification=True,
        semantic_citation_precision=None,
        scale_out_permitted=False,
        production_accepted=False,
    )
