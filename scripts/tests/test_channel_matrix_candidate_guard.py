"""Verifier unit contracts in temporary Git fixtures, not product qualification."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "verify_channel_matrix_candidate.py"
spec = importlib.util.spec_from_file_location("matrix_candidate_guard_under_test", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class CandidateGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original_root = guard.ROOT
        self.addCleanup(setattr, guard, "ROOT", self.original_root)
        guard.ROOT = Path(self.temp.name) / "repo"
        guard.ROOT.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Verifier fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (guard.ROOT / "sample.txt").write_text("original\n")
        self.git("add", "sample.txt")
        self.git("commit", "-qm", "fixture")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=guard.ROOT, check=True,
                              text=True, capture_output=True).stdout.strip()

    def test_explicit_false_claims_are_accepted(self):
        guard.require_false_claims({name: False for name in guard.DENIED_CLAIMS})

    def test_missing_and_non_boolean_false_claims_are_rejected(self):
        for value in (None, True, 0, "false", []):
            row = {name: False for name in guard.DENIED_CLAIMS}
            row["activation"] = value
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                guard.require_false_claims(row)
        with self.assertRaises(RuntimeError):
            guard.require_false_claims({})

    def test_clean_file_receipt_matches_the_committed_blob(self):
        receipt = guard.file_receipt(guard.ROOT / "sample.txt")
        self.assertEqual(receipt["gitBlob"], self.git("rev-parse", "HEAD:sample.txt"))
        self.assertEqual(receipt["bytes"], 9)

    def test_dirty_file_cannot_receive_a_candidate_receipt(self):
        (guard.ROOT / "sample.txt").write_text("uncommitted\n")
        with self.assertRaises(RuntimeError):
            guard.file_receipt(guard.ROOT / "sample.txt")

    def test_parent_paths_are_rejected(self):
        with self.assertRaises(RuntimeError):
            guard.local_path("../outside")

    def test_symlink_escape_is_rejected(self):
        target = Path(self.temp.name) / "outside.txt"
        target.write_text("outside\n")
        (guard.ROOT / "escape").symlink_to(target)
        with self.assertRaises(RuntimeError):
            guard.local_path("escape")

    def test_observation_requires_the_actual_commit_tree(self):
        head = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assertEqual(guard.checked_observation({"commit": head, "tree": tree}, head, "fixture"), (head, tree))
        with self.assertRaises(RuntimeError):
            guard.checked_observation({"commit": head, "tree": "0" * 40}, head, "fixture")

    def test_expected_sha_mismatch_fails_before_any_map_claim(self):
        with self.assertRaises(RuntimeError):
            guard.verify("0" * 40)


if __name__ == "__main__":
    unittest.main()
