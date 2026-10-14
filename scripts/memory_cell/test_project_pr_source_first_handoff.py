"""Research-only tests: never mock human review as a passing verdict."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest

from project_first_parent_diff_handoff import assemble, checked_archive
from project_pr_source_first_handoff import compile_intake

ORIGINAL = Path(
    os.environ.get(
        "HEPTA_ORIGINAL_FOUR_PROJECT_ZIP",
        "/mnt/data/github-actions-artifact-11779111741.zip",
    )
)


class HumanIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = assemble(checked_archive(ORIGINAL))

    def test_actual_sha_bound_source_first_packet(self):
        report = compile_intake(self.source)
        self.assertEqual(report["all_registered_questions"], 16)
        self.assertEqual(report["preliminary_review_requested_questions"], 10)
        self.assertEqual(report["excluded_as_unresolved_questions"], 6)
        self.assertEqual(report["previewed_unique_file_count"], 21)
        self.assertEqual(len(report["source_first_cases"]), 5)
        self.assertEqual(len(report["blocked_cases"]), 3)
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["reviewed_with_real_independent_humans"])

    def test_actual_excerpts_are_byte_identity_preserved(self):
        value = compile_intake(self.source)
        for case in value["source_first_cases"]:
            for f in case["files"]:
                preview = f["source_excerpt"]
                if preview["text"] is not None:
                    self.assertEqual(
                        hashlib.sha256(preview["text"].encode()).hexdigest(),
                        preview["sha256"],
                    )
                self.assertFalse(f["complete_historical_pr_base_diff_certified"])
            self.assertTrue(all(q["reviewer_response"] is None for q in case["questions"]))

    def test_historical_merge_cases_are_not_put_in_review_candidates(self):
        report = compile_intake(self.source)
        self.assertEqual(
            sorted(x["pull_number"] for x in report["blocked_cases"]),
            [28828, 32523, 162467],
        )
        self.assertEqual(
            set(x["reason"] for x in report["blocked_cases"]),
            {"multi_parent_baseline_unresolved", "renamed_prior_path_unresolved"},
        )
        self.assertEqual(report["reader_task_admitted"], 0)

    def test_mutated_source_ref_cannot_be_published(self):
        obj = deepcopy(self.source)
        obj["cases"][0]["files"][0]["head_git_blob_sha1"] = "f" * 40
        with self.assertRaises(ValueError):
            compile_intake(obj)

    def test_fake_semantic_verdict_or_answer_denied(self):
        for key, val in (("human_reviewer_verdict", "pass"), ("source_preview_sufficient_for_answer", True), ("answer_gold", "fake")):
            obj = deepcopy(self.source)
            obj["cases"][0][key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                compile_intake(obj)

    def test_deletion_and_duplicate_original_task_denied(self):
        for change in ("delete", "duplicate"):
            obj = deepcopy(self.source)
            if change == "delete":
                obj["cases"].pop()
            else:
                obj["cases"][-1] = deepcopy(obj["cases"][0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                compile_intake(obj)

    def test_mutated_original_diff_preview_denied(self):
        obj = deepcopy(self.source)
        obj["cases"][0]["files"][0]["diff"]["text"] += "injected\n"
        with self.assertRaises(ValueError):
            compile_intake(obj)

    def test_external_readonly_sources_are_not_promoted(self):
        result = compile_intake(self.source)
        for item in result["source_first_cases"]:
            self.assertTrue(item["preliminary_review_only"])
            for question in item["questions"]:
                self.assertFalse(question["independently_adjudicated"])
                self.assertFalse(question["reader_task_eligible"])
                self.assertIsNone(question["reviewer_identity"])
                self.assertIsNone(question["reviewer_attestation"])
                self.assertIsNone(question["source_sufficient_for_this_question"])
        self.assertFalse(result["secure_reviewer_access_boundaries_established_by_git_artifact"])


if __name__ == "__main__":
    unittest.main()
