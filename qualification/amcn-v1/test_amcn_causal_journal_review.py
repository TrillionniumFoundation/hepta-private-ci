"""Mock-only journal integrity regressions, never pretrained model executions."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import amcn_causal_journal_review as audit
import amcn_causal_reader_generation as reader
import amcn_causal_task_audit as contract
from test_amcn_causal_reader_generation import Fake
from test_amcn_causal_task_audit import fixture, sha


class PhysicalJournalSourceCensus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "original"
        self.plan, _, _ = fixture()
        self.plan["prompt_sha256"] = reader.PROMPT_SHA
        for case in self.plan["cases"]:
            for arm in contract.ARMS:
                case["arm_plans"][arm]["planned_request_sha256"] = contract.request_digest(
                    self.plan, case, arm, {x["source_id"]: x for x in case["sources"]})
        self.external = {"source_plan_sha256": sha("precommitted-independent-source"),
                         "material_manifest_digest": sha("synthetic-only-reader-material")}
        reader.generate_original(self.plan, self.external["material_manifest_digest"],
                                 Fake(self.plan), self.folder,
                                 source_sha256=self.external["source_plan_sha256"])
        self.update_external_pins()

    def update_external_pins(self):
        for key, path in (("original_plan_sha256", "frozen-plan.json"),
                          ("original_answers_file_sha256", "answers.json"),
                          ("original_seal_file_sha256", "sealed-original.json")):
            self.external[key] = sha256((self.folder / path).read_bytes()).hexdigest()

    def review(self):
        return audit.audit_original_journal(self.folder, **self.external)

    def load(self, name):
        return json.loads((self.folder / name).read_bytes())

    def change_json(self, name, obj):
        (self.folder / name).write_bytes(contract.canonical(obj) + b"\n")

    def jsonl(self, name):
        return [json.loads(x) for x in (self.folder / name).read_text().splitlines()]

    def change_jsonl(self, name, rows):
        (self.folder / name).write_bytes(b"".join(contract.canonical(x) + b"\n"
                                                         for x in rows))

    def test_all_original_attempts_recounted_but_no_authority(self):
        report = self.review()
        self.assertEqual(report["fully_recounted_answer_attempts"], 54)
        self.assertEqual(report["question_count"], 6)
        self.assertEqual(report["original_failed_attempts"], 0)
        self.assertEqual(set(report["original_per_arm_counters"]), set(contract.ARMS))
        self.assertTrue(all(v["attempts"] == 6 for v in
                            report["original_per_arm_counters"].values()))
        self.assertFalse(report["independently_authenticated_pretrained_model"])
        self.assertIsNone(report["independent_semantic_task_correctness"])
        self.assertFalse(report["superiority_claim"])

    def test_tampered_original_answers_never_pass_original_pin(self):
        answers = self.load("answers.json")
        answers[0]["raw_answer"] = "altered without re-inference"
        self.change_json("answers.json", answers)
        with self.assertRaisesRegex(contract.Refused, "externally pinned"):
            self.review()

    def test_changed_pin_cannot_hide_different_append_only_rows(self):
        answers = self.load("answers.json")
        answers[0]["raw_answer"] = "changed"
        self.change_json("answers.json", answers)
        self.update_external_pins()  # even an unqualified new caller pin fails
        with self.assertRaisesRegex(contract.Refused, "append-only"):
            self.review()

    def test_reordered_prestart_records_denied(self):
        starts = self.jsonl("starts.jsonl")
        starts[1], starts[2] = starts[2], starts[1]
        self.change_jsonl("starts.jsonl", starts)
        with self.assertRaisesRegex(contract.Refused, "out-of-order"):
            self.review()

    def test_missing_start_denied(self):
        starts = self.jsonl("starts.jsonl")
        self.change_jsonl("starts.jsonl", starts[:-1])
        with self.assertRaisesRegex(contract.Refused, "missing/duplicate"):
            self.review()

    def test_duplicate_answer_row_denied(self):
        rows = self.jsonl("answers.jsonl")
        rows[3] = deepcopy(rows[2])
        self.change_jsonl("answers.jsonl", rows)
        with self.assertRaisesRegex(contract.Refused, "complete answers"):
            self.review()

    def test_missing_failed_state_denied(self):
        statuses = self.jsonl("attempt-status.jsonl")
        statuses[0]["status"] = "failed"
        statuses[0]["exception_type"] = "RuntimeError"
        self.change_jsonl("attempt-status.jsonl", statuses)
        with self.assertRaisesRegex(contract.Refused, "contradicts"):
            self.review()

    def test_fake_citation_cannot_be_declared_in_answer_rows(self):
        rows = self.jsonl("answers.jsonl")
        rows[0]["emitted_source_ids"] = ["fake source"]
        self.change_jsonl("answers.jsonl", rows)
        answers = self.load("answers.json")
        answers[0]["emitted_source_ids"] = ["fake source"]
        self.change_json("answers.json", answers)
        seal = self.load("sealed-original.json")
        seal["answers_sha256"] = contract.digest(answers)
        seal["raw_answer_rows_sha256"] = contract.bytes_sha(
            (self.folder / "answers.jsonl").read_bytes())
        self.change_json("sealed-original.json", seal)
        self.update_external_pins()  # coherent, but fabricated citations must fail
        with self.assertRaisesRegex(contract.Refused, "citation labels"):
            self.review()

    def test_original_execution_receipt_not_arbitrary_signed_hash(self):
        rows = self.jsonl("answers.jsonl")
        rows[0]["reader_execution_receipt_sha256"] = sha("invented")
        self.change_jsonl("answers.jsonl", rows)
        answers = self.load("answers.json")
        answers[0]["reader_execution_receipt_sha256"] = sha("invented")
        self.change_json("answers.json", answers)
        seal = self.load("sealed-original.json")
        seal["answers_sha256"] = contract.digest(answers)
        seal["raw_answer_rows_sha256"] = contract.bytes_sha(
            (self.folder / "answers.jsonl").read_bytes())
        self.change_json("sealed-original.json", seal)
        self.update_external_pins()
        with self.assertRaisesRegex(contract.Refused, "receipt was not derived"):
            self.review()

    def test_changed_model_material_boundaries_denied(self):
        self.external["material_manifest_digest"] = sha("different model")
        with self.assertRaisesRegex(contract.Refused, "Reader/material"):
            self.review()

    def test_false_failure_total_denied(self):
        seal = self.load("sealed-original.json")
        seal["failed_attempts"] = 2
        self.change_json("sealed-original.json", seal)
        self.update_external_pins()
        with self.assertRaisesRegex(contract.Refused, "failed original Reader work"):
            self.review()

    def test_duplicate_json_keys_fail_even_with_new_pin(self):
        (self.folder / "frozen-plan.json").write_bytes(b'{"a":1,"a":2}\n')
        self.update_external_pins()
        with self.assertRaisesRegex(contract.Refused, "duplicate"):
            self.review()

    def test_extra_raw_gold_file_denied(self):
        (self.folder / "original-gold.json").write_bytes(b'{}')
        with self.assertRaisesRegex(contract.Refused, "extra"):
            self.review()

    def test_symlink_seal_denied(self):
        location = self.folder / "sealed-original.json"
        raw = location.read_bytes()
        location.unlink()
        original = Path(self.tmp.name) / "untrusted-seal.json"
        original.write_bytes(raw)
        location.symlink_to(original)
        with self.assertRaisesRegex(contract.Refused, "linked"):
            self.review()

    def test_one_actual_failure_recounted_without_scoring_it(self):
        # A fresh independent mock-only trial ensures execution's failure path
        # has consistent durable start, status and original answer journals.
        other = Path(self.tmp.name) / "failed"
        reader.generate_original(self.plan, self.external["material_manifest_digest"],
                                 Fake(self.plan, fail_on=3), other,
                                 source_sha256=self.external["source_plan_sha256"])
        self.folder = other
        self.update_external_pins()
        report = self.review()
        self.assertEqual(report["original_failed_attempts"], 1)
        self.assertFalse(report["production_accepted"])


if __name__ == "__main__":
    unittest.main()
