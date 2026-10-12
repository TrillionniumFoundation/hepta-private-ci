"""Source-family precommit contracts; no model, reviewed gold, or live fleet."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from project_pr_family_extension import (
    PARTITIONS,
    PREVIOUS_SHA,
    audit,
    prepare,
    unsigned_review_worklist,
)

ROOT = Path(__file__).resolve().parent
EXTENSION = ROOT / "data/real-project-pr-independent-extension-20261012.json"
PREVIOUS = ROOT / "data/real-project-pr-source-cut-20261012.json"


class ProjectExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = EXTENSION.read_bytes()
        cls.manifest = json.loads(cls.content)

    def test_real_source_only_six_project_extension(self):
        observed = audit(self.manifest)
        self.assertEqual(observed["combined_project_proxies"], 10)
        self.assertEqual(observed["original_commit_ids_recorded"], 14)
        self.assertEqual(observed["original_blob_ids_recorded"], 32)
        self.assertEqual(observed["tasks_requiring_real_review"], 12)
        self.assertIsNone(observed["independent_effective_n"])
        self.assertFalse(observed["decoded_source_bytes_verified"])
        self.assertFalse(observed["production_accepted"])

    def test_all_worklist_items_lack_gold_predictions_and_authority(self):
        plan = unsigned_review_worklist(self.manifest)
        self.assertEqual(len(plan["tasks"]), 12)
        self.assertTrue(plan["not_model_ready"])
        self.assertEqual(
            {x["source_project"] for x in plan["tasks"]},
            set(PARTITIONS),
        )
        for task in plan["tasks"]:
            self.assertIsNone(task["answer"])
            self.assertIsNone(task["model_prediction"])
            self.assertEqual(task["reviewer_verdict"], "unreviewed")
            self.assertFalse(task["independent_reviewer_authenticated"])
            self.assertFalse(task["decoded_code_verified"])

    def test_real_previous_manifest_is_required_and_output_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "worklist.json"
            result = prepare(
                EXTENSION,
                PREVIOUS,
                out,
                expected_sha256=sha256(self.content).hexdigest(),
            )
            self.assertEqual(result["additional_public_prs"], 6)
            item = json.loads(out.read_text())
            self.assertEqual(item["previous_corpus_sha256"], PREVIOUS_SHA)
            with self.assertRaises(FileExistsError):
                prepare(
                    EXTENSION,
                    PREVIOUS,
                    out,
                    expected_sha256=sha256(self.content).hexdigest(),
                )
            with self.assertRaises(ValueError):
                prepare(
                    EXTENSION,
                    PREVIOUS,
                    Path(directory) / "invalid.json",
                    expected_sha256="0" * 64,
                )

    def test_future_modified_metadata_and_commit_are_rejected(self):
        for key, value in (
            ("updated_at", "2026-10-13T00:00:00Z"),
            ("head_committed_at", "2026-10-13T00:00:00Z"),
            ("created_at", "2026-10-13T00:00:00Z"),
        ):
            bad = deepcopy(self.manifest)
            bad["cases"][0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                audit(bad)
        bad = deepcopy(self.manifest)
        bad["cases"][0]["commits"][0]["committed_at"] = (
            "2026-10-13T00:00:00Z"
        )
        with self.assertRaises(ValueError):
            audit(bad)

    def test_target_leak_or_forged_independent_review_reject(self):
        for key, value in (
            ("no_gold_answers", False),
            ("independent_review_certified", True),
            ("effective_independent_n", 10),
            ("source_bytes_not_yet_verified", False),
            ("production_accepted", True),
        ):
            bad = deepcopy(self.manifest)
            bad[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                audit(bad)
        bad = deepcopy(self.manifest)
        bad["cases"][0]["reference_answer"] = "leak"
        with self.assertRaises(ValueError):
            audit(bad)

    def test_cross_partition_and_identity_substitution_fail(self):
        for change in ("partition", "repo", "head_sha", "files"):
            bad = deepcopy(self.manifest)
            if change == "partition":
                bad["cases"][0][change] = "train"
            elif change == "repo":
                bad["cases"][0][change] = "numpy/numpy"
            elif change == "head_sha":
                bad["cases"][0][change] = "a" * 40
            else:
                bad["cases"][0]["files"][0]["blob_sha"] = (
                    bad["cases"][1]["files"][0]["blob_sha"]
                )
            with self.subTest(field=change), self.assertRaises(ValueError):
                audit(bad)

    def test_unsafe_changed_file_and_missing_case_reject(self):
        bad = deepcopy(self.manifest)
        bad["cases"][0]["files"][0]["path"] = "../secret"
        with self.assertRaises(ValueError):
            audit(bad)
        bad = deepcopy(self.manifest)
        bad["cases"][0]["files"][0]["changes"] += 1
        with self.assertRaises(ValueError):
            audit(bad)
        bad = deepcopy(self.manifest)
        bad["cases"].pop()
        with self.assertRaises(ValueError):
            audit(bad)


if __name__ == "__main__":
    unittest.main()
