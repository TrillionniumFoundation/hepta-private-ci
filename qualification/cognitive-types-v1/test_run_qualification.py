"""Failure classification and deterministic candidate regressions, with no remote effects."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("readonly_qualification", Path(__file__).with_name("run_qualification.py"))
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


class QualificationTests(unittest.TestCase):
    def test_failed_command_and_missing_runner_are_not_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = qualification.run_check("failed", [sys.executable, "-c", "raise SystemExit(7)"], root, root)
            missing = qualification.run_check("missing", [str(root / "absent-runner")], root, root)
            self.assertEqual((failed["status"], failed["exit_code"]), ("failed", 7))
            self.assertEqual((missing["status"], missing["exit_code"]), ("infrastructure_invalid", None))
            self.assertEqual(len(failed["log_sha256"]), 64)
            self.assertFalse(qualification.finish_receipt({"identity_valid": True, "checks": [failed]}, root))
            self.assertFalse(json.loads((root / "receipt.json").read_text())["qualification_passed"])

    def test_empty_skipped_and_invalid_identity_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            for identity, checks in [(True, []), (False, [{"status": "passed"}]),
                                     (True, [{"status": "skipped"}]),
                                     (True, [{"status": "infrastructure_invalid"}])]:
                with self.subTest(identity=identity, checks=checks):
                    self.assertFalse(qualification.finish_receipt({"identity_valid": identity, "checks": checks}, Path(directory)))

    def test_exact_source_and_merge_have_distinct_reproducible_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-b", "main")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@invalid.example")
            (root / "baseline").write_text("base\n")
            git("add", ".")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            (root / "change").write_text("source\n")
            git("add", ".")
            git("commit", "-m", "source")
            source = git("rev-parse", "HEAD")
            exact = qualification.prepare_candidate(root, source, base, "exact-head")
            first = qualification.prepare_candidate(root, source, base, "synthetic-merge")
            second = qualification.prepare_candidate(root, source, base, "synthetic-merge")
            self.assertEqual(first, second)
            self.assertEqual(first["parents"], [base, source])
            self.assertNotEqual(exact["candidate_commit"], first["candidate_commit"])
            self.assertEqual(exact["source_tree"], first["source_tree"])
            (root / "change").write_text("uncommitted mutation\n")
            with self.assertRaises(ValueError):
                qualification.prepare_candidate(root, source, base, "exact-head")


if __name__ == "__main__":
    unittest.main()
