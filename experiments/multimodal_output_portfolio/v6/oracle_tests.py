"""Standalone oracle custody regressions, using tiny disposable Git repositories."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from .validate_oracle import SOURCE_DIR, publish_report


class OracleCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        target = self.repo / SOURCE_DIR
        target.mkdir(parents=True)
        for name in ("control.py", "validate_oracle.py"):
            shutil.copyfile(Path(__file__).with_name(name), target / name)
        self.git("init", "-q")
        self.git("config", "user.name", "Oracle Test")
        self.git("config", "user.email", "oracle@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.commit()
        self.output = self.root / "report.json"

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.repo, text=True).strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "oracle fixture")
        self.expected = self.git("rev-parse", "HEAD")

    def append_control(self, text):
        path = self.repo / SOURCE_DIR / "control.py"
        path.write_text(path.read_text() + "\n" + text + "\n")

    def run_oracle(self):
        return subprocess.run([sys.executable, str(self.repo / SOURCE_DIR / "validate_oracle.py"),
                               "--repo", str(self.repo), "--expected-commit", self.expected,
                               "--output", str(self.output)], capture_output=True, text=True,
                              cwd=self.root, timeout=30)

    def test_clean_expected_commit_passes_all_128_cases(self):
        result = self.run_oracle()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(self.output.read_text())
        self.assertEqual((report["status"], report["cases"], report["failures"], report["git_commit"]),
                         ("passed", 128, [], self.expected))
        self.assertTrue(report["clean_source_verified_pre_post"])
        for name, field in (("control.py", "control_sha256"), ("validate_oracle.py", "script_sha256")):
            self.assertEqual(report[field], hashlib.sha256((self.repo / SOURCE_DIR / name).read_bytes()).hexdigest())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_dirty_controller_rejected_without_report(self):
        self.append_control("# uncommitted alteration")
        result = self.run_oracle()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be clean", result.stderr)
        self.assertFalse(self.output.exists())

    def test_wrong_expected_commit_rejected_without_report(self):
        self.expected = "0" * 40
        result = self.run_oracle()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit identity differs", result.stderr)
        self.assertFalse(self.output.exists())

    def test_source_bytes_checked_even_when_git_status_hides_changes(self):
        self.git("update-index", "--assume-unchanged", str(SOURCE_DIR / "control.py"))
        self.append_control("# hidden working tree alteration")
        self.assertEqual(self.git("status", "--porcelain"), "")
        result = self.run_oracle()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Frozen source bytes differ: control.py", result.stderr)
        self.assertFalse(self.output.exists())

    def test_existing_report_is_preserved(self):
        original = b'{"status":"old report must survive"}\n'
        self.output.write_bytes(original)
        result = self.run_oracle()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(self.output.read_bytes(), original)

    def test_import_error_has_no_credited_output(self):
        self.append_control('raise RuntimeError("injected controller failure")')
        self.commit()
        result = self.run_oracle()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("injected controller failure", result.stderr)
        self.assertFalse(self.output.exists())

    def test_persistent_mutation_during_cases_rejected(self):
        self.append_control('''
_original_choose = choose
def choose(*args, **kwargs):
    from pathlib import Path
    path = Path(__file__)
    path.write_bytes(path.read_bytes() + b"\\n# mutation during validation\\n")
    return _original_choose(*args, **kwargs)
''')
        self.commit()
        self.git("update-index", "--assume-unchanged", str(SOURCE_DIR / "control.py"))
        result = self.run_oracle()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Frozen source bytes differ: control.py", result.stderr)
        self.assertFalse(self.output.exists())

    def test_completed_numerical_failures_are_reported_with_nonzero_exit(self):
        self.append_control('''
_original_choose = choose
def choose(*args, **kwargs):
    from dataclasses import replace
    return replace(_original_choose(*args, **kwargs), value=10.0)
''')
        self.commit()
        result = self.run_oracle()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(self.output.read_text())
        self.assertEqual((report["status"], report["cases"], report["failures"]),
                         ("failed", 128, list(range(128))))

    def test_atomic_publication_cannot_overwrite_a_late_destination(self):
        self.output.write_text("competing report")
        with self.assertRaises(FileExistsError):
            publish_report(self.output, {"status": "passed"})
        self.assertEqual(self.output.read_text(), "competing report")
        self.assertEqual(list(self.root.glob(".report.json.*")), [])


if __name__ == "__main__":
    unittest.main()
