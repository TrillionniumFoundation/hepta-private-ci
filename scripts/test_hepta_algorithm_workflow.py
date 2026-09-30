"""Verify executable owner/aggregate commands without duplicated paper checks."""

import contextlib
import io
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
subject = runpy.run_path(str(Path(__file__).with_name("hepta-algorithm-docs.py")))


def workflow(*commands):
    return "steps:\n  - run: |\n" + "".join(
        "      " + command + "\n" for command in commands
    )


class AlgorithmWorkflowOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.self_test = "python3 scripts/hepta-algorithm-docs.py self-test"
        self.owner_verify = "python3 scripts/hepta-algorithm-docs.py verify"
        self.aggregate_verify = "python3 scripts/hepta-docs.py verify"
        self.dedicated = workflow(self.self_test, self.owner_verify)
        self.global_workflow = workflow(self.aggregate_verify)

    def verify(self, dedicated, global_workflow):
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            subject["verify_algorithm_workflow_commands"](dedicated, global_workflow)

    def test_aggregate_delegation_needs_no_duplicate_source_or_status_command(self):
        self.verify(self.dedicated, self.global_workflow)

    def test_shared_recorder_executes_the_real_verifier(self):
        record = (
            'python3 scripts/hepta_ci_exec.py --output "$RUNNER_TEMP/test.json" -- '
        )
        self.verify(
            workflow(self.self_test, record + self.owner_verify),
            workflow(record + self.aggregate_verify),
        )

    def test_missing_owner_self_test_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.verify(workflow(self.owner_verify), self.global_workflow)

    def test_source_lock_check_cannot_substitute_for_semantic_verify(self):
        with self.assertRaises(SystemExit):
            self.verify(
                workflow(self.self_test, self.owner_verify + "-sources"),
                self.global_workflow,
            )

    def test_aggregate_must_execute_not_only_describe_verification(self):
        for command in (
            "# " + self.aggregate_verify,
            "echo " + self.aggregate_verify,
            self.aggregate_verify + "-sources",
        ):
            with self.subTest(command=command), self.assertRaises(SystemExit):
                self.verify(self.dedicated, workflow(command))

    def test_commented_owner_command_is_not_execution(self):
        with self.assertRaises(SystemExit):
            self.verify(
                workflow("# " + self.self_test, self.owner_verify), self.global_workflow
            )

    def test_each_candidate_runs_one_verifier_and_no_redundant_receipt(self):
        for path, verifier in (
            (subject["WORKFLOW_PATH"], "scripts/hepta-algorithm-docs.py"),
            (subject["GLOBAL_WORKFLOW"], "scripts/hepta-docs.py"),
        ):
            with self.subTest(workflow=path):
                commands = subject["workflow_commands"]((ROOT / path).read_text())
                wrapped = [
                    row[row.index("--") + 1 :]
                    for row in commands
                    if row[:2] == ["python3", "scripts/hepta_ci_exec.py"]
                    and "--" in row
                ]
                self.assertEqual(
                    sum(row[:3] == ["python3", verifier, "verify"] for row in wrapped), 2
                )
                self.assertFalse(
                    any(row[:3] == ["python3", verifier, "verify"] for row in commands)
                )
                redundant = {
                    "receipt",
                    "receipt-verify",
                    "inventory-legacy",
                    "cleanup-inventory",
                    "verify-sources",
                    "generate-status",
                }
                for row in commands:
                    if len(row) >= 3 and row[0] == "python3" and row[1] == verifier:
                        self.assertNotIn(row[2], redundant)

    def test_current_workflows_have_the_executing_owner(self):
        self.verify(
            (ROOT / subject["WORKFLOW_PATH"]).read_text(),
            (ROOT / subject["GLOBAL_WORKFLOW"]).read_text(),
        )


if __name__ == "__main__":
    unittest.main()
