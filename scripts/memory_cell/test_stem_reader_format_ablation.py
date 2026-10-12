"""Synthetic-only flat-input Reader census; no pretrained model is executed."""

from dataclasses import asdict
import unittest

from native import Question, digest
from stem_reader_format_ablation import (
    ARCHIVED_SOURCE, ARMS, FORMAT_ID, PHASES, STAGES,
    fixed_frozen_cases, flat_user_message, evaluate_flat_answers,
)


def fixture():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({p: [f"{p}-{i}" for i in range(8)] for p in PHASES})
    plan = dict(
        source_commit=ARCHIVED_SOURCE,
        arms=list(ARMS), curriculum_attempted_examples=list(STAGES),
        questions=questions,
        question_families={
            qid: "family-"+qid for p in PHASES for qid in questions[p]
        },
    )
    rows = []
    for stage in STAGES:
        for phase in PHASES:
            for qid in questions[phase]:
                q = Question(
                    qid, "family-"+qid, "scope-"+qid,
                    "Which city?", "2023-03-09",
                )
                evidence = [dict(
                    label="E1", id="window-"+qid,
                    root="root-"+qid, scope=q.scope,
                    observed_at="2023-03-08",
                    excerpt="Unchanged private source text for Paris.",
                )]
                receipt = dict(
                    generator_identity="original-model",
                    generator_profile="original-prompt",
                    observable_query=asdict(q),
                    question_digest=digest(asdict(q)),
                    delivered_evidence=evidence,
                    canonical_request_digest=digest((
                        "original-model", "original-prompt", asdict(q), evidence,
                    )),
                    input_ids_digest="input-pinned",
                    generated_ids_digest="output-pinned",
                    production_accepted=False,
                )
                for arm in ARMS:
                    rows.append(dict(
                        stage=stage, phase=phase, arm=arm,
                        question_id=qid, family="family-"+qid,
                        status="succeeded",
                        answer="Paris",
                        selection_geometry=dict(learned_top_id="window-"+qid),
                        receipt=receipt,
                    ))
    return plan, rows


def outcomes(cases):
    rows = [
        dict(
            question_id=c["question_id"], phase=c["phase"],
            status="succeeded", answer="Paris", receipt=dict(
                delivered_evidence=c["delivered_evidence"]
            ),
        ) for c in cases
    ]
    baseline = [
        dict(question_id=c["question_id"], stage=48,
             arm="frozen_rerank", status="succeeded",
             diagnostic_answer_f1=0.5, answer='{"question": "Which city?"}')
        for c in cases
    ]
    targets = {c["question_id"]: "Paris" for c in cases}
    return rows, baseline, targets


