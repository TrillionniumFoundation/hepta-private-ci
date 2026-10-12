"""Synthetic acceptance-boundary tests for same-Reader Shadow answer control."""

from dataclasses import asdict
from types import SimpleNamespace
import unittest

from native import Question, digest
from stem_pairwise_reader_comparison import (
    ARMS, PHASES, TEST_PHASES, STAGES,
    run_final_shadow_reader, review_final_shadow_reader,
)

READER = "immutable-reader"
PROFILE = "immutable-prompt"


def reader_receipt(q, evidence, text):
    """Authored deterministic fixture receipts, not pretrained executions."""
    return dict(
        generator_identity=READER,
        generator_profile=PROFILE,
        observable_query=asdict(q),
        delivered_evidence=list(evidence),
        canonical_request_digest=digest(
            (READER, PROFILE, asdict(q), evidence)
        ),
        question_digest=digest(asdict(q)),
        input_ids_digest=digest(
            (asdict(q), tuple(
                (item["label"], item["observed_at"], item["excerpt"])
                for item in evidence
            ))
        ),
        generated_ids_digest=digest(("emitted-fixture", text)),
        actual_reader_execution=True,
    )

SIX_ARMS = ("frozen_rerank", "prototype", "linear", "gated",
            "lineage_lora_gated", "independent_lora_gated")


def fixture():
    questions = {
        "train": [
            Question(f"train-{i}", "registered", "train-scope",
                     "What was written?", "2023-04-11")
            for i in range(48)
        ],
    }
    questions.update({
        phase: [
            Question(f"{phase}-{i}", "registered", f"scope-{phase}-{i}",
                     "What was written?", "2023-04-11")
            for i in range(8)
        ]
        for phase in PHASES
    })
    choices, frozen = [], []
    for stage in STAGES:
        for phase in PHASES:
            for q in questions[phase]:
                for arm in SIX_ARMS:
                    frozen.append(dict(
                        stage=stage, phase=phase, question_id=q.identity, arm=arm,
                        cell="general", family="frozen-family-" + q.identity,
                        status="succeeded", selected=0,
                        pool_digest="sealed-original-" + q.identity,
                        answer="BASE",
                        receipt=reader_receipt(q, get_evidence(q, 0), "BASE"),
                    ))
                for arm in ARMS:
                    changed = (
                        stage == 48 and phase == "test"
                        and q.identity == "test-0" and arm == "pairwise_gated"
                    )
                    choices.append(dict(
                        stage=stage, phase=phase, question_id=q.identity, arm=arm,
                        cell="general", family="frozen-family-" + q.identity,
                        status="succeeded",
                        selected=1 if changed else 0,
                        original_frozen_selected=0,
                        candidate_count=2, pool_digest="sealed-original-" + q.identity,
                        actual_reader_calls=0,
                        training_labels_or_test_gold_in_answer=False,
                    ))
    return questions, choices, frozen


def get_evidence(q, selected):
    return (dict(
        id="window-" + str(selected), label="E1", root="source-root",
        scope=q.scope, observed_at="2023-04-10",
        excerpt=("Updated evidence: GOOD" if selected else "Original evidence: BASE"),
    ),)


def answer(q, evidence, key):
    assert key.startswith("shadow-reader/48/")
    assert len(evidence) == 1
    raw = "GOOD" if evidence[0]["id"] == "window-1" else "BASE"
    return raw, reader_receipt(q, evidence, raw)


def target_map(questions):
    return {
        q.identity: SimpleNamespace(answer="GOOD")
        for phase in TEST_PHASES for q in questions[phase]
    }


def score(response, target):
    return float(response == target.answer)


