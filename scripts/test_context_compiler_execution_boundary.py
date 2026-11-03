"""Real-Git receipt boundary tests; fake Bazel behavior is not Bazel qualification."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import context_compiler_candidate as candidate
import context_compiler_execution as execution
import context_compiler_qualification as legacy


class ExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / "source"
        self.root.mkdir()
        self.output = self.workspace / "evidence"
        self.manifest = self.root / "state.json"
        self.manifest.write_text('{"consumerExecution": []}')
        self.lockfile = self.root / "MODULE.bazel.lock"
        self.lockfile.write_text("committed lock bytes\n")
        # Model only Bazel's documented update/error lock behavior. Native Bazel
        # execution and the old hosted ValueError cause are not asserted here.
        (self.root / "bazel_fixture.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "if '--lockfile_mode=error' in sys.argv:\n    sys.exit(48)\n"
            "Path('MODULE.bazel.lock').write_text('updated lock bytes\\n')\n"
        )
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "immutable source")
        self.head = self.git("rev-parse", "HEAD")
        self.record = candidate.prepare(self.root, self.head, self.head, "source-head")
        self.record_path = self.workspace / "candidate.json"
        candidate.write_record(self.record_path, self.record)

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.root, env=candidate.git_env(), text=True
        ).strip()

    def run_receipt(self, *, permit_fixture_write=False, verify_error=None):
        spec = next(
            x for x in legacy.command_specs() if x["name"] == "bazel-context-compiler"
        )
        argv = list(spec["argv"])
        if permit_fixture_write:
            argv.remove("--lockfile_mode=error")
        first = {
            **spec,
            "cwd": self.root,
            "argv": [sys.executable, "-B", "bazel_fixture.py", *argv[1:]],
        }
        following = {
            "name": "source-readiness",
            "cwd": self.root,
            "argv": [sys.executable, "-B", "-c", "raise SystemExit(0)"],
        }
        with (
            patch.object(legacy, "ROOT", self.root),
            patch.object(legacy, "MANIFEST", self.manifest),
            patch.object(legacy, "tool_version", return_value={"available": False}),
            patch.object(execution, "specs", return_value=[first, following]),
            patch.object(
                sys,
                "argv",
                [
                    "qualification",
                    "--candidate-record",
                    str(self.record_path),
                    "--output-dir",
                    str(self.output),
                ],
            ),
        ):
            if verify_error is None:
                result = execution.main()
            else:
                with patch.object(candidate, "verify", side_effect=verify_error):
                    result = execution.main()
        return result, json.loads(
            (self.output / "context-compiler-qualification-receipt.json").read_text()
        )

    def test_lock_rejection_keeps_source_clean_and_runs_remaining_checks(self):
        result, receipt = self.run_receipt()
        self.assertEqual(result, 1)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["failureContext"], None)
        self.assertEqual(receipt["failureClass"], None)
        self.assertEqual(
            [(x["name"], x["exitCode"], x["succeeded"]) for x in receipt["commands"]],
            [("bazel-context-compiler", 48, False), ("source-readiness", 0, True)],
        )
        self.assertEqual(self.lockfile.read_text(), "committed lock bytes\n")
        candidate.verify(self.root, self.record)

    def test_dirty_source_stops_before_readiness_with_safe_boundary_reason(self):
        result, receipt = self.run_receipt(permit_fixture_write=True)
        self.assertEqual(result, 1)
        self.assertEqual(receipt["failureClass"], "ValueError")
        self.assertEqual(
            receipt["failureContext"],
            {
                "phase": "verify_after_command",
                "command": "bazel-context-compiler",
                "reasonCode": "candidate_worktree_dirty",
            },
        )
        self.assertEqual(
            [x["name"] for x in receipt["commands"]], ["bazel-context-compiler"]
        )
        self.assertEqual(self.lockfile.read_text(), "updated lock bytes\n")
        self.assertFalse(receipt["independentAcceptance"])
        self.assertFalse(receipt["activation"])
        self.assertFalse(receipt["release"])

    def test_unknown_verifier_error_does_not_export_raw_exception(self):
        result, receipt = self.run_receipt(
            verify_error=ValueError("private/raw/exception-marker")
        )
        self.assertEqual(result, 1)
        self.assertEqual(receipt["commands"], [])
        self.assertEqual(
            receipt["failureContext"],
            {
                "phase": "verify_initial_candidate",
                "command": None,
                "reasonCode": "candidate_verification_rejected",
            },
        )
        self.assertNotIn("private/raw/exception-marker", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main(verbosity=2)
