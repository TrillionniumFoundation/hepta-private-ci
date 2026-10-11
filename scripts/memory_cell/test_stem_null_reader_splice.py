"""Pure fixture tests: no new Reader calls and no posthoc model selection."""

from types import SimpleNamespace as NS
import unittest

from native import digest
from stem_native_null_ablation import observe_null_choice
from stem_null_reader_splice import observed_zero_offset_reader_splice

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
IDENTITY, PROFILE = "fixed-reader", "same-prompt"


def fixture():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({p: [f"{p}-{i}" for i in range(8)] for p in PHASES})
    plan = dict(
        arms=list(ARMS), curriculum_attempted_examples=list(STAGES), questions=questions
    )
    targets = {
        q: NS(
            answer="BAR",
            evidence=("source",),
            unanswerable=False,
            unresolved_evidence=(),
        )
        for phase in PHASES
        for q in questions[phase]
    }
    scored, controls = [], []
    for phase in PHASES:
        for q in questions[phase]:
            query = dict(
                identity=q,
                content="What was it?",
                scope="scope-" + q,
                observed_at="2024-05-01",
            )
            controls.append(
                dict(
                    phase=phase,
                    question_id=q,
                    family="family-" + q,
                    status="succeeded",
                    answer="BAR",
                    evidence_count=0,
                    receipt=dict(
                        generator_identity=IDENTITY,
                        generator_profile=PROFILE,
                        delivered_evidence=[],
                        observable_query=query,
                        canonical_request_digest=digest(
                            (
                                IDENTITY,
                                PROFILE,
                                query,
                                [],
                            )
                        ),
                        actual_reader_execution=True,
                    ),
                )
            )
            for stage in STAGES:
                for arm in ARMS:
                    scored.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=q,
                            arm=arm,
                            family="family-" + q,
                            status="succeeded",
                            selected=0,
                            answer="FOO",
                            null_counterfactual=observe_null_choice(
                                [2.0, 1.0, 3.0], ("A", "B"), 0
                            ),
                            receipt=dict(
                                generator_identity=IDENTITY,
                                generator_profile=PROFILE,
                                observable_query=query,
                                delivered_evidence=[
                                    dict(label="E1", excerpt="Some content.")
                                ],
                            ),
                        )
                    )
    return plan, scored, controls, targets


def diagnose(answer, target):
    return float(answer == target.answer)


def run(plan, scored, control, targets):
    return observed_zero_offset_reader_splice(
        plan,
        scored,
        control,
        targets,
        diagnose,
        reader_identity=IDENTITY,
        reader_profile=PROFILE,
    )


