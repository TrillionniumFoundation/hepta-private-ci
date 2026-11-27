"""Immutable successful-run accounting, tamper checks; no model execution."""

from copy import deepcopy
import os
from pathlib import Path
import unittest

from stem_audit_archive import AuditError, PinnedArchive
from stem_strict_success_audit import (
    SOURCE,
    TREE,
    ZIP_SHA256,
    audit_records,
    audit_archive,
)


class StrictCompletedNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get("HEPTA_STEM_STRICT_ARCHIVE")
        if not path:
            raise unittest.SkipTest(
                "Immutable native artifact integration: run the dedicated strict evidence workflow"
            )
        cls.path = Path(path)
        archive = PinnedArchive(cls.path, ZIP_SHA256)
        try:
            cls.inputs = [
                archive.json("comparison/preregistered.json"),
                archive.jsonl("comparison/policy-predictions.jsonl"),
                archive.json("comparison/scored-policy-attempts.json"),
                archive.json("comparison/report.json"),
                archive.json("comparison/within-head-train-fit.json"),
                archive.json("comparison/post-policy-native-source-ceiling.json"),
                archive.json("comparison/reader-paired-no-evidence.json"),
                archive.json("chronology.json"),
            ]
            cls.provenance = (
                archive.read("tested-commit.txt").decode().strip(),
                archive.read("tested-tree.txt").decode().strip(),
            )
        finally:
            archive.close()

    def test_true_strict_frozen_source_result_not_false_lora_gain(self):
        output = audit_archive(self.path)
        self.assertEqual(self.provenance, (SOURCE, TREE))
        self.assertEqual(output["verified_member_digests"], 130)
        self.assertEqual(output["original_policy_succeeded"], 576)
        self.assertEqual(output["original_reader_actual_executions"], 44)
        self.assertEqual(output["isolated_no_evidence_reader_calls"], 32)
        self.assertEqual(output["emitted_citation_markers"], 0)
        self.assertEqual(output["native_longmemeval_future_time_pairs"], 1475)
        self.assertEqual(len(output["changed_source_rows"]), 1)
        changed = output["changed_source_rows"][0]
        self.assertEqual(changed["phase"], "retention")
        self.assertEqual(changed["stage"], 48)
        self.assertEqual(changed["before_weak_source"], 0)
        self.assertEqual(changed["after_weak_source"], 0)
        self.assertFalse(changed["changed_answer_bytes"])
        for arm, receipt in output["learned_vs_frozen"].items():
            self.assertEqual(receipt["matched_policy_attempts"], 96)
            self.assertEqual(receipt["test_transfer_top1_changes"], 0)
            self.assertEqual(receipt["observed_native_document_support_gains"], 0)
            self.assertFalse(receipt["independent_task_superiority"])
        self.assertFalse(output["production_accepted"])

    def test_missing_or_changed_raw_attempt_is_not_success(self):
        for mode in ("missing", "changed-answer", "failed", "changed-pool"):
            dataset = deepcopy(self.inputs)
            raw = dataset[1]
            if mode == "missing":
                raw.pop()
            elif mode == "changed-answer":
                raw[0]["answer"] = "fabricated post-run improvement"
            elif mode == "failed":
                raw[0]["status"] = "failed"
            else:
                raw[0]["pool_digest"] = "not-the-frozen-pool"
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_records(*dataset)

    def test_changed_reader_or_scoring_receipt_is_not_learning(self):
        for mode in ("model", "prompt", "scored-answer"):
            dataset = deepcopy(self.inputs)
            if mode == "model":
                dataset[1][0]["receipt"]["generator_identity"] = "forged-reader"
            elif mode == "prompt":
                dataset[1][0]["receipt"]["generator_profile"] = "another-prompt"
            else:
                dataset[2][0]["answer"] = "fake scoring-stage answer"
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_records(*dataset)

    def test_head_training_checkpoint_and_label_gate_cannot_be_promoted(self):
        for mode in ("lost-fit", "changed-head", "train-used-test", "released"):
            dataset = deepcopy(self.inputs)
            if mode == "lost-fit":
                dataset[4]["checkpoints"].pop()
            elif mode == "changed-head":
                dataset[4]["checkpoints"][0]["updated_head_sha256"] = "1" * 64
            elif mode == "train-used-test":
                dataset[4]["checkpoints"][0]["heldout_annotations_consulted"] = True
            else:
                dataset[3]["production_accepted"] = True
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_records(*dataset)

    def test_source_coverage_aggregation_and_frozen_binding_are_recomputed(self):
        for damage in ("retrieval-miss-count", "source-scorer", "candidate-count"):
            dataset = deepcopy(self.inputs)
            if damage == "retrieval-miss-count":
                dataset[5]["phases"]["test"]["support_missing_from_pool"] += 1
            elif damage == "source-scorer":
                registered = next(
                    x
                    for x in dataset[5]["decisions"]
                    if x["phase"] == "test"
                    and x["weak_native_support_resolved"]
                    and not x["native_source_unanswerable"]
                )
                frozen = next(
                    x
                    for x in dataset[2]
                    if x["stage"] == 48
                    and x["phase"] == "test"
                    and x["arm"] == "frozen_rerank"
                    and x["question_id"] == registered["question_id"]
                )
                frozen["source_choice_correct"] = 1 - frozen["source_choice_correct"]
            else:
                dataset[5]["decisions"][0]["candidate_count"] += 1
            with self.subTest(damage=damage), self.assertRaises(AuditError):
                audit_records(*dataset)

    def test_source_census_and_no_evidence_denominators_stay_complete(self):
        for mode in ("lost-source", "no-reader-control", "noncomparable-time"):
            dataset = deepcopy(self.inputs)
            if mode == "lost-source":
                dataset[5]["decisions"].pop()
            elif mode == "no-reader-control":
                dataset[6]["matched_pairs"] = 31
            else:
                dataset[7]["datasets"]["longmemeval"]["unknown"] += 1
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_records(*dataset)


if __name__ == "__main__":
    unittest.main()
