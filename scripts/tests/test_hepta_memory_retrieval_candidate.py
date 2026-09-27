"""Execute real temporary Git repositories; no product/native-test claim."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.hepta_memory_retrieval_candidate import CandidateError, refs, synthetic_commit


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Local candidate fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.initial = self.commit("common.txt", "initial\n")
        self.git("update-ref", "refs/remotes/origin/main", self.initial)
        self.source = self.commit("candidate.txt", "source\n")

    def git(self, *args):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True,
            text=True, timeout=30, check=True,
        )
        return result.stdout.strip()

    def commit(self, name, text):
        (self.root / name).write_text(text)
        self.git("add", name)
        self.git("commit", "-qm", "fixture change")
        return self.git("rev-parse", "HEAD")

    def advance_main(self, name="main.txt", text="new main\n"):
        self.git("checkout", "--detach", self.initial)
        main = self.commit(name, text)
        self.git("update-ref", "refs/remotes/origin/main", main)
        self.git("checkout", "--detach", self.source)
        return main

    def test_base_is_fetched_main_not_older_event_ancestor(self):
        main = self.advance_main()
        self.assertEqual(refs(self.root, self.source), {
            "source_sha": self.source, "base_sha": main, "main_sha": main,
        })

    def test_main_push_uses_distinct_first_parent(self):
        self.git("update-ref", "refs/remotes/origin/main", self.source)
        self.assertEqual(refs(self.root, self.source), {
            "source_sha": self.source, "base_sha": self.initial, "main_sha": self.source,
        })

    def test_wrong_checkout_is_rejected(self):
        with self.assertRaises(CandidateError):
            refs(self.root, self.initial)

    def test_dirty_checkout_is_rejected(self):
        (self.root / "candidate.txt").write_text("uncommitted\n")
        with self.assertRaises(CandidateError):
            refs(self.root, self.source)

    def test_missing_fetched_main_is_rejected(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        with self.assertRaises(CandidateError):
            refs(self.root, self.source)

    def test_branch_and_uppercase_are_not_exact_identities(self):
        for value in ("HEAD", self.source.upper(), None, "../main"):
            with self.subTest(value=value), self.assertRaises(CandidateError):
                refs(self.root, value)

    def test_merge_is_deterministic_and_binds_ordered_parents(self):
        main = self.advance_main()
        before = self.git("rev-parse", "HEAD")
        first = synthetic_commit(self.root, main, self.source)
        with patch.dict(os.environ, {"GIT_AUTHOR_NAME": "other", "GIT_AUTHOR_DATE": "2025-01-01T00:00:00Z"}):
            second = synthetic_commit(self.root, main, self.source)
        self.assertEqual(first, second)
        self.assertEqual(self.git("show", "-s", "--format=%P", first).split(), [main, self.source])
        self.assertEqual(self.git("show", f"{first}:main.txt"), "new main")
        self.assertEqual(self.git("show", f"{first}:candidate.txt"), "source")
        self.assertEqual(self.git("rev-parse", "HEAD"), before)

    def test_conflict_is_rejected_without_moving_checkout(self):
        self.source = self.commit("common.txt", "source change\n")
        main = self.advance_main("common.txt", "main change\n")
        with self.assertRaises(CandidateError):
            synthetic_commit(self.root, main, self.source)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_duplicate_parents_are_rejected(self):
        with self.assertRaises(CandidateError):
            synthetic_commit(self.root, self.source, self.source)


if __name__ == "__main__":
    unittest.main()
