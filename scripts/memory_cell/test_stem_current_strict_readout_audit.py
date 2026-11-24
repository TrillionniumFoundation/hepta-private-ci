"""Adversarial synthetic audit checks; not a source of native QA scores."""

from copy import deepcopy
import unittest

from stem_audit_archive import AuditError
from stem_current_strict_readout_audit import (
    ARMS,
    PHASES,
    STAGES,
    evaluate_strict_run,
)


def fixtures():
    cohort = {"train": [f"train-{n}" for n in range(48)]}
    cohort.update({phase: [f"{phase}-{n}" for n in range(8)] for phase in PHASES})
    all_qids = [q for ids in cohort.values() for q in ids]
    routes = {
        q: ("general" if n % 2 == 0 else "temporal")
        for ids in cohort.values()
        for n, q in enumerate(ids)
    }
    families = {q: "train-source" for q in cohort["train"]}
    for phase in ("select", "retention", "test"):
        for n, q in enumerate(cohort[phase]):
            families[q] = "locomo-A" if n < 4 else "locomo-B"
    for q in cohort["transfer"]:
        families[q] = "longmemeval-C"
    plan = dict(
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        questions=cohort,
        routes=routes,
        question_families=families,
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
    )
    scored, raw = [], []
    availability = {}
    answerable_n = 0
    for phase in PHASES:
        unanswerable = {"select": 2, "retention": 2, "test": 2, "transfer": 1}[phase]
        for n, q in enumerate(cohort[phase]):
            is_answerable = n >= unanswerable
            if is_answerable:
                available = answerable_n < 17
                frozen_correct = answerable_n < 13
                answerable_n += 1
            else:
                available = frozen_correct = False
            availability[phase, q] = dict(
                phase=phase,
                question_id=q,
                source_family=families[q],
                weak_native_support_resolved=is_answerable,
                native_source_unanswerable=not is_answerable,
                native_support_available_in_pool=available if is_answerable else None,
                frozen_selected_native_support=(
                    frozen_correct if is_answerable else None
                ),
                native_weak_support_not_window_entailment=True,
                independently_reviewed_source_sufficiency=False,
            )
    assert answerable_n == 25
    for stage in STAGES:
        for phase in PHASES:
            for q in cohort[phase]:
                good = availability[phase, q]
                for arm in ARMS:
                    row = dict(
                        stage=stage,
                        phase=phase,
                        question_id=q,
                        arm=arm,
                        status="succeeded",
                        family=families[q],
                        cell=routes[q],
                        pool_digest="fixed-pool-" + q,
                        selected=0,
                        answer="Same pinned Reader answer",
                        receipt=dict(
                            generator_identity="frozen-reader",
                            generator_profile="unchanged-prompt",
                        ),
                    )
                    raw.append(row)
                    scored.append(
                        dict(
                            row,
                            source_choice_correct=(
                                int(good["frozen_selected_native_support"])
                                if good["weak_native_support_resolved"]
                                else 0
                            ),
                        )
                    )
    report = dict(
        plan=plan,
        logical_policy_attempts=576,
        production_accepted=False,
        semantic_citation_precision=None,
        reader=dict(
            actual_attempts=48,
            actual_successes=48,
            actual_failed_attempts=0,
            cache_hits=543,
        ),
        no_evidence_reader_report=dict(planned_controls=32),
        no_evidence_reader_call_accounting=dict(
            policy_and_oracle_reader=dict(actual_attempts=48),
        ),
        within_head_train_fit=[{} for _ in range(30)],
    )
    return plan, raw, scored, report, dict(decisions=list(availability.values()))


