import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.hepta_ci_history import fetch_environment
from scripts.hepta_ci_history import prepare


class ExactHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git(self.source, "init", "-q", "-b", "main")
        self.git(self.source, "config", "user.name", "History test")
        self.git(self.source, "config", "user.email", "history@example.invalid")
        (self.source / "common").write_text("common\n")
        self.commit("common")
        self.common = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.source, "switch", "-q", "-c", "candidate")
        for index in range(3):
            (self.source / "candidate").write_text(f"candidate {index}\n")
            self.commit("candidate")
        self.head = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.source, "switch", "-q", "main")
        (self.source / "base").write_text("independent base change\n")
        self.commit("base")
        self.base = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.source, "switch", "-q", "-c", "unrelated", self.common)
        (self.source / "archive-only").write_text("unrelated archived content\n")
        self.commit("archive")
        self.unrelated = self.git(self.source, "rev-parse", "HEAD")
        self.git(self.source, "tag", "-a", "historical-archive", "-m", "archive")
        self.checkout = self.root / "checkout"
        self.git(
            self.root,
            "clone",
            "-q",
            "--no-tags",
            "--depth=1",
            "--branch",
            "candidate",
            self.source.as_uri(),
            str(self.checkout),
        )
        # Detached auto-maintenance can write pack files during fixture cleanup.
        self.git(self.checkout, "config", "maintenance.auto", "false")

    def git(self, directory, *arguments):
        return subprocess.check_output(
            ["git", *arguments], cwd=directory, stderr=subprocess.PIPE, text=True
        ).strip()

    def commit(self, message):
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", message)

    def missing(self, commit):
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(self.checkout, "cat-file", "-e", f"{commit}^{{commit}}")

    def archives_unselected(self):
        self.assertEqual(self.git(self.checkout, "tag"), "")
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(
                self.checkout, "show-ref", "--verify", "refs/remotes/origin/unrelated"
            )

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_comparison_fetch_preserves_dirty_checkout_and_excludes_archives(self):
        self.missing(self.base)
        (self.checkout / "candidate").write_text("local edits\n")
        prepare(self.checkout, [self.base, self.head])
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.head)
        self.assertEqual((self.checkout / "candidate").read_text(), "local edits\n")
        self.assertEqual(
            self.git(
                self.checkout, "diff", "--name-only", self.base, self.head
            ).splitlines(),
            ["base", "candidate"],
        )
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_full_history_preserves_actual_merge_base_and_merge_tree(self):
        prepare(self.checkout, [self.base, self.head], full_history=True)
        self.assertEqual(
            self.git(self.checkout, "merge-base", self.base, self.head), self.common
        )
        self.assertEqual(
            self.git(self.checkout, "merge-tree", "--write-tree", self.base, self.head),
            self.git(self.source, "merge-tree", "--write-tree", self.base, self.head),
        )
        self.assertEqual(
            self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "false"
        )
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_snapshot_only_fetch_supplies_base_content_without_other_history(self):
        prepare(self.checkout, [self.base, self.head], with_blobs=True)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.head)
        self.assertEqual(
            self.git(self.checkout, "show", f"{self.base}:base"),
            "independent base change",
        )
        self.assertEqual(
            self.git(self.checkout, "diff", "--numstat", self.base, self.head),
            self.git(self.source, "diff", "--numstat", self.base, self.head),
        )
        self.assertEqual(
            self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "true"
        )
        self.missing(self.common)
        self.missing(self.unrelated)
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": "", "GIT_NO_LAZY_FETCH": "1"})
    def test_snapshot_with_blobs_upgrades_a_cached_blobless_comparison(self):
        self.git(self.source, "config", "uploadpack.allowFilter", "true")
        self.git(self.source, "config", "uploadpack.allowReachableSHA1InWant", "true")
        prepare(self.checkout, [self.base, self.head])
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(self.checkout, "show", f"{self.base}:base")
        prepare(self.checkout, [self.base, self.head], with_blobs=True)
        self.assertEqual(
            self.git(self.checkout, "show", f"{self.base}:base"),
            "independent base change",
        )
        self.missing(self.common)
        self.missing(self.unrelated)
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": "", "GIT_NO_LAZY_FETCH": "1"})
    def test_full_history_with_blobs_upgrades_cached_blobless_history(self):
        self.git(self.source, "config", "uploadpack.allowFilter", "true")
        self.git(self.source, "config", "uploadpack.allowReachableSHA1InWant", "true")
        self.git(self.source, "switch", "-q", "main")
        (self.source / "base").write_text("base after cached snapshot\n")
        self.commit("new base")
        new_base = self.git(self.source, "rev-parse", "HEAD")
        prepare(self.checkout, [new_base, self.head], full_history=True)
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(self.checkout, "show", f"{self.base}:base")
        prepare(
            self.checkout, [new_base, self.head], full_history=True, with_blobs=True
        )
        self.assertEqual(
            self.git(self.checkout, "show", f"{self.base}:base"),
            "independent base change",
        )
        self.assertEqual(
            self.git(self.checkout, "merge-tree", "--write-tree", new_base, self.head),
            self.git(self.source, "merge-tree", "--write-tree", new_base, self.head),
        )
        self.missing(self.unrelated)
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": "", "GIT_NO_LAZY_FETCH": "1"})
    def test_full_history_with_blobs_unshallows_a_cached_blobless_snapshot(self):
        self.git(self.source, "config", "uploadpack.allowFilter", "true")
        self.git(self.source, "config", "uploadpack.allowReachableSHA1InWant", "true")
        prepare(self.checkout, [self.base, self.head])
        self.assertEqual(
            self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "true"
        )
        prepare(
            self.checkout, [self.base, self.head], full_history=True, with_blobs=True
        )
        self.assertEqual(
            self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "false"
        )
        self.assertEqual(
            self.git(self.checkout, "merge-tree", "--write-tree", self.base, self.head),
            self.git(self.source, "merge-tree", "--write-tree", self.base, self.head),
        )
        self.missing(self.unrelated)
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_full_history_with_blobs_materializes_merge_without_lazy_fetch(self):
        self.git(self.source, "config", "uploadpack.allowFilter", "true")
        prepare(
            self.checkout, [self.base, self.head], full_history=True, with_blobs=True
        )
        self.git(self.checkout, "remote", "remove", "origin")
        merge = self.git(
            self.checkout, "merge-tree", "--write-tree", self.base, self.head
        )
        self.assertEqual(
            merge,
            self.git(self.source, "merge-tree", "--write-tree", self.base, self.head),
        )
        self.assertEqual(
            self.git(self.checkout, "show", f"{merge}:base"), "independent base change"
        )
        self.missing(self.unrelated)
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_unavailable_exact_commit_fails_without_replacing_checkout(self):
        with self.assertRaises(subprocess.CalledProcessError):
            prepare(self.checkout, ["a" * 40])
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.head)

    def test_ref_names_are_rejected_before_network(self):
        with self.assertRaises(ValueError):
            prepare(self.checkout, ["main"])
        self.missing(self.base)

    @patch.dict(
        os.environ, {"GH_TOKEN": "test-only-token", "GITHUB_REPOSITORY": "owner/repo"}
    )
    def test_ci_token_cannot_be_sent_to_different_origin(self):
        with self.assertRaises(ValueError):
            fetch_environment(self.checkout)


if __name__ == "__main__":
    unittest.main()