class FlatReaderTests(unittest.TestCase):
    def test_exact_six_arm_original_576_to_32_control_cases(self):
        plan, rows = fixture()
        c = fixed_frozen_cases(plan, rows)
        self.assertEqual(len(rows), 576)
        self.assertEqual(len(c), 32)
        self.assertEqual(c[0]["original_reader_identity"], "original-model")
        self.assertEqual(c[0]["delivered_evidence"][0]["label"], "E1")
        self.assertTrue(all(x["format_rewrite_only"] for x in c))

    def test_flat_preserves_original_source_bytes_and_not_gold(self):
        cases = fixed_frozen_cases(*fixture())
        q, source = cases[0]["question"], cases[0]["delivered_evidence"]
        payload = flat_user_message(q, source)
        self.assertIn(q["content"], payload)
        self.assertIn(source[0]["excerpt"], payload)
        self.assertIn("Evidence [E1], observed at", payload)
        self.assertNotIn('{"question"', payload)
        self.assertNotIn("SECRET_TARGET_NOT_IN_SOURCE", payload)
        self.assertTrue(FORMAT_ID.endswith(".v1"))

    def test_all_32_answer_records_scored_only_after_generation(self):
        cases = fixed_frozen_cases(*fixture())
        answer, baseline, targets = outcomes(cases)
        report = evaluate_flat_answers(
            cases, answer, baseline, targets,
            lambda text, target: float(text == target),
        )
        self.assertEqual(report["planned_questions"], 32)
        self.assertEqual(report["phases"]["test"]["paired_f1_scored"], 8)
        self.assertEqual(report["phases"]["test"]["paired_diagnostic_f1_delta_mean"], .5)
        self.assertTrue(report["only_user_payload_format_changed"])
        self.assertFalse(report["production_accepted"])
        self.assertIsNone(report["semantic_citation_precision"])

    def test_flat_format_counts_prompt_echo_separately_from_answer_accuracy(self):
        cases = fixed_frozen_cases(*fixture())
        answers, baseline, targets = outcomes(cases)
        report = evaluate_flat_answers(
            cases, answers, baseline, targets,
            lambda answer, target: float(answer == target),
        )
        phase = report["phases"]["test"]
        self.assertEqual(phase["original_serialized_question_prefixes"], 8)
        self.assertEqual(phase["flat_serialized_question_prefixes"], 0)
        self.assertEqual(phase["original_structural_citation_markers"], 0)
        self.assertEqual(phase["flat_structural_citation_markers"], 0)
        self.assertIsNone(phase["semantic_citation_precision"])

    def test_failure_or_unscored_target_stays_in_original_denominator(self):
        cases = fixed_frozen_cases(*fixture())
        answers, baseline, targets = outcomes(cases)
        answers[0] = dict(answers[0], status="failed")
        answers[0].pop("answer")
        result = evaluate_flat_answers(
            cases, answers, baseline, targets,
            lambda answer, target: float(answer == target),
        )["phases"]["select"]
        self.assertEqual(result["flat_generation_succeeded"], 7)
        self.assertEqual(result["paired_f1_missing"], 1)
        self.assertEqual(result["all_planned_f1_delta_bounds"], [
            (3.5-1)/8, (3.5+1)/8,
        ])

    def test_original_request_or_future_source_mutation_is_rejected(self):
        for mode in ("request", "future", "source-id"):
            plan, rows = fixture()
            old = next(x for x in rows if x["stage"] == 48
                       and x["phase"] == "test" and x["arm"] == "frozen_rerank")
            if mode == "request":
                old["receipt"]["canonical_request_digest"] = "tamper"
            elif mode == "future":
                old["receipt"]["delivered_evidence"][0]["observed_at"] = "2023-03-10"
            else:
                old["selection_geometry"]["learned_top_id"] = "tamper"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fixed_frozen_cases(plan, rows)

    def test_complete_stage_and_no_duplicate_experiment_records(self):
        plan, rows = fixture()
        for modified in (rows[:-1], rows[:-1]+[rows[0]]):
            with self.assertRaises(ValueError):
                fixed_frozen_cases(plan, modified)
        cases = fixed_frozen_cases(plan, rows)
        answer, baseline, targets = outcomes(cases)
        for modified in (answer[:-1], answer[:-1]+[answer[0]]):
            with self.assertRaises(ValueError):
                evaluate_flat_answers(
                    cases, modified, baseline, targets,
                    lambda a, t: 1.0,
                )

    def test_prompt_requires_single_strictly_older_source(self):
        cases = fixed_frozen_cases(*fixture())
        q, ev = cases[0]["question"], cases[0]["delivered_evidence"]
        for evidence in (
            [],
            ev*2,
            [dict(ev[0], observed_at="2023-03-10")],
            [dict(ev[0], scope="cross-scope")],
        ):
            with self.assertRaises(ValueError):
                flat_user_message(q, evidence)

    def test_zero_gold_scoring_does_not_become_success_claim(self):
        cases = fixed_frozen_cases(*fixture())
        rows, baseline, targets = outcomes(cases)
        report = evaluate_flat_answers(
            cases, rows, baseline, targets,
            lambda answer, target: None,
        )
        self.assertEqual(
            report["phases"]["transfer"]["all_planned_f1_delta_bounds"],
            [-1.0, 1.0],
        )
        self.assertFalse(report["independent_human_oracle_verified"])


if __name__ == "__main__":
    unittest.main()
