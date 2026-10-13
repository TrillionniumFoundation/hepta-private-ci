"""Fail-closed tests for the immutable successful native Stem artifact.

These are not simulated QA successes; each enabled test consumes the exact
byte-pinned model-run ZIP and mutates copies to assert rejection.
"""
import copy
import os
from pathlib import Path
import unittest

from stem_audit_archive import PinnedArchive
from stem_audit_completed_run import (
    ZIP_SHA256, audit_pinned_zip, reconcile,
)


class CompletedNativeStemAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        supplied = os.environ.get("HEPTA_PINNED_COMPLETED_STEM_ZIP")
        if not supplied:
            raise unittest.SkipTest(
                "pinned artifact unavailable; dedicated audit downloads it"
            )
        cls.path = Path(supplied)
        archive = PinnedArchive(cls.path, ZIP_SHA256)
        try:
            cls.plan = archive.json("comparison/preregistered.json")
            cls.pred = archive.jsonl("comparison/policy-predictions.jsonl")
            cls.scored = archive.json("comparison/scored-policy-attempts.json")
            cls.report = archive.json("comparison/report.json")
        finally:
            archive.close()

    def check(self, *, plan=None, predictions=None, scored=None, report=None):
        return reconcile(
            self.plan if plan is None else plan,
            self.pred if predictions is None else predictions,
            self.scored if scored is None else scored,
            self.report if report is None else report,
        )

    def test_original_complete_run_is_genuine_but_not_learning_success(self):
        receipt = audit_pinned_zip(self.path)
        self.assertEqual(receipt["verified_internal_sha256_members"], 130)
        self.assertEqual(receipt["genuine_model_policy_successes"], 576)
        self.assertEqual(receipt["real_reader_call_count"], 44)
        self.assertEqual(receipt["isolated_no_evidence_reader_attempts"], 32)
        self.assertFalse(receipt["independently_adjudicated_qa_gain"])
        self.assertFalse(receipt["production_accepted"])

    def test_single_changed_source_did_not_improve_or_change_answer(self):
        result = self.check()
        self.assertEqual(len(result["changed_selected_candidates"]), 1)
        changed = result["changed_selected_candidates"][0]
        self.assertEqual(changed["question_id"], "locomo:conv-43/q217")
        self.assertEqual(changed["frozen_weak_native_support"], 0)
        self.assertEqual(changed["learned_weak_native_support"], 0)
        self.assertFalse(changed["answer_changed"])
        self.assertEqual(sum(x["changed_answer_bytes"] for x in
                             result["candidate_selection_and_answers_by_arm"].values()), 0)

    def test_missing_or_duplicate_or_fake_policy_is_not_a_smaller_census(self):
        for kind in ("missing", "duplicate", "fake"):
            records = copy.deepcopy(self.pred)
            if kind == "missing":
                records.pop()
            elif kind == "duplicate":
                records[-1] = records[0]
            else:
                records[-1]["arm"] = "fabricated-win"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.check(predictions=records)

    def test_fabricated_posthoc_answer_is_rejected(self):
        rows = copy.deepcopy(self.scored)
        rows[0]["answer"] = "New answer written after model generation"
        with self.assertRaisesRegex(ValueError, "original answer"):
            self.check(scored=rows)

    def test_unsupported_selected_source_cannot_be_marked_gain(self):
        rows = copy.deepcopy(self.scored)
        for row in rows:
            if (row["stage"] == 48 and row["phase"] == "retention"
                    and row["question_id"] == "locomo:conv-43/q217"
                    and row["arm"] == "lineage_lora_gated"):
                row["source_choice_correct"] = 1
        with self.assertRaisesRegex(ValueError, "no confirmed learning benefit"):
            self.check(scored=rows)

    def test_training_steps_cannot_be_promoted_to_new_pair_examples(self):
        state = copy.deepcopy(self.report)
        state["adapter_pair_opportunities"]["checkpoint_prefixes"]["48"][
            "positive_negative_pair_eligible_questions"
        ] = 40
        with self.assertRaisesRegex(ValueError, "contrastive train"):
            self.check(report=state)

    def test_changed_prompt_or_candidate_pool_cannot_fake_a_result(self):
        cases = copy.deepcopy(self.pred)
        for row in cases:
            if row["arm"] == "gated":
                row["pool_digest"] = "forged"
                break
        with self.assertRaisesRegex(ValueError, "pool/family drift"):
            self.check(predictions=cases)

    def test_reader_reuse_and_production_status_cannot_be_fabricated(self):
        state = copy.deepcopy(self.report)
        state["reader"]["cache_hits"] += 1
        with self.assertRaisesRegex(ValueError, "Reader attempt"):
            self.check(report=state)
        state = copy.deepcopy(self.report)
        state["production_accepted"] = True
        with self.assertRaisesRegex(ValueError, "semantic citation or production"):
            self.check(report=state)

    def test_missing_support_is_eight_retrieval_failures_not_eight_head_losses(self):
        receipt = self.check()
        ceiling = receipt["source_ceiling"]
        self.assertEqual(ceiling["native_answerable_with_resolved_weak_support"], 25)
        self.assertEqual(ceiling["native_unanswerable"], 7)
        self.assertEqual(ceiling["weak_support_missing_from_candidates"], 8)
        self.assertEqual(ceiling["weak_support_retrieved_but_frozen_top1_missed"], 4)
        self.assertEqual(ceiling["frozen_top1_selected_weak_native_support"], 13)


if __name__ == "__main__":
    unittest.main()
