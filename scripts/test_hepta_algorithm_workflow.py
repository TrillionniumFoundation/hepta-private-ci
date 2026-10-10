import contextlib
import io
import runpy
import unittest
from pathlib import Path

subject = runpy.run_path(str(Path(__file__).with_name("hepta-algorithm-docs.py")))


class AlgorithmWorkflowOwnershipTests(unittest.TestCase):
    def setUp(self):
        prefix = "python3 scripts/hepta-algorithm-docs.py "
        self.dedicated = "\n".join(
            prefix + command
            for command in (
                "self-test",
                "verify-sources",
                "verify",
                "generate-status --check",
            )
        )
        self.global_workflow = "\n".join(
            prefix + command
            for command in ("verify-sources", "generate-status --check")
        )

    def verify(self, dedicated, global_workflow):
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            subject["verify_algorithm_workflow_commands"](dedicated, global_workflow)

    def test_owner_self_test_does_not_require_duplicate_global_execution(self):
        self.verify(self.dedicated, self.global_workflow)

    def test_missing_owner_self_test_is_still_rejected(self):
        with self.assertRaises(SystemExit):
            self.verify(
                self.dedicated.replace("self-test", "missing"), self.global_workflow
            )

    def test_missing_global_source_verification_is_still_rejected(self):
        with self.assertRaises(SystemExit):
            self.verify(
                self.dedicated,
                self.global_workflow.replace("verify-sources", "missing"),
            )

    def test_missing_global_generated_status_check_is_still_rejected(self):
        with self.assertRaises(SystemExit):
            self.verify(
                self.dedicated,
                self.global_workflow.replace("generate-status", "missing"),
            )

    def test_verify_sources_cannot_substitute_for_owner_verify(self):
        dedicated = self.dedicated.replace(
            "python3 scripts/hepta-algorithm-docs.py verify\n", ""
        )
        with self.assertRaises(SystemExit):
            self.verify(dedicated, self.global_workflow)

    def test_commented_command_is_not_execution(self):
        dedicated = self.dedicated.replace(
            "python3 scripts/hepta-algorithm-docs.py self-test",
            "# python3 scripts/hepta-algorithm-docs.py self-test",
        )
        with self.assertRaises(SystemExit):
            self.verify(dedicated, self.global_workflow)