class SpliceTests(unittest.TestCase):
    def test_splices_real_empty_answers_with_no_extra_reader_requests(self):
        plan, scored, controls, targets = fixture()
        old = digest(scored)
        result = run(plan, scored, controls, targets)
        self.assertEqual(digest(scored), old)
        self.assertEqual(len(result["rows"]), 192)
        self.assertEqual(result["planned_original_policy_rows"], 576)
        self.assertEqual(result["actual_extra_reader_calls_in_this_analysis"], 0)
        phase = result["per_phase_arm"]["test/gated"]
        self.assertEqual(phase["planned"], 8)
        self.assertEqual(phase["real_empty_evidence_answers_used"], 8)
        self.assertEqual(
            phase["by_native_answerability"]["answerable-native-document-support"][
                "original_evidence_replaced_count"
            ],
            8,
        )
        self.assertEqual(phase["paired_diagnostic_f1_delta_mean"], 1.0)
        self.assertEqual(phase["all_planned_paired_delta_bounds"], [1, 1])
        self.assertFalse(result["production_accepted"])

    def test_keep_original_answer_if_zero_offset_selects_source(self):
        p, scored, controls, targets = fixture()
        item = next(
            r
            for r in scored
            if (r["stage"], r["phase"], r["question_id"], r["arm"])
            == (48, "test", "test-0", "gated")
        )
        item["null_counterfactual"] = observe_null_choice(
            [2.0, 1.0, -1.0],
            ("A", "B"),
            0,
        )
        report = run(p, scored, controls, targets)["per_phase_arm"]["test/gated"]
        self.assertEqual(report["would_abstain"], 7)
        self.assertEqual(report["real_empty_evidence_answers_used"], 7)
        self.assertEqual(report["paired_diagnostic_f1_delta_mean"], 7 / 8)

    def test_failure_does_not_disappear_or_become_f1_success(self):
        p, scored, controls, targets = fixture()
        row = next(
            r
            for r in scored
            if (r["stage"], r["phase"], r["question_id"], r["arm"])
            == (48, "test", "test-0", "gated")
        )
        row["status"] = "failed"
        row.pop("answer")
        row.pop("receipt")
        out = run(p, scored, controls, targets)["per_phase_arm"]["test/gated"]
        self.assertEqual(out["planned"], 8)
        self.assertEqual(out["actual_original_reader_successes"], 7)
        self.assertEqual(out["observed_shadow_answers"], 8)
        self.assertEqual(out["scored_paired_answer_changes"], 7)
        self.assertEqual(out["all_planned_paired_delta_bounds"], [0.75, 1.0])

    def test_missing_no_evidence_answer_is_bounded_not_replaced(self):
        p, scored, controls, targets = fixture()
        control = next(c for c in controls if c["question_id"] == "test-0")
        control["status"] = "failed"
        control.pop("answer")
        control.pop("receipt")
        out = run(p, scored, controls, targets)["per_phase_arm"]["test/gated"]
        self.assertEqual(out["observed_shadow_answers"], 7)
        self.assertEqual(out["omitted_or_unscored_pairs"], 1)
        self.assertEqual(out["all_planned_paired_delta_bounds"], [0.75, 1.0])

    def test_missing_duplicate_policy_and_reader_identity_drift_rejected(self):
        for mode in ("missing", "duplicate", "identity", "evidence", "question"):
            p, scored, controls, targets = fixture()
            if mode == "missing":
                scored.pop()
            elif mode == "duplicate":
                scored[-1] = dict(scored[0])
            elif mode == "identity":
                controls[0]["receipt"]["generator_identity"] = "other-reader"
            elif mode == "question":
                controls[0]["receipt"]["observable_query"]["identity"] = "unrelated"
            else:
                controls[0]["receipt"]["delivered_evidence"] = [{"label": "E1"}]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                run(p, scored, controls, targets)

    def test_null_receipt_tampering_and_forged_empty_source_reject(self):
        for mode in ("claim", "selected", "forge", "missing"):
            p, scored, controls, targets = fixture()
            row = next(
                r
                for r in scored
                if (r["stage"], r["phase"], r["question_id"], r["arm"])
                == (48, "test", "test-0", "gated")
            )
            if mode == "claim":
                row["null_counterfactual"]["zero_offset_would_abstain"] = False
            elif mode == "selected":
                row["selected"] = 1
            elif mode == "forge":
                row["receipt"]["delivered_evidence"] = []
            else:
                row.pop("null_counterfactual")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                run(p, scored, controls, targets)

    def test_original_already_empty_and_failed_evidence_not_falsely_replaced(self):
        p, scored, controls, targets = fixture()
        one = next(
            r
            for r in scored
            if (r["stage"], r["phase"], r["question_id"], r["arm"])
            == (48, "test", "test-0", "gated")
        )
        one["selected"] = None
        one["null_counterfactual"] = observe_null_choice([0.0], (), None)
        one["receipt"]["delivered_evidence"] = []
        broken = next(
            r
            for r in scored
            if (r["stage"], r["phase"], r["question_id"], r["arm"])
            == (48, "test", "test-1", "gated")
        )
        broken["status"] = "failed"
        broken.pop("receipt")
        broken.pop("answer")
        report = run(p, scored, controls, targets)["per_phase_arm"]["test/gated"]
        category = report["by_native_answerability"][
            "answerable-native-document-support"
        ]
        self.assertEqual(category["registered_questions"], 8)
        self.assertEqual(category["original_evidence_replaced_count"], 6)
        self.assertEqual(report["scored_paired_answer_changes"], 7)

    def test_null_abstention_f1_not_independent_entailment(self):
        p, scored, controls, targets = fixture()
        targets["test-0"].unanswerable = True
        output = run(p, scored, controls, targets)
        row = next(x for x in output["rows"] if x["question_id"] == "test-0")
        self.assertEqual(row["category"], "native-unanswerable")
        self.assertEqual(
            output["per_phase_arm"]["test/gated"]["by_native_answerability"][
                "native-unanswerable"
            ]["registered_questions"],
            1,
        )
        self.assertEqual(
            output["per_phase_arm"]["test/gated"]["by_native_answerability"][
                "answerable-native-document-support"
            ]["registered_questions"],
            7,
        )
        self.assertIsNone(row["semantic_citation_precision"])
        self.assertTrue(output["posthoc_zero_offset_not_a_preregistered_policy"])
        self.assertTrue(output["independent_answer_semantics_unverified"])


if __name__ == "__main__":
    unittest.main()
