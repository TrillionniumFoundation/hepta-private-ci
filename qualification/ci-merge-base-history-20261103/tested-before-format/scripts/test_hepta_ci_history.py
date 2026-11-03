import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.hepta_ci_history import fetch_environment
from scripts.hepta_ci_history import git as history_git
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
    def test_merge_base_mode_repairs_actual_shallow_three_dot_without_all_refs(self):
        prepare(self.checkout, [self.base, self.head])
        with self.assertRaises(subprocess.CalledProcessError):
            self.git(self.checkout, "diff", "--name-only", f"{self.base}...{self.head}")
        (self.checkout / "candidate").write_text("local edits\n")
        with patch("scripts.hepta_ci_history.git", wraps=history_git) as calls:
            prepare(self.checkout, [self.base, self.head], merge_base=True)
        self.assertEqual(self.git(self.checkout, "merge-base", self.base, self.head), self.common)
        self.assertEqual(
            self.git(self.checkout, "diff", "--name-only", f"{self.base}...{self.head}"),
            self.git(self.source, "diff", "--name-only", f"{self.base}...{self.head}"),
        )
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.head)
        self.assertEqual((self.checkout / "candidate").read_text(), "local edits\n")
        fetches = [call.args[1:] for call in calls.call_args_list if call.args[1] == "fetch"]
        self.assertGreaterEqual(len(fetches), 2)
        for args in fetches:
            self.assertEqual(args[-3:], ("origin", self.base, self.head))
            self.assertIn("--no-tags", args)
            self.assertIn("--filter=blob:none", args)
            self.assertNotIn("--unshallow", args)
            self.assertTrue(any(arg.startswith("--deepen=") for arg in args))
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_visible_old_merge_base_does_not_hide_a_better_shallow_ancestor(self):
        self.git(self.source, "switch", "-q", "-c", "latent-common", self.common)
        relevant = self.source / ".github/workflows/v8-canary.yml"
        relevant.parent.mkdir(parents=True)
        relevant.write_text("shared before the true fork\n")
        self.commit("newer common ancestor")
        correct = self.git(self.source, "rev-parse", "HEAD")
        tips = []
        for branch in ("long-base", "long-head"):
            self.git(self.source, "switch", "-q", "-c", branch, correct)
            for index in range(6):
                (self.source / branch).write_text(str(index))
                self.commit(branch)
            tip = self.git(self.source, "rev-parse", "HEAD")
            tree = self.git(self.source, "rev-parse", "HEAD^{tree}")
            merged = self.git(self.source, "commit-tree", tree, "-p", tip,
                              "-p", self.common, "-m", "short path to old ancestor")
            self.git(self.source, "update-ref", "refs/heads/shortcut-" + branch, merged)
            tips.append(merged)
        base, head = tips
        checkout = self.root / "shortcut"
        self.git(self.root, "clone", "-q", "--no-tags", "--depth=2", "--branch",
                 "shortcut-long-head", self.source.as_uri(), str(checkout))
        self.git(checkout, "fetch", "--no-tags", "--depth=2", "origin", base)
        self.assertEqual(self.git(checkout, "merge-base", base, head), self.common)
        self.assertEqual(self.git(self.source, "merge-base", base, head), correct)
        self.assertIn(".github/workflows/v8-canary.yml",
                      self.git(checkout, "diff", "--name-only", f"{base}...{head}"))
        prepare(checkout, [base, head], merge_base=True)
        self.assertEqual(self.git(checkout, "merge-base", base, head), correct)
        self.assertEqual(self.git(checkout, "diff", "--name-only", f"{base}...{head}"),
                         self.git(self.source, "diff", "--name-only", f"{base}...{head}"))
        self.assertEqual(self.git(checkout, "tag"), "")

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_equal_tips_need_no_history_or_network(self):
        with patch("scripts.hepta_ci_history.git", wraps=history_git) as calls:
            prepare(self.checkout, [self.head, self.head], merge_base=True)
        self.assertFalse(any(call.args[1] == "fetch" for call in calls.call_args_list))
        self.assertEqual(self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "true")

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_disconnected_complete_histories_fail_instead_of_empty_diff(self):
        self.git(self.source, "switch", "--orphan", "disconnected")
        (self.source / "orphan").write_text("different history\n")
        self.commit("disconnected root")
        other = self.git(self.source, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ValueError, "no common ancestor"):
            prepare(self.checkout, [other, self.head], merge_base=True)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.head)
        self.archives_unselected()

    @patch.dict(os.environ, {"GH_TOKEN": ""})
    def test_unavailable_merge_base_input_preserves_checkout_and_fails(self):
        with self.assertRaises(subprocess.CalledProcessError):
            prepare(self.checkout, [self.head, "a" * 40], merge_base=True)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.head)

    def test_merge_base_mode_requires_exact_pair_and_exclusive_mode(self):
        for commits, full in [([self.head], False), ([self.base, self.head], True),
                              ([self.base, self.head, self.common], False)]:
            with self.subTest(commits=commits, full=full), self.assertRaises(ValueError):
                prepare(self.checkout, commits, merge_base=True, full_history=full)

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
