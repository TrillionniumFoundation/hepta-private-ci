"""Do not turn three repeated native checkpoints into 48 independent test subjects.

Pure post-policy accounting of the already matched frozen-vs-learned
test/transfer records. The single predeclared last checkpoint is the
descriptive primary contrast; prior checkpoints describe repeated measures.
Native document support is weak. No independence, significance, entailment,
or prospective population inference is certified.
"""

from collections import Counter
import math


STAGES = (16, 32, 48)
PHASES = ("test", "transfer")
CELLS = ("general", "temporal")
ARMS = ("prototype", "linear", "gated", "lineage_lora_gated", "independent_lora_gated")
KINDS = (
    "answerable-native-document-support",
    "native-unanswerable",
    "native-support-unresolved",
)


def _bounds(values, planned):
    if not planned:
        raise ValueError("empty planned effective-N cohort")
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1
        for v in values
    ):
        raise ValueError("invalid paired native effect")
    missing = planned - len(values)
    if missing < 0:
        raise ValueError("more observations than registered subjects")
    total = math.fsum(values)
    return [(total - missing) / planned, (total + missing) / planned]


def effective_heldout_subjects(plan, paired_bridge):
    """Evaluate stage 48 once per question; separately retain stages 16/32."""
    questions = plan["questions"]
    families = plan["question_families"]
    routes = plan["routes"]
    if (
        paired_bridge["schema"] != "hepta.stem-train-heldout-diagnostic-gap.v5"
        or paired_bridge["production_accepted"] is not False
        or paired_bridge["posthoc_source_annotations_only"] is not True
        or paired_bridge["native_document_support_vs_abstention_separate"] is not True
        or tuple(plan["arms"][1:]) != ARMS
        or tuple(plan["curriculum_attempted_examples"]) != STAGES
        or tuple(plan["cells"]) != CELLS
        or any(len(questions[phase]) != 8 for phase in PHASES)
    ):
        raise ValueError("unbound native held-out paired cohort")
    subjects = {q: phase for phase in PHASES for q in questions[phase]}
    if (
        len(subjects) != 16
        or len(set(questions["test"] + questions["transfer"])) != 16
        or not set(subjects).issubset(families)
        or not set(subjects).issubset(routes)
        or any(
            routes[q] not in CELLS
            or not isinstance(families[q], str)
            or not families[q]
            for q in subjects
        )
    ):
        raise ValueError("held-out question/family/route identities drifted")
    all_phases = ("train", "select", "retention", "test", "transfer")
    if any(
        phase not in questions
        or any(
            q not in families or not isinstance(families[q], str) or not families[q]
            for q in questions[phase]
        )
        for phase in all_phases
    ):
        raise ValueError("unregistered original source-family lineage")
    family_sets = {
        phase: {families[q] for q in questions[phase]} for phase in all_phases
    }
    source_family_units = dict(
        test=len(family_sets["test"]),
        transfer=len(family_sets["transfer"]),
        combined_test_transfer=len(family_sets["test"] | family_sets["transfer"]),
        retention=len(family_sets["retention"]),
        test_shared_with_retention=len(family_sets["test"] & family_sets["retention"]),
        test_new_beyond_retention=len(family_sets["test"] - family_sets["retention"]),
        transfer_shared_with_train_select_retention_test=len(
            family_sets["transfer"]
            & (
                family_sets["train"]
                | family_sets["select"]
                | family_sets["retention"]
                | family_sets["test"]
            )
        ),
        test_is_unseen_source_family_vs_retention=(
            not bool(family_sets["test"] & family_sets["retention"])
        ),
        family_overlap_does_not_prove_training_label_leakage=True,
        unique_source_families_not_independent_samples=True,
        independent_family_sampling_verified=False,
    )
    rows = paired_bridge["test_transfer_paired_panel_rows"]
    if not isinstance(rows, list) or len(rows) != 3 * 5 * 16:
        raise ValueError("full three-stage repeated question panel required")
    expected = {
        (stage, arm, phase, q)
        for stage in STAGES
        for arm in ARMS
        for q, phase in subjects.items()
    }
    indexed = {}
    truth_kind = {}
    pinned_pool_by_question = {}
    pinned_reader_request_by_question = {}
    for row in rows:
        key = row["stage"], row["arm"], row["phase"], row["question_id"]
        if key not in expected or key in indexed:
            raise ValueError("extra or repeated held-out evaluation row")
        q = row["question_id"]
        cat = row["native_source_label_category"]
        if (
            row["cell"] != routes[q]
            or row["source_family"] != families[q]
            or cat not in KINDS
            or type(row["both_source_choices_observed"]) is not bool
            or type(row["both_original_reader_calls_succeeded"]) is not bool
            or type(row["both_reader_answers_scored"]) is not bool
            or row["semantic_citation_precision"] is not None
            or (cat == KINDS[0]) != row["native_answerable_source_support"]
        ):
            raise ValueError("mismatched Cell/family or native label classification")
        if q in truth_kind and truth_kind[q] != cat:
            raise ValueError("question native answerability changed across checkpoints")
        truth_kind[q] = cat
        pool = row["matched_original_pool_digest"]
        if row["both_source_choices_observed"]:
            if not isinstance(pool, str) or not pool:
                raise ValueError("missing frozen-matched original candidate pool")
            previous = pinned_pool_by_question.setdefault(q, pool)
            if previous != pool:
                raise ValueError("frozen candidate pool changed between checkpoints")
        elif pool is not None:
            raise ValueError("unobserved selection acquired a false pool binding")
        reader = row["matched_reader_request_identity"]
        if row["both_original_reader_calls_succeeded"]:
            if (
                not isinstance(reader, (tuple, list))
                or len(reader) != 3
                or any(not isinstance(v, str) or not v for v in reader)
            ):
                raise ValueError("unbound matched Reader source/prompt/question")
            previous = pinned_reader_request_by_question.setdefault(q, tuple(reader))
            if previous != tuple(reader):
                raise ValueError("frozen Reader/prompt changed between checkpoints")
        elif reader is not None:
            raise ValueError("failed Reader pair received a forged identity")
        change = row["changed_top1"]
        if (change is not None and type(change) is not bool) or (
            row["both_source_choices_observed"] != (change is not None)
        ):
            raise ValueError("missing selection treated as a stable source decision")
        gain = row["weak_support_gain"]
        abstain = row["native_abstention_gain"]
        if (
            (
                gain is not None
                and (cat != KINDS[0] or type(gain) is not int or gain not in (-1, 0, 1))
            )
            or (
                abstain is not None
                and (
                    cat != KINDS[1]
                    or type(abstain) is not int
                    or abstain not in (-1, 0, 1)
                )
            )
            or (cat == KINDS[2] and (gain is not None or abstain is not None))
        ):
            raise ValueError(
                "abstention or unresolved source laundered into source gain"
            )
        f1 = row["diagnostic_answer_f1_delta"]
        if (
            (
                f1 is not None
                and (
                    type(f1) not in (int, float)
                    or not math.isfinite(f1)
                    or not -1 <= f1 <= 1
                )
            )
            or row["both_reader_answers_scored"] != (f1 is not None)
            or (f1 is not None and not row["both_original_reader_calls_succeeded"])
        ):
            raise ValueError("Reader failure laundered into paired answer effect")
        indexed[key] = row
    if set(indexed) != expected or len(truth_kind) != 16:
        raise ValueError("missing native repeated observation or question category")
    report = {}
    for arm in ARMS:
        stage48 = [
            indexed[(48, arm, subjects[q], q)]
            for q in questions["test"] + questions["transfer"]
        ]

        def summarize(cohort):
            gain = [
                x["weak_support_gain"]
                for x in cohort
                if x["weak_support_gain"] is not None
            ]
            abstain = [
                x["native_abstention_gain"]
                for x in cohort
                if x["native_abstention_gain"] is not None
            ]
            answer = [
                x["diagnostic_answer_f1_delta"]
                for x in cohort
                if x["diagnostic_answer_f1_delta"] is not None
            ]
            by_type = Counter(x["native_source_label_category"] for x in cohort)
            n = len(cohort)
            return dict(
                planned_unique_questions=n,
                source_family_count=len(set(x["source_family"] for x in cohort)),
                answerable_native_source_questions=by_type[KINDS[0]],
                native_unanswerable_questions=by_type[KINDS[1]],
                unresolved_native_support_questions=by_type[KINDS[2]],
                both_top1_selections_observed=sum(
                    x["both_source_choices_observed"] for x in cohort
                ),
                original_pool_binding_verified_for_observed_selections=sum(
                    x["matched_original_pool_digest"] is not None for x in cohort
                ),
                matched_reader_identity_verified_for_success_pairs=sum(
                    x["matched_reader_request_identity"] is not None for x in cohort
                ),
                changed_top1_decisions=sum(x["changed_top1"] is True for x in cohort),
                source_support_scored_pairs=len(gain),
                source_support_gains=sum(x == 1 for x in gain),
                source_support_regressions=sum(x == -1 for x in gain),
                source_support_all_planned_bounds=_bounds(gain, n),
                abstention_scored_pairs=len(abstain),
                abstention_gains=sum(x == 1 for x in abstain),
                abstention_regressions=sum(x == -1 for x in abstain),
                abstention_all_planned_bounds=_bounds(abstain, n),
                both_reader_calls_succeeded=sum(
                    x["both_original_reader_calls_succeeded"] for x in cohort
                ),
                paired_reader_f1_scored=len(answer),
                paired_reader_f1_delta_mean=(
                    math.fsum(answer) / len(answer) if answer else None
                ),
                reader_f1_all_planned_bounds=_bounds(answer, n),
            )

        per_phase = {
            phase: summarize([x for x in stage48 if x["phase"] == phase])
            for phase in PHASES
        }
        per_cell = {
            cell: summarize([x for x in stage48 if x["cell"] == cell]) for cell in CELLS
        }
        repeat_panel = {}
        for q in questions["test"] + questions["transfer"]:
            observations = [indexed[(stage, arm, subjects[q], q)] for stage in STAGES]
            repeat_panel[q] = dict(
                phase=subjects[q],
                cell=routes[q],
                family=families[q],
                repeated_measures=3,
                candidate_selection_changed_at_any_stage=any(
                    x["changed_top1"] is True for x in observations
                ),
                native_support_gain_on_all_three_stages=all(
                    x["weak_support_gain"] == 1 for x in observations
                ),
                original_reader_both_succeeded_all_stages=all(
                    x["both_original_reader_calls_succeeded"] for x in observations
                ),
            )
        report[arm] = dict(
            primary_checkpoint=48,
            primary=summarize(stage48),
            per_phase=per_phase,
            per_cell=per_cell,
            repeated_checkpoint_observations=48,
            unique_heldout_questions=16,
            independent_sampling_units_authenticated=False,
            original_pool_stable_across_three_checkpoints_when_observed=True,
            frozen_reader_and_prompt_stable_when_observed=True,
            repeated_observations_must_not_be_48_independent_examples=True,
            exploratory_all_three_checkpoint_subjects=repeat_panel,
            variance_or_significance_from_nonindependent_questions=None,
            independent_generalization_proven=False,
        )
    return dict(
        schema="hepta.stem-effective-heldout-repeated-panel.v3",
        declared_phases=PHASES,
        stage_48_primary_predeclared_no_best_checkpoint_search=True,
        repeated_stages=STAGES,
        independent_question_ids_per_arm=16,
        repeated_question_evaluations_per_arm=48,
        source_family_sampling_independence_certified=False,
        original_native_source_family_structure=source_family_units,
        full_original_policy_census_verified_by_bridge=True,
        semantic_citation_precision=None,
        by_arm=report,
        production_accepted=False,
    )
