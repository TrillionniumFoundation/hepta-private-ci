import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hepta_ci_scope import changed_paths, select
from scripts.hepta_ci_trees import prepare_trees


class ExactTreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = self.root / "origin"
        self.client = self.root / "client"
        self.origin.mkdir()
        self.client.mkdir()
        self.git(self.origin, "init", "-q")
        self.git(self.origin, "config", "user.name", "Exact Tree Test")
        self.git(self.origin, "config", "user.email", "exact-tree@localhost")
        self.write("README.md", "common\n")
        self.common = self.commit("common")
        self.write("codex-rs/hepta-fleet/src/base.rs", "base only\n")
        self.base = self.commit("comparison base")
        self.git(self.origin, "checkout", "-qb", "candidate", self.common)
        self.write("codex-rs/hepta-agentd/src/head.rs", "head only\n")
        self.head = self.commit("candidate")
        self.git(self.origin, "checkout", "-qb", "unrelated", self.common)
        self.write("unrelated.txt", "must not be fetched\n")
        self.unrelated = self.commit("unrelated")
        self.git(self.origin, "tag", "unrelated-tag")
        self.git(self.client, "init", "-q")
        self.git(self.client, "remote", "add", "origin", self.origin.as_uri())
        self.git(self.client, "fetch", "--no-tags", "--depth=1", "origin", self.head)
        self.git(self.client, "checkout", "--detach", "FETCH_HEAD")

    @staticmethod
    def git(root, *args):
        return (
            subprocess.check_output(
                ["git", "--no-replace-objects", "-C", str(root), *args],
                stderr=subprocess.PIPE,
            )
            .decode()
            .strip()
        )

    def write(self, path, body):
        file = self.origin / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body)

    def commit(self, message):
        self.git(self.origin, "add", "-A")
        self.git(self.origin, "commit", "-qm", message)
        return self.git(self.origin, "rev-parse", "HEAD")

    def paths(self, root):
        previous = Path.cwd()
        try:
            os.chdir(root)
            return changed_paths(self.base, self.head)
        finally:
            os.chdir(previous)

    def test_shallow_diverged_trees_keep_original_scope_and_ignore_unrelated_refs(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(self.client, "cat-file", "-e", self.base)
        refs_before = self.git(self.client, "for-each-ref", "--format=%(refname)")
        result = prepare_trees(self.client, self.base, self.head)
        self.assertTrue(result["base_fetched"])
        self.assertEqual(result["source_head"], self.head)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.head)
        self.assertEqual(
            self.git(self.client, "rev-parse", "--is-shallow-repository"), "true"
        )
        expected = self.paths(self.origin)
        self.assertEqual(self.paths(self.client), expected)
        self.assertIn("codex-rs/hepta-fleet/src/base.rs", expected)
        self.assertIn("codex-rs/hepta-agentd/src/head.rs", expected)
        self.assertEqual(select(self.paths(self.client)), select(expected))
        self.assertEqual(
            self.git(self.client, "for-each-ref", "--format=%(refname)"), refs_before
        )
        for omitted in (self.common, self.unrelated):
            with (
                self.subTest(omitted=omitted),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                self.git(self.client, "cat-file", "-e", omitted)

    def test_existing_exact_base_does_not_need_an_accessible_remote(self):
        prepare_trees(self.client, self.base, self.head)
        self.git(
            self.client, "remote", "set-url", "origin", (self.root / "missing").as_uri()
        )
        result = prepare_trees(self.client, self.base, self.head)
        self.assertFalse(result["base_fetched"])
        self.assertEqual(self.paths(self.client), self.paths(self.origin))

    def test_identical_trees_keep_the_empty_plan(self):
        result = prepare_trees(self.client, self.head, self.head)
        self.assertFalse(result["base_fetched"])
        self.assertEqual(result["head_tree"], result["base_tree"])

    def test_invalid_identity_is_rejected_before_any_git_command(self):
        for invalid in ("0" * 40, "--upload-pack=payload", "HEAD", "a" * 39):
            with (
                self.subTest(invalid=invalid),
                patch("scripts.hepta_ci_trees.git") as command,
                self.assertRaises(ValueError),
            ):
                prepare_trees(self.client, invalid, self.head)
            command.assert_not_called()

    def test_candidate_mismatch_cannot_fetch_or_select_another_head(self):
        with self.assertRaisesRegex(ValueError, "checkout differs"):
            prepare_trees(self.client, self.base, self.base)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.head)
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(self.client, "cat-file", "-e", self.base)

    def test_unavailable_exact_base_fails_without_a_fallback_plan(self):
        with self.assertRaises(subprocess.CalledProcessError):
            prepare_trees(self.client, "f" * 40, self.head)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.head)


if __name__ == "__main__":
    unittest.main()
