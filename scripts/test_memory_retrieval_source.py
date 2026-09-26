import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from capture_memory_retrieval_source import ROOTS, capture
from memory_retrieval_synthetic_merge import synthetic_merge


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Source test")
        self.git("config", "user.email", "source-test@example.invalid")
        for name in ROOTS:
            path = self.root / name / "fixture"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("original\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.original = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def branch(self, name, file, content):
        self.git("checkout", "-qb", name, self.original)
        (self.root / file).write_text(content)
        self.git("add", ".")
        self.git("commit", "-qm", name)
        return self.git("rev-parse", "HEAD")

    def test_source_observation_covers_all_roots_and_exact_identity(self):
        receipt = capture(self.root, self.original, self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(set(receipt["source_objects"]), set(ROOTS))
        self.assertFalse(receipt["qualification_executed"])
        self.assertEqual(receipt["source"]["commit"], self.original)

    def test_dirty_source_and_wrong_tree_are_rejected(self):
        with self.assertRaises(ValueError):
            capture(self.root, self.original, "0" * 40)
        (self.root / "codex-rs/fixture").write_text("modified\n")
        with self.assertRaises(ValueError):
            capture(self.root, self.original, self.git("rev-parse", "HEAD^{tree}"))

    def test_merge_is_deterministic_independent_of_committer_environment(self):
        base = self.branch("base", "base.txt", "base\n")
        source = self.branch("source", "source.txt", "source\n")
        result = synthetic_merge(self.root, base, source)
        with patch.dict(os.environ, {"GIT_AUTHOR_NAME": "different", "GIT_COMMITTER_DATE": "1234567890 +0900"}):
            self.assertEqual(synthetic_merge(self.root, base, source), result)
        self.assertEqual(self.git("show", "-s", "--format=%P", result[0]), f"{base} {source}")
        self.assertEqual(self.git("rev-parse", "HEAD"), source)

    def test_conflict_is_not_a_candidate_success(self):
        base = self.branch("base", "codex-rs/fixture", "base\n")
        source = self.branch("source", "codex-rs/fixture", "source\n")
        with self.assertRaises(subprocess.CalledProcessError):
            synthetic_merge(self.root, base, source)
        self.assertEqual(self.git("rev-parse", "HEAD"), source)

    def test_duplicate_parent_and_ref_injection_are_rejected(self):
        with self.assertRaises(ValueError):
            synthetic_merge(self.root, self.original, self.original)
        with self.assertRaises(ValueError):
            synthetic_merge(self.root, "HEAD", "--help")


if __name__ == "__main__":
    unittest.main()
