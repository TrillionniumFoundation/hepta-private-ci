"""Offline adversarial controls. Fixtures do not authenticate human evidence."""

import copy
import json
import os
import sys
import types
import unittest
from pathlib import Path

try:
    import project_pr_source_materialize
except ImportError:
    shim = types.ModuleType("project_pr_source_materialize")
    shim.decode_blob = lambda obj, oid: (_ for _ in ()).throw(RuntimeError("no real API in fixture"))
    shim.github_json = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("no network in fixture"))
    sys.modules["project_pr_source_materialize"] = shim

from project_first_parent_diff_handoff import checked_archive, git_blob, sha
from project_merge_two_parent_diff_handoff import bound_rows, produce

SOURCE = Path(os.environ.get("HEPTA_ORIGINAL_FOUR_PROJECT_ZIP", "/mnt/data/github-actions-artifact-11779111741.zip"))


def model_fixture():
    files = checked_archive(SOURCE)
    files = dict(files)
    data = json.loads(files["merge-concordance/concordance.json"])
    versions = {"numpy/numpy": b"before NumPy controlled fixture\n", "astral-sh/ruff": b"before Ruff controlled fixture\n"}
    for row in data["rows"]:
        first = {"blob_sha": row["head_blob_sha1"], "mode": "100644"}
        second = {"blob_sha": git_blob(versions[row["project"]]), "mode": "100644"}
        row["parent_entries"] = ([first, second] if row["classification"] == "parents-diverge" else [first, None])
    files["merge-concordance/concordance.json"] = json.dumps(data, sort_keys=True).encode()
    ready = json.loads(files["merge-concordance/READY.json"])
    ready["concordance_sha256"] = sha(files["merge-concordance/concordance.json"])
    files["merge-concordance/READY.json"] = json.dumps(ready).encode()
    return files, versions


class TwoParentReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = checked_archive(SOURCE)

    def test_unmodified_real_merge_census(self):
        rows, questions = bound_rows(self.real)
        self.assertEqual(len(rows), 31)
        self.assertEqual(len(questions), 4)
        self.assertEqual(sum(r[0]["classification"] == "parents-diverge" for r in rows), 30)
        self.assertEqual(sum(r[0]["classification"] == "absent-one" for r in rows), 1)

    def test_synthetic_two_parent_alternatives_keep_uncertainty(self):
        files, raw = model_fixture()
        seen = set()

        def fetch(project, oid):
            seen.add((project, oid))
            return raw[project]

        result = produce(files, fetch)
        self.assertEqual(result["merge_file_count"], 31)
        self.assertEqual(result["review_task_count"], 4)
        self.assertEqual(result["independently_git_sha1_verified_new_parent_blobs"], 2)
        self.assertEqual(len(seen), 2)
        self.assertFalse(result["complete_pr_base_diff_certified"])
        self.assertEqual(result["human_sufficient_evidence_verdicts"], 0)
        self.assertFalse(result["production_accepted"])
        for task in result["review_tasks"]:
            self.assertEqual(task["reviewer_verdict"], "unreviewed")
            for row in task["files"]:
                self.assertEqual(len(row["both_parent_alternatives"]), 2)
                self.assertTrue(row["no_uniquely_certified_previous_version"])
                for view in row["both_parent_alternatives"]:
                    if view["previous_exists_at_same_path"]:
                        self.assertIsNotNone(view["previous_sha256"])

    def test_parent_blob_injection_rejected(self):
        files, raw = model_fixture()
        with self.assertRaisesRegex(ValueError, "Git SHA-1"):
            produce(files, lambda project, sha: b"different from registered parent")

    def test_missing_parent_ref_fails_closed(self):
        files, _ = model_fixture()
        merge = json.loads(files["merge-concordance/concordance.json"])
        merge["rows"][1]["parent_entries"][1] = None
        files["merge-concordance/concordance.json"] = json.dumps(merge, sort_keys=True).encode()
        ready = json.loads(files["merge-concordance/READY.json"])
        ready["concordance_sha256"] = sha(files["merge-concordance/concordance.json"])
        files["merge-concordance/READY.json"] = json.dumps(ready).encode()
        with self.assertRaisesRegex(ValueError, "classification"):
            bound_rows(files)

    def test_changed_original_manifest_hash_denied(self):
        files = dict(self.real)
        data = json.loads(files["merge-concordance/READY.json"])
        data["source_manifest_sha256"] = "f" * 64
        files["merge-concordance/READY.json"] = json.dumps(data).encode()
        with self.assertRaises(ValueError):
            bound_rows(files)

    def test_changed_classification_census_denied(self):
        files = dict(self.real)
        merge = json.loads(files["merge-concordance/concordance.json"])
        merge["classification_counts"] = {"parents-diverge": 31}
        files["merge-concordance/concordance.json"] = json.dumps(merge, sort_keys=True).encode()
        with self.assertRaises(ValueError):
            bound_rows(files)

    def test_no_unreviewed_gold_answer_allowed(self):
        files = dict(self.real)
        questions = json.loads(files["unsigned-first-parent-review.json"])
        case = next(q for q in questions["questions"] if q["source_project"] == "numpy/numpy" and q["source_pr"] == 32523)
        case["answer_gold"] = "imputed answer"
        files["unsigned-first-parent-review.json"] = json.dumps(questions).encode()
        with self.assertRaisesRegex(ValueError, "gold"):
            bound_rows(files)

    def test_duplicate_or_missing_merge_row_rejected(self):
        for how in ("duplicate", "missing"):
            files = dict(self.real)
            obj = json.loads(files["merge-concordance/concordance.json"])
            if how == "duplicate":
                obj["rows"][1] = copy.deepcopy(obj["rows"][0])
            else:
                obj["rows"].pop()
            files["merge-concordance/concordance.json"] = json.dumps(obj, sort_keys=True).encode()
            ready = json.loads(files["merge-concordance/READY.json"])
            ready["concordance_sha256"] = sha(files["merge-concordance/concordance.json"])
            files["merge-concordance/READY.json"] = json.dumps(ready).encode()
            with self.subTest(how=how), self.assertRaises(ValueError):
                bound_rows(files)

    def test_original_source_zip_pin_rejects_changed_outer_bytes(self):
        with self.assertRaisesRegex(ValueError, "SHA mismatch|pinned source ZIP mismatch"):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "changed.zip"
                p.write_bytes(SOURCE.read_bytes() + b"changed")
                checked_archive(p)


if __name__ == "__main__":
    unittest.main()