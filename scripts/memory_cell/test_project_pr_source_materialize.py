"""Synthetic Git object fixtures test integrity, NOT original project outcomes."""

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from project_pr_source_materialize import (
    ObjectReader, atomic_json, bind_path, blob_sha, collect, decode_blob, digest,
    verify_head,
)


class FrozenGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "original"
        self.cases = []
        self.objects = {}
        projects = (
            "rust-lang/rust", "rust-lang/rust", "kubernetes/kubernetes",
            "kubernetes/kubernetes", "numpy/numpy", "numpy/numpy",
            "astral-sh/ruff", "astral-sh/ruff",
        )
        for index, repo in enumerate(projects):
            head, root, intermediate = (f"{index+1:040x}", f"{index+10:040x}", f"{index+20:040x}")
            parent = f"{index+30:040x}"
            payload = f"non-executable source;  note {index}".encode()
            oid = blob_sha(payload)
            self.objects[repo, "commits", head] = dict(
                sha=head, tree=dict(sha=root), parents=[dict(sha=parent)],
                author=dict(date="2026-10-11T08:00:00Z"),
                committer=dict(date="2026-10-11T08:00:00Z"),
            )
            self.objects[repo, "trees", root] = dict(
                sha=root, truncated=False, tree=[dict(path="folder", type="tree", mode="040000", sha=intermediate)],
            )
            self.objects[repo, "trees", intermediate] = dict(
                sha=intermediate, truncated=False,
                tree=[dict(path=f"file{j}.txt", type="blob", mode="100644", sha=oid) for j in range(10)],
            )
            self.objects[repo, "blobs", oid] = dict(
                sha=oid, encoding="base64", size=len(payload),
                content=base64.b64encode(payload).decode(),
            )
            self.cases.append(dict(
                repo=repo, partition="evaluation", pull_number=100+index,
                head_sha=head, tree_sha=root, parents=[parent],
                head_committed_at="2026-10-11T08:00:00Z",
                files=[dict(path=f"folder/file{j}.txt", blob_sha=oid) for j in range(10)],
            ))
        self.manifest = dict(model_executions=0, no_answers_or_labels=True, cases=self.cases)

    def fetch(self, repo, category, oid):
        return deepcopy(self.objects[repo, category, oid])

    def test_complete_census_creates_final_ready_and_original_sha_bindings(self):
        ready = collect(self.manifest, self.output, manifest_sha="f"*64, fetch=self.fetch)
        self.assertEqual(ready["original_file_bindings"], 80)
        self.assertEqual(ready["unique_blobs"], 8)
        self.assertTrue(ready["original_objects_verified"])
        inventory = (self.output / "inventory.json").read_bytes()
        self.assertEqual(ready["inventory_sha256"], digest(inventory))
        for row in json.loads(inventory)["originals"]:
            raw = (self.output / row["blob_path"]).read_bytes()
            self.assertEqual(blob_sha(raw), row["blob_sha"])
            self.assertEqual(digest(raw), row["sha256"])
        self.assertFalse(ready["production_accepted"])
        self.assertFalse(ready["independent_semantic_review"])
        with self.assertRaises(ValueError):
            collect(self.manifest, self.output, manifest_sha="f"*64, fetch=self.fetch)

    def test_parent_tree_and_mode_mismatch_rejected(self):
        for kind in ("parent", "head_tree", "symlink", "absent", "wrong_file_sha"):
            with self.subTest(kind=kind):
                obj = deepcopy(self.objects)
                row = self.cases[0]
                commit = obj[row["repo"], "commits", row["head_sha"]]
                root = obj[row["repo"], "trees", row["tree_sha"]]
                subtree = obj[row["repo"], "trees", root["tree"][0]["sha"]]
                if kind == "parent":
                    commit["parents"] = []
                elif kind == "head_tree":
                    commit["tree"]["sha"] = "d"*40
                elif kind == "symlink":
                    subtree["tree"][0]["mode"] = "120000"
                elif kind == "absent":
                    subtree["tree"].pop(0)
                elif kind == "wrong_file_sha":
                    subtree["tree"][0]["sha"] = "e"*40
                output = Path(self.temp.name) / ("partial-" + kind)
                with self.assertRaises(ValueError):
                    collect(self.manifest, output, manifest_sha="f"*64, fetch=lambda *key: deepcopy(obj[key]))
                self.assertTrue((output / "INCOMPLETE.json").exists())
                self.assertFalse((output / "READY.json").exists())

    def test_sealed_committer_cut_cannot_be_bypassed_by_backdated_author(self):
        for kind in ("future_committer", "different_pinned_date", "missing_committer",
                     "malformed_committer", "future_author"):
            with self.subTest(kind=kind):
                obj = deepcopy(self.objects)
                manifest = deepcopy(self.manifest)
                row = manifest["cases"][0]
                commit = obj[row["repo"], "commits", row["head_sha"]]
                if kind == "future_committer":
                    # Author is still before the cut, but this Git object is not.
                    commit["committer"]["date"] = "2026-10-13T08:00:00Z"
                elif kind == "different_pinned_date":
                    row["head_committed_at"] = "2026-10-10T08:00:00Z"
                elif kind == "missing_committer":
                    del commit["committer"]
                elif kind == "malformed_committer":
                    commit["committer"]["date"] = "yesterday"
                elif kind == "future_author":
                    commit["author"]["date"] = "2026-10-13T08:00:00Z"
                output = Path(self.temp.name) / ("committer-" + kind)
                with self.assertRaises(ValueError):
                    collect(manifest, output, manifest_sha="f"*64,
                            fetch=lambda *key: deepcopy(obj[key]))
                self.assertTrue((output / "INCOMPLETE.json").exists())
                self.assertFalse((output / "READY.json").exists())

    def test_corrupted_blob_and_size_or_budget_fail_closed(self):
        for kind in ("bytes", "size", "budget"):
            with self.subTest(kind=kind):
                obj = deepcopy(self.objects)
                row = self.cases[0]
                oid = row["files"][0]["blob_sha"]
                blob = obj[row["repo"], "blobs", oid]
                if kind == "bytes":
                    blob["content"] = base64.b64encode(b"tamper").decode()
                elif kind == "size":
                    blob["size"] = 1024*1024+1
                output = Path(self.temp.name) / ("bad-" + kind)
                with self.assertRaises(ValueError):
                    collect(self.manifest, output, manifest_sha="f"*64,
                            fetch=lambda *key: deepcopy(obj[key]),
                            max_total=10 if kind == "budget" else 24*1024*1024)
                self.assertFalse((output / "READY.json").exists())

    def test_tree_prefix_confusion_and_stale_source_blocks(self):
        row = self.cases[0]
        reader = ObjectReader(self.fetch)
        verify_head(row, reader)
        self.assertEqual(bind_path(row, row["files"][0], reader), "100644")
        self.assertEqual(reader.count, 3)
        with self.assertRaises(ValueError):
            bind_path(row, row["files"][0] | {"path":"../file0.txt"}, reader)
        with self.assertRaises(ValueError):
            collect(self.manifest | {"model_executions":1}, self.output,
                    manifest_sha="f"*64, fetch=self.fetch)
        self.assertFalse(self.output.exists())

    def test_blob_decoder_rejects_bad_base64_and_type(self):
        row = self.cases[0]
        oid = row["files"][0]["blob_sha"]
        blob = self.fetch(row["repo"], "blobs", oid)
        with self.assertRaises(ValueError):
            decode_blob(blob | {"content":"!!!"}, oid)
        with self.assertRaises(ValueError):
            decode_blob(blob | {"size": True}, oid)
        with self.assertRaises(ValueError):
            decode_blob(blob | {"encoding":"utf-8"}, oid)


if __name__ == "__main__":
    unittest.main()
