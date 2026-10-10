"""Real Git fixtures for retaining pinned evidence without a side branch."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "paper_evidence", Path(__file__).with_name("hepta-paper-evidence.py")
)
assert SPEC is not None and SPEC.loader is not None
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


class EvidenceRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = dict(os.environ)
        self.environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "fixture",
                "GIT_COMMITTER_NAME": "fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            }
        )
        self.git("init", "--quiet")
        self.tree = self.git("mktree", data="")
        self.parent = self.git("commit-tree", self.tree, data="evidence parent\n")
        self.commit = self.git(
            "commit-tree", self.tree, "-p", self.parent, data="pinned evidence\n"
        )
        self.source = self.git("commit-tree", self.tree, data="source history\n")
        self.merged = self.git(
            "commit-tree",
            self.tree,
            "-p",
            self.source,
            "-p",
            self.commit,
            data="retain evidence\n",
        )
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("update-ref", "refs/heads/main", self.merged)
        self.binding = {
            "retentionPolicy": {"kind": "main_history_ancestor"},
            "verificationPolicy": {"pinnedEvidenceMustBeAncestorOfSource": True},
            "evidenceCommit": self.commit,
            "evidenceParentCommit": self.parent,
            "evidenceTree": self.tree,
        }
        self.root_patch = patch.object(EVIDENCE, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def git(self, *args: str, data: str | None = None) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            input=data,
            text=True,
            capture_output=True,
            check=True,
            env=self.environment,
        ).stdout.strip()

    def verify(self) -> str:
        return EVIDENCE.verify_retained_commit(self.binding)

    def test_main_only_history_retains_exact_pinned_objects(self) -> None:
        self.assertEqual(
            self.git("for-each-ref", "--format=%(refname)"), "refs/heads/main"
        )
        self.assertEqual(self.verify(), self.commit)

    def test_deleting_side_branch_does_not_remove_pinned_evidence(self) -> None:
        self.git("update-ref", "refs/heads/evidence/old", self.commit)
        self.git("update-ref", "-d", "refs/heads/evidence/old")
        self.assertEqual(self.verify(), self.commit)

    def test_fetched_but_unmerged_evidence_is_rejected(self) -> None:
        self.git("update-ref", "refs/heads/main", self.source)
        self.git("update-ref", "refs/remotes/origin/evidence/old", self.commit)
        with self.assertRaises(SystemExit):
            self.verify()

    def test_wrong_parent_is_rejected(self) -> None:
        self.binding["evidenceParentCommit"] = self.source
        with self.assertRaises(SystemExit):
            self.verify()

    def test_wrong_tree_is_rejected(self) -> None:
        self.binding["evidenceTree"] = "1" * 40
        with self.assertRaises(SystemExit):
            self.verify()

    def test_missing_object_and_symbolic_commit_are_rejected(self) -> None:
        for value in ("1" * 40, "main", "HEAD", self.commit[:12]):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.binding["evidenceCommit"] = value
                self.verify()

    def test_branch_identity_cannot_replace_retention_policy(self) -> None:
        self.binding["evidenceBranch"] = "evidence/old"
        with self.assertRaises(SystemExit):
            self.verify()

    def test_ancestry_requirement_cannot_be_disabled(self) -> None:
        self.binding["verificationPolicy"]["pinnedEvidenceMustBeAncestorOfSource"] = (
            False
        )
        with self.assertRaises(SystemExit):
            self.verify()

    def test_source_byte_digest_still_rejects_changed_content(self) -> None:
        blob = self.git("hash-object", "-w", "--stdin", data="changed")
        tree = self.git("mktree", data=f"100644 blob {blob}\tsource.txt\n")
        commit = self.git("commit-tree", tree, data="wrong source bytes\n")
        row = {
            "sourceId": "fixture",
            "path": "source.txt",
            "kind": "fixture",
            "gitBlobSha": blob,
            "sha256": "0" * 64,
            "bytes": 7,
        }
        with self.assertRaises(SystemExit):
            EVIDENCE.verify_source(commit, row)


if __name__ == "__main__":
    unittest.main()