class StrictSourceGateTests(unittest.TestCase):
    def test_complete_strict_run_is_not_independent_learning_gain(self):
        data = evaluate_strict_run(*fixtures())
        self.assertEqual(data["successful_policy_attempts"], 576)
        self.assertEqual(data["answerable_evaluation_questions"], 25)
        self.assertEqual(data["native_unanswerable_evaluation_questions"], 7)
        self.assertEqual(data["answerable_native_support_in_fixed_pool"], 17)
        self.assertEqual(data["answerable_native_support_absent_from_fixed_pool"], 8)
        self.assertEqual(data["unique_test_transfer_questions"], 16)
        self.assertEqual(data["distinct_native_test_transfer_source_families"], 3)
        self.assertFalse(data["any_arm_positive_on_both_test_and_transfer"])
        self.assertFalse(data["production_accepted"])

    def test_one_test_gain_is_not_transfer_gain(self):
        plan, raw, scored, report, ceiling = fixtures()
        target = next(
            a
            for a in raw
            if a["stage"] == 48
            and a["phase"] == "test"
            and a["question_id"] == "test-5"
            and a["arm"] == "gated"
        )
        target["selected"] = 1
        target["answer"] = "New fixed Reader output"
        changed = next(
            a
            for a in scored
            if a["stage"] == 48
            and a["phase"] == "test"
            and a["question_id"] == "test-5"
            and a["arm"] == "gated"
        )
        changed.update(deepcopy(target), source_choice_correct=1)
        data = evaluate_strict_run(plan, raw, scored, report, ceiling)
        self.assertEqual(
            data["final_test_transfer_comparison"]["gated"]["test"][
                "native_document_support_gains"
            ],
            1,
        )
        self.assertFalse(data["any_arm_positive_on_both_test_and_transfer"])
        self.assertFalse(data["production_accepted"])

    def test_paired_original_answers_and_scoring_cannot_be_rewritten(self):
        cases = ("answer", "selected", "source_choice_correct", "same-choice-fake-gain")
        for mode in cases:
            plan, raw, scored, report, ceiling = fixtures()
            q = next(
                x
                for x in scored
                if x["stage"] == 48
                and x["phase"] == "test"
                and x["question_id"] == "test-5"
                and x["arm"] == "gated"
            )
            if mode == "same-choice-fake-gain":
                q["source_choice_correct"] = 1
            elif mode == "source_choice_correct":
                q["source_choice_correct"] = "unsupported"
            elif mode == "selected":
                q["selected"] = 1
            else:
                q["answer"] = "changed after actual Reader call"
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                evaluate_strict_run(plan, raw, scored, report, ceiling)

    def test_changed_reader_prompt_identity_or_candidate_pool_rejected(self):
        for field, new in (
            ("pool_digest", "different-pool"),
            ("generator_identity", "different-reader"),
            ("generator_profile", "different-prompt"),
        ):
            plan, raw, scored, report, ceiling = fixtures()
            target = next(
                x
                for x in raw
                if x["stage"] == 48 and x["phase"] == "test" and x["arm"] == "linear"
            )
            if field == "pool_digest":
                target[field] = new
            else:
                target["receipt"][field] = new
            with self.subTest(field=field), self.assertRaises(AuditError):
                evaluate_strict_run(plan, raw, scored, report, ceiling)

    def test_missing_duplicate_and_failed_policy_deny_success(self):
        for change in ("missing", "duplicate", "failed"):
            p, raw, scored, report, ceiling = fixtures()
            if change == "missing":
                raw.pop()
            elif change == "duplicate":
                raw[-1] = dict(raw[0])
            else:
                raw[-1]["status"] = "failed"
            with self.subTest(change=change), self.assertRaises(AuditError):
                evaluate_strict_run(p, raw, scored, report, ceiling)

    def test_missing_labels_and_changed_unanswerable_census_rejected(self):
        for kind in ("missing", "changed-class", "family-drift"):
            p, raw, scored, report, ceiling = fixtures()
            if kind == "missing":
                ceiling["decisions"].pop()
            elif kind == "changed-class":
                ceiling["decisions"][0]["native_source_unanswerable"] = False
            else:
                ceiling["decisions"][0]["source_family"] = "other-source"
            with self.subTest(kind=kind), self.assertRaises(AuditError):
                evaluate_strict_run(p, raw, scored, report, ceiling)

    def test_main_reader_postpolicy_oracle_cost_cannot_be_misassigned(self):
        p, raw, scored, report, ceiling = fixtures()
        report["reader"]["actual_attempts"] = 33
        with self.assertRaisesRegex(AuditError, "Reader invocation"):
            evaluate_strict_run(p, raw, scored, report, ceiling)

        p, raw, scored, report, ceiling = fixtures()
        report["no_evidence_reader_call_accounting"]["policy_and_oracle_reader"][
            "actual_attempts"
        ] = 33
        with self.assertRaisesRegex(AuditError, "Oracle"):
            evaluate_strict_run(p, raw, scored, report, ceiling)

    def test_production_field_cannot_be_true_and_noevidence_must_be_complete(self):
        p, raw, scored, report, ceiling = fixtures()
        report["production_accepted"] = True
        with self.assertRaises(AuditError):
            evaluate_strict_run(p, raw, scored, report, ceiling)
        report["production_accepted"] = False
        report["no_evidence_reader_report"]["planned_controls"] = 31
        with self.assertRaises(AuditError):
            evaluate_strict_run(p, raw, scored, report, ceiling)


if __name__ == "__main__":
    unittest.main()
