"""Synthetic parent trees, never human or model-produced answer evidence."""

import base64
from copy import deepcopy
import unittest

from project_pr_merge_concordance import classify, inspect
from project_pr_source_materialize import ObjectReader, blob_sha
from test_project_pr_parent_context import SourceFixtures, sha


class MergeConcordanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = SourceFixtures()
        self.parent, _ = self.fixture.inspect()
        self.case = next(
            c for c in self.fixture.manifest["cases"] if len(c["parents"]) == 2
        )

    def install(self, parent_sha, path, old_blob):
        repo = self.case["repo"]
        root = self.fixture.objects[repo, "commits", parent_sha]["tree"]["sha"]
        for part in path.split("/")[:-1]:
            tree = self.fixture.objects[repo, "trees", root]
            item = next((x for x in tree["tree"] if x["path"] == part), None)
            if item is None:
                child = sha(root + "/" + part)
                item = dict(path=part, type="tree", mode="040000", sha=child)
                tree["tree"].append(item)
                self.fixture.objects[repo, "trees", child] = dict(
                    sha=child,
                    truncated=False,
                    tree=[],
                )
            root = item["sha"]
        self.fixture.objects[repo, "trees", root]["tree"].append(
            dict(path=path.split("/")[-1], type="blob", mode="100644", sha=old_blob)
        )

    def run_comparison(self, parent=None):
        seen = {}

        def retain(oid, raw):
            seen[oid] = raw
            return "common-previous/" + oid + ".blob"

        report = inspect(
            self.fixture.manifest,
            parent if parent is not None else self.parent,
            ObjectReader(self.fixture.fetch),
            retain,
        )
        return report, seen

    def test_original_merge_cases_remain_unknown_without_parent_blobs(self):
        result, stored = self.run_comparison()
        self.assertEqual(result["merge_file_count"], 31)
        self.assertEqual(result["classification_counts"], {"absent-both": 31})
        self.assertFalse(stored)
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(result["independent_review"])

    def test_identical_prior_blobs_allow_only_a_common_byte_observation(self):
        files = [f for f in self.case["files"] if f["status"] != "renamed"]
        self.assertGreaterEqual(len(files), 3)
        previous = b"original before merge"
        old = blob_sha(previous)
        self.fixture.objects[self.case["repo"], "blobs", old] = dict(
            sha=old,
            size=len(previous),
            encoding="base64",
            content=base64.b64encode(previous).decode(),
        )
        for i, file in enumerate(files[:3]):
            first = file["blob_sha"] if i == 0 else old
            second = sha("different-" + file["path"]) if i == 2 else first
            self.install(self.case["parents"][0], file["path"], first)
            self.install(self.case["parents"][1], file["path"], second)
        result, saved = self.run_comparison()
        by_path = {
            r["head_path"]: r["classification"]
            for r in result["rows"]
            if r["project"] == self.case["repo"]
        }
        self.assertEqual(by_path[files[0]["path"]], "identical-to-both-parents")
        self.assertEqual(by_path[files[1]["path"]], "changed-from-identical-parents")
        self.assertEqual(by_path[files[2]["path"]], "parents-diverge")
        self.assertEqual(saved[old], previous)
        self.assertFalse(result["complete_pr_base_diff_certified"])

    def test_missing_one_parent_never_becomes_an_original_before_file(self):
        case_file = next(f for f in self.case["files"] if f["status"] != "renamed")
        self.install(self.case["parents"][0], case_file["path"], case_file["blob_sha"])
        result, _ = self.run_comparison()
        row = next(
            r
            for r in result["rows"]
            if r["project"] == self.case["repo"] and r["head_path"] == case_file["path"]
        )
        self.assertEqual(row["classification"], "absent-one")
        self.assertIsNone(row["common_previous_blob_sha1"])

    def test_remote_sha_identity_must_match_actual_common_previous_bytes(self):
        case_file = next(f for f in self.case["files"] if f["status"] != "renamed")
        fabricated = sha("fake prior")
        for parent in self.case["parents"]:
            self.install(parent, case_file["path"], fabricated)
        wrong = b"wrong"
        self.fixture.objects[self.case["repo"], "blobs", fabricated] = dict(
            sha=fabricated,
            size=len(wrong),
            encoding="base64",
            content=base64.b64encode(wrong).decode(),
        )
        with self.assertRaises(ValueError):
            self.run_comparison()

    def test_immutable_original_head_cannot_be_relabelled(self):
        modified = deepcopy(self.parent)
        modified["files"][0]["original_head_sha1"] = "0" * 40
        with self.assertRaises(ValueError):
            self.run_comparison(modified)

    def test_divergent_parent_and_rename_never_select_one_parent(self):
        a = dict(blob_sha="a" * 40, mode="100644")
        b = dict(blob_sha="b" * 40, mode="100644")
        self.assertEqual(classify("a" * 40, a, b), "parents-diverge")
        self.assertEqual(classify("a" * 40, a, None), "absent-one")
        self.assertEqual(classify("a" * 40, a, b, renamed=True), "unresolved-rename")


if __name__ == "__main__":
    unittest.main()
