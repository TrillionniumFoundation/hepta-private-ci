"""Source byte verification mechanics; fixtures never supply review answers."""

import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from project_pr_family_bytes import (
    collect,
    github_object,
    reopen,
    verify_commits,
)
from project_pr_source_materialize import blob_sha, decode_blob, digest

HERE = Path(__file__).resolve().parent
EXT = HERE / "data/real-project-pr-independent-extension-20261012.json"
OLD = HERE / "data/real-project-pr-source-cut-20261012.json"


class Reader:
    def __init__(self, commits):
        self.commits = commits

    def get(self, repo, kind, oid):
        if kind != "commits":
            raise ValueError("test reader never downloads an original Git blob")
        return self.commits[oid]


class FamilyByteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(EXT.read_text())

    def test_source_head_metadata_and_contiguous_commit_check(self):
        row = self.manifest["cases"][0]
        sha = row["head_sha"]
        commit = {
            "sha": sha,
            "tree": {"sha": row["tree_sha"]},
            "parents": [{"sha": x} for x in row["parents"]],
            "author": {"date": row["head_committed_at"]},
            "committer": {"date": row["head_committed_at"]},
        }
        self.assertEqual(verify_commits(row, Reader({sha: commit})), 1)
        wrong = deepcopy(commit)
        wrong["tree"]["sha"] = "a" * 40
        with self.assertRaises(ValueError):
            verify_commits(row, Reader({sha: wrong}))
        wrong = deepcopy(commit)
        wrong["committer"]["date"] = "2026-10-13T00:00:00Z"
        with self.assertRaises(ValueError):
            verify_commits(row, Reader({sha: wrong}))

    def test_source_object_client_will_not_fetch_unlisted_repositories(self):
        for repo, kind in (
            ("numpy/numpy", "commits"),
            ("python/cpython", "issues"),
            ("example.invalid", "blobs"),
        ):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                github_object(repo, kind, "a" * 40)

    def test_raw_blob_bytes_are_checked_not_just_metadata(self):
        data = b"sample source from original Git repository"
        sha = blob_sha(data)
        good = {
            "sha": sha,
            "size": len(data),
            "encoding": "base64",
            "content": base64.b64encode(data).decode(),
        }
        self.assertEqual(decode_blob(good, sha), data)
        mutated = deepcopy(good)
        mutated["content"] = base64.b64encode(data + b"!").decode()
        with self.assertRaises(ValueError):
            decode_blob(mutated, sha)

    def test_partial_download_fails_before_ready_is_published(self):
        def unavailable(repo, kind, oid):
            raise ValueError("original Git object unavailable")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incomplete"
            with self.assertRaises(ValueError):
                collect(
                    EXT,
                    OLD,
                    path,
                    source_sha256=sha256(EXT.read_bytes()).hexdigest(),
                    fetch=unavailable,
                )
            self.assertTrue(path.exists())
            self.assertFalse((path / "READY.json").exists())

    def test_changed_reopened_blob_is_never_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "blobs").mkdir()
            data = b"a"
            sha = blob_sha(data)
            (root / "blobs" / (sha + ".blob")).write_bytes(data)
            row = {
                "blob_sha": sha,
                "byte_sha256": digest(data),
                "bytes": 1,
            }
            # A valid individual byte check cannot forge the required 32-file
            # source census, so this cannot issue a READY.
            inventory = {
                "originals": [row],
                "retained_source_bytes": 1,
            }
            with self.assertRaises(ValueError):
                reopen(root, inventory)


if __name__ == "__main__":
    unittest.main()