class FrozenReaderShadowControlTests(unittest.TestCase):
    def prepare(self, generate=answer, get_source=get_evidence):
        questions, choices, frozen = fixture()
        raw = run_final_shadow_reader(
            questions, choices, frozen, get_source, generate,
            reader_identity=READER, reader_profile=PROFILE,
        )
        return questions, choices, frozen, raw

    def test_full_predeclared_32_control_rows_with_exact_reader_identity(self):
        q, shadows, frozen, records = self.prepare()
        self.assertEqual(len(shadows), 192)
        self.assertEqual(len(frozen), 576)
        self.assertEqual(len(records), 32)
        self.assertTrue(all(r["status"] == "succeeded" for r in records))
        self.assertEqual(sum(r["changed_frozen_selected_source"] for r in records), 1)
        self.assertTrue(all(not r["native_target_passed_to_generator"] for r in records))
        out = review_final_shadow_reader(records, frozen, target_map(q), score)
        self.assertEqual(out["per_phase_arm"]["test/pairwise_gated"]["source_changed"], 1)
        self.assertEqual(out["per_phase_arm"]["test/pairwise_gated"]["scored_matched_answers"], 8)
        self.assertAlmostEqual(
            out["per_phase_arm"]["test/pairwise_gated"]["mean_paired_diagnostic_f1_delta"],
            1/8,
        )
        self.assertFalse(out["independent_prospective_generalization"])
        self.assertFalse(out["production_accepted"])

    def test_generator_failure_remains_visible_in_full_denominator(self):
        def fail_one(q, ev, k):
            if q.identity == "test-0" and k.endswith("/pairwise_gated"):
                raise RuntimeError("isolated Reader unavailable")
            return answer(q, ev, k)
        questions, choices, frozen, raw = self.prepare(fail_one)
        self.assertEqual(sum(x["status"] == "failed" for x in raw), 1)
        report = review_final_shadow_reader(raw, frozen, target_map(questions), score)
        g = report["per_phase_arm"]["test/pairwise_gated"]
        self.assertEqual(g["attempted"], 8)
        self.assertEqual(g["missing_failed_or_unscorable"], 1)
        self.assertEqual(g["source_changed"], 1)
        self.assertEqual(g["changed_source_scored"], 0)
        self.assertEqual(g["changed_source_reader_unscored"], 1)
        self.assertEqual(g["changed_source_all_observed_f1_delta_bounds"], [-1, 1])
        self.assertEqual(g["scored_matched_answers"], 7)
        self.assertEqual(g["original_8_planned_f1_delta_bounds"], [-1/8, 1/8])

    def test_missing_shadow_attempt_does_not_trigger_reader(self):
        q, choices, frozen = fixture()
        for row in choices:
            if (row["stage"],row["phase"],row["question_id"],row["arm"]) == (
                48,"test","test-0","pairwise_gated"
            ):
                row.update(status="failed")
        calls = []
        def count(q, ev, k):
            calls.append(k)
            return answer(q,ev,k)
        raw = run_final_shadow_reader(
            q, choices, frozen, get_evidence, count,
            reader_identity=READER, reader_profile=PROFILE,
        )
        self.assertEqual(len(calls), 31)
        self.assertEqual(sum(x["status"] == "unavailable" for x in raw), 1)

    def test_changed_model_or_prompt_receipt_is_rejected_not_relabelled(self):
        for field in ("generator_identity", "generator_profile",
                      "observable_query", "delivered_evidence"):
            def wrong(q, ev, key):
                raw, receipt = answer(q, ev, key)
                receipt[field] = "wrong" if field != "delivered_evidence" else []
                return raw, receipt
            with self.subTest(field=field):
                q, choices, frozen, rows = self.prepare(wrong)
                self.assertTrue(all(r["status"] == "failed" for r in rows))

    def test_missing_or_duplicate_shadow_and_baseline_fail_before_model_call(self):
        for mode in ("missing-shadow", "duplicate-shadow", "missing-original"):
            q, choices, frozen = fixture()
            if mode == "missing-shadow":
                choices.pop()
            elif mode == "duplicate-shadow":
                choices[-1] = dict(choices[0])
            else:
                frozen.pop()
            calls = []
            def count(*args):
                calls.append(1)
                return answer(*args)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                run_final_shadow_reader(
                    q, choices, frozen, get_evidence, count,
                    reader_identity=READER, reader_profile=PROFILE,
                )
            self.assertFalse(calls)

    def test_cross_scope_evidence_is_never_a_success(self):
        def cross_scope(q, selected):
            return (dict(get_evidence(q,selected)[0], scope="another"),)
        q, choices, frozen, rows = self.prepare(get_source=cross_scope)
        self.assertTrue(all(row["status"] == "failed" for row in rows))

    def test_gold_review_rejects_duplicate_or_detached_frozen_families(self):
        q, choices, frozen, rows = self.prepare()
        with self.assertRaises(ValueError):
            review_final_shadow_reader(rows[:-1]+[dict(rows[0])], frozen,
                                       target_map(q), score)
        rows[0]["source_family"] = "unregistered-other"
        with self.assertRaises(ValueError):
            review_final_shadow_reader(rows, frozen, target_map(q), score)

    def test_no_gold_target_or_semantic_precision_is_authorized_by_generation(self):
        q, choices, frozen, rows = self.prepare()
        receipt = review_final_shadow_reader(rows, frozen, target_map(q), score)
        self.assertTrue(receipt["postpolicy_answer_targets_only"])
        self.assertIsNone(receipt["independent_semantic_citation_precision"])
        self.assertTrue(receipt["native_document_support_not_semantic_citation"])
        self.assertFalse(receipt["production_accepted"])


    def test_same_actual_reader_request_cannot_fabricate_a_new_answer(self):
        q, _, frozen, records = self.prepare()
        original = records[1]
        self.assertEqual(original["phase"], "test")
        self.assertEqual(original["arm"], "pairwise_gated")
        # The real changed-source row is a distinct request, not this control.
        same = next(r for r in records if r["phase"] == "test"
                    and r["question_id"] == "test-1"
                    and r["arm"] == "pairwise_linear")
        same["answer"] = "GOOD"
        with self.assertRaisesRegex(ValueError, "identical Reader input"):
            review_final_shadow_reader(records, frozen, target_map(q), score)

    def test_original_reader_request_token_and_answer_seals_are_rechecked(self):
        for side, key in (
            ("original", "canonical_request_digest"),
            ("original", "question_digest"),
            ("original", "input_ids_digest"),
            ("shadow", "canonical_request_digest"),
            ("shadow", "generated_ids_digest"),
        ):
            q, _, frozen, records = self.prepare()
            if side == "original":
                row = next(r for r in frozen if r["stage"] == 48
                           and r["phase"] == "test" and r["question_id"] == "test-0"
                           and r["arm"] == "frozen_rerank")
            else:
                row = next(r for r in records if r["phase"] == "test"
                           and r["question_id"] == "test-0"
                           and r["arm"] == "pairwise_linear")
            row["receipt"][key] = "1" * 64
            with self.subTest(side=side, key=key), self.assertRaises(ValueError):
                review_final_shadow_reader(records, frozen, target_map(q), score)

    def test_source_flip_does_not_imply_a_changed_reader_input(self):
        q, _, frozen, records = self.prepare()
        flip = next(r for r in records if r["phase"] == "test"
                    and r["question_id"] == "test-0"
                    and r["arm"] == "pairwise_gated")
        baseline = next(r for r in frozen if r["stage"] == 48
                        and r["phase"] == "test" and r["question_id"] == "test-0"
                        and r["arm"] == "frozen_rerank")
        # Different source-window IDs can render the same model-visible bytes.
        flip["receipt"]["input_ids_digest"] = baseline["receipt"]["input_ids_digest"]
        with self.assertRaisesRegex(ValueError, "identical Reader input"):
            review_final_shadow_reader(records, frozen, target_map(q), score)

    def test_unchanged_selected_source_must_keep_exact_delivered_evidence(self):
        q, _, frozen, records = self.prepare()
        same = next(r for r in records if r["phase"] == "test"
                    and r["question_id"] == "test-1"
                    and r["arm"] == "pairwise_linear")
        same["receipt"]["delivered_evidence"][0]["excerpt"] = "altered source"
        with self.assertRaises(ValueError):
            review_final_shadow_reader(records, frozen, target_map(q), score)


if __name__ == "__main__":
    unittest.main()
