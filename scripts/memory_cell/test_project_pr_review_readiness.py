"""Provenance negative controls; fixtures are not human reviewer decisions."""

from copy import deepcopy
from pathlib import Path
import os
import unittest

from project_first_parent_diff_handoff import assemble, checked_archive
from project_pr_review_readiness import assess

ARCHIVE = Path(os.environ.get("HEPTA_ORIGINAL_FOUR_PROJECT_ZIP", "/mnt/data/github-actions-artifact-11779111741.zip"))


class ReviewReadinessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = assemble(checked_archive(ARCHIVE))

    def test_complete_actual_source_review_census(self):
        result = assess(self.real)
        self.assertEqual(result["fixed_questions"], 16)
        self.assertEqual(result["original_file_bindings"], 80)
        self.assertEqual(result["bucket_counts"], {
            "source_first_review_candidate": 10,
            "renamed_prior_path_unresolved": 2,
            "multi_parent_baseline_unresolved": 4,
        })
        self.assertEqual(result["qualified_reader_tasks"], 0)
        self.assertEqual(result["actual_human_review_verdicts"], 0)
        self.assertFalse(result["production_accepted"])
        self.assertTrue(all(not task["reader_task_eligible"] for task in result["tasks"]))

    def test_actual_historical_partitions_stay_fixed(self):
        result = assess(self.real)
        self.assertEqual(result["partition_counts"], {"train": 4, "selection": 4, "evaluation": 8})
        self.assertEqual(result["original_first_parent_diff_file_bindings"], 27)
        self.assertTrue(all(task["requires_full_pr_historical_baseline"] for task in result["tasks"]))

    def test_duplicate_or_lost_questions_rejected(self):
        for how in ("drop", "duplicate", "change_kind"):
            data = deepcopy(self.real)
            if how == "drop":
                data["cases"].pop()
            elif how == "duplicate":
                data["cases"][2] = deepcopy(data["cases"][1])
            else:
                data["cases"][0]["task_id"] += "/unknown"
            with self.subTest(how=how), self.assertRaises(ValueError):
                assess(data)

    def test_fake_semantics_answers_rejected(self):
        for key, value in (
            ("human_reviewer_verdict", "accepted"),
            ("source_preview_sufficient_for_answer", True),
            ("no_model_answer_available", False),
            ("answer_gold", "fake"),
        ):
            data = deepcopy(self.real)
            data["cases"][0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                assess(data)

    def test_duplicate_or_changed_file_identity_rejected(self):
        for how in ("duplicate", "head", "drop"):
            data = deepcopy(self.real)
            files = data["cases"][0]["files"]
            if how == "duplicate":
                files[1] = deepcopy(files[0])
            elif how == "head":
                files[0]["head_git_blob_sha1"] = "f" * 40
            else:
                files.pop()
            with self.subTest(how=how), self.assertRaises(ValueError):
                assess(data)

    def test_rewrite_first_parent_preview_rejected(self):
        for how in ("bytes", "relabel"):
            data = deepcopy(self.real)
            f = next(f for f in data["cases"][0]["files"] if f["diff"])
            if how == "bytes":
                f["diff"]["text"] += "bogus\n"
            else:
                f["parent_classification"] = "ambiguous-multi-parent-head"
            with self.subTest(how=how), self.assertRaises(ValueError):
                assess(data)

    def test_changed_parent_census_and_partition_denied(self):
        for how in ("counts", "partition"):
            data = deepcopy(self.real)
            if how == "counts":
                data["comparison_counts"]["ambiguous-multi-parent-head"] = 30
            else:
                data["cases"][0]["partition"] = "evaluation"
            with self.subTest(how=how), self.assertRaises(ValueError):
                assess(data)

    def test_paired_questions_must_share_same_original_sources(self):
        data = deepcopy(self.real)
        data["cases"][1]["files"][0]["source_path"] = "invented.rs"
        with self.assertRaises(ValueError):
            assess(data)


if __name__ == "__main__":
    unittest.main()
