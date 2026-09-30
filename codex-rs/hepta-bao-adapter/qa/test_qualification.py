"""Test receipt/CI control flow only; mocked Cargo is not native test evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("bao_qualify", Path(__file__).with_name("qualify.py"))
qualify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualify)
HEAD = "a" * 40
TREE = "b" * 40


class QualificationTests(unittest.TestCase):
    def execute(self, statuses=None, expected=HEAD, dirty="", diff_code=0):
        statuses = statuses or [0] * len(qualify.CHECKS)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            def fake_git(*args):
                if args == ("rev-parse", "HEAD"):
                    return HEAD
                if args == ("rev-parse", "HEAD^{tree}"):
                    return TREE
                return dirty
            calls = []
            def fake_run(command, **kwargs):
                if command == ["git", "diff", "--check"]:
                    return subprocess.CompletedProcess(command, diff_code)
                calls.append(command)
                code = statuses[len(calls)-1]
                kwargs["stdout"].write(f"synthetic gate status {code}\n".encode())
                return subprocess.CompletedProcess(command, code)
            with patch.object(qualify, "git", side_effect=fake_git), patch.object(qualify.subprocess, "run", side_effect=fake_run), patch.object(qualify.subprocess, "check_output", return_value="rustc synthetic\nhost: synthetic-target"), patch("sys.argv", ["qualify.py", "--expected-sha", expected, "--candidate-role", "source-head", "--output", str(output)]):
                code = qualify.main()
            return code, calls, json.loads((output / "receipt.json").read_text())

    def test_all_checks_run_when_format_fails(self):
        statuses = [0] * len(qualify.CHECKS)
        statuses[next(i for i, row in enumerate(qualify.CHECKS) if row[0] == "format")] = 1
        code, calls, receipt = self.execute(statuses)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), len(qualify.CHECKS))
        self.assertEqual([row["exitCode"] for row in receipt["checks"]], statuses)
        self.assertFalse(receipt["passed"])

    def test_lint_failure_is_not_a_pass(self):
        statuses = [0] * len(qualify.CHECKS)
        statuses[next(i for i, row in enumerate(qualify.CHECKS) if row[0] == "clippy")] = 1
        code, calls, receipt = self.execute(statuses)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), len(qualify.CHECKS))
        self.assertFalse(receipt["passed"])

    def test_wrong_source_and_dirty_source_cannot_pass(self):
        for expected, dirty in [("c"*40, ""), (HEAD, " M src/lib.rs")]:
            code, _, receipt = self.execute(expected=expected, dirty=dirty)
            self.assertEqual(code, 1)
            self.assertFalse(receipt["identityClean"])

    def test_clean_all_pass_records_source_without_release_authority(self):
        code, _, receipt = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(receipt["passed"])
        self.assertEqual((receipt["head"], receipt["tree"]), (HEAD,TREE))
        self.assertFalse(receipt["providerDynamicE2E"])
        self.assertFalse(receipt["productionExecutionProved"])
        self.assertFalse(receipt["releaseAuthority"])

    def test_failed_whitespace_check_cannot_pass(self):
        code, _, receipt = self.execute(diff_code=2)
        self.assertEqual(code, 1)
        self.assertFalse(receipt["identityClean"])

    def test_workflow_jobs_do_not_depend_on_document_success(self):
        workflow = (qualify.ROOT / ".github/workflows/lane-a-foundation.yml").read_text()
        for variant in ("head", "merge"):
            block = workflow.split(f"  secrets-native-{variant}:\n", 1)[1].split("\n  secrets-native-", 1)[0]
            self.assertNotIn("\n    needs:", block)
            self.assertNotIn("continue-on-error", block)
            self.assertIn("if: always()", block)
            self.assertIn("--expected-sha", block)
            self.assertIn("if-no-files-found: error", block)
        self.assertIn("Verify current implementation, traceability and nonclaims", workflow)
        self.assertIn("Construct deterministic synthetic merge", workflow)

if __name__ == "__main__":
    unittest.main()
