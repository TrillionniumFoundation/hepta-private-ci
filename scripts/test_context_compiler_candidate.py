"""Real-Git tests of candidate identity; these are not native Rust qualification."""
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("candidate", Path(__file__).with_name("context_compiler_candidate.py"))
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        (self.root / "base").write_text("base\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "source").write_text("source\n")
        self.commit("source")
        self.source = self.git("rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.root, env=candidate.git_env(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def source_record(self):
        return candidate.prepare(self.root, self.source, self.base, "source-head")

    def test_source_identity(self):
        record = self.source_record()
        self.assertEqual(record["testedHeadSha"], self.source)
        self.assertFalse(record["executionPassed"])
        candidate.verify(self.root, record)

    def test_deterministic_merge_and_ordered_parents(self):
        first = candidate.prepare(self.root, self.source, self.base, "synthetic-merge")
        self.assertEqual(first["parents"], [self.base, self.source])
        self.git("checkout", "-q", "--detach", self.source)
        second = candidate.prepare(self.root, self.source, self.base, "synthetic-merge")
        self.assertEqual(first, second)

    def test_divergent_base_changes_are_in_tested_tree(self):
        self.git("checkout", "-q", "--detach", self.base)
        (self.root / "base-update").write_text("must be tested\n")
        self.commit("base update")
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", self.source)
        record = candidate.prepare(self.root, self.source, base, "synthetic-merge")
        self.assertTrue((self.root / "source").exists())
        self.assertTrue((self.root / "base-update").exists())
        candidate.verify(self.root, record)

    def test_dirty_tracked_source_is_not_overwritten(self):
        (self.root / "source").write_text("uncommitted\n")
        with self.assertRaises(ValueError):
            self.source_record()
        self.assertEqual((self.root / "source").read_text(), "uncommitted\n")

    def test_untracked_source_is_not_ignored(self):
        (self.root / "untracked").write_text("not qualified\n")
        with self.assertRaises(ValueError):
            self.source_record()

    def test_alias_and_short_oid_rejected(self):
        for value in ["HEAD", self.source[:12], self.source + "^{commit}", "-h", self.source.upper()]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                candidate.prepare(self.root, value, self.base, "source-head")

    def test_tree_and_missing_objects_are_not_commits(self):
        for value in [self.git("rev-parse", "HEAD^{tree}"), "0" * 40]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                candidate.prepare(self.root, value, self.base, "source-head")

    def test_changed_head_fails_even_when_worktree_clean(self):
        record = self.source_record()
        self.git("checkout", "-q", "--detach", self.base)
        with self.assertRaises(ValueError):
            candidate.verify(self.root, record)

    def test_forged_tree_and_parents_rejected(self):
        original = self.source_record()
        for field, value in [("testedTreeSha", "0" * 40), ("parents", [])]:
            record = copy.deepcopy(original)
            record[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                candidate.verify(self.root, record)

    def test_source_record_cannot_self_assert_acceptance(self):
        for field in ["executionPassed", "independentAcceptance"]:
            record = self.source_record()
            record[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                candidate.verify(self.root, record)

    def test_duplicate_merge_parents_rejected(self):
        with self.assertRaises(ValueError):
            candidate.prepare(self.root, self.source, self.source, "synthetic-merge")

    def test_conflicting_merge_fails_without_source_mutation(self):
        (self.root / "base").write_text("source conflict\n")
        self.commit("source conflict")
        source = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", self.base)
        (self.root / "base").write_text("base conflict\n")
        self.commit("base conflict")
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", source)
        with self.assertRaises(ValueError):
            candidate.prepare(self.root, source, base, "synthetic-merge")
        self.assertEqual(self.git("rev-parse", "HEAD"), source)
        self.assertEqual((self.root / "base").read_text(), "source conflict\n")

    def test_git_environment_cannot_redirect_repository(self):
        with patch.dict(os.environ, {"GIT_DIR": "/nonexistent", "GIT_INDEX_FILE": "/nonexistent/index", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.bare", "GIT_CONFIG_VALUE_0": "true"}):
            self.source_record()

    def test_replace_refs_do_not_change_identity(self):
        self.git("replace", self.source, self.base)
        record = self.source_record()
        self.assertEqual(record["parents"], [self.base])
        self.assertNotEqual(record["testedTreeSha"], self.git("rev-parse", self.base + "^{tree}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
