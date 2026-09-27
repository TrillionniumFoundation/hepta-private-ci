"""Recorder regression tests. Subprocess fixtures do not qualify the Rust product."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import intuition_ledger_exact as ledger
import intuition_qualify_exact as q


class LedgerRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        (self.repo / "codex-rs").mkdir(parents=True)
        (self.repo / "codex-rs/Cargo.lock").write_text("unit-test fixture only\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        self.sha = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.evidence = self.root / "evidence"

    def tearDown(self):
        self.temp.cleanup()

    def run_fixture(self, *, empty=False, code=0, dirty=False):
        def execute(argv, log, cwd, timeout):
            log.write_text(f"test result: ok. {0 if empty else 1} passed; 0 failed;\n")
            if dirty:
                (self.repo / "unexpected").write_text("mutated by fixture\n")
            return code
        with mock.patch.object(q, "ROOT", self.repo), mock.patch.object(q, "execute", side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
            result = ledger.main(["--source-commit", self.sha, "--evidence", str(self.evidence)])
        return result, json.loads((self.evidence / "command-record.json").read_text())

    def test_full_mandatory_plan_records_all_commands_without_promoting(self):
        code, report = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertEqual(len(report["commands"]), len(ledger.COMMANDS))
        self.assertEqual(report["promotion"], "not_authorized")
        names = {row["name"] for row in report["commands"]}
        self.assertIn("agentd-v3-product-tests", names)
        self.assertIn("agentd-commit-boundary-tests", names)
        manifest = json.loads((self.evidence / "artifact-manifest.json").read_text())
        for name, digest in manifest["sha256"].items():
            self.assertEqual(q.sha256(self.evidence / name), digest)

    def test_compiler_failure_is_retained_and_never_passes(self):
        code, report = self.run_fixture(code=101)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(all(row["exitCode"] == 101 for row in report["commands"]))
        self.assertTrue((self.evidence / "agentd-v3-product-tests.log").is_file())

    def test_zero_tests_are_not_success(self):
        code, report = self.run_fixture(empty=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")

    def test_source_mutation_invalidates_receipt(self):
        code, report = self.run_fixture(dirty=True)
        self.assertEqual(code, 1)
        self.assertFalse(report["worktreeUnchanged"])


if __name__ == "__main__":
    unittest.main()
