#!/usr/bin/env python3
"""Regression tests for exact Agentd effect-owner execution claims."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name("owner_runtime_qualification.py")
SPEC = importlib.util.spec_from_file_location(
    "kernel_authority_owner_runtime",
    MODULE,
)
assert SPEC is not None and SPEC.loader is not None
OWNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OWNER)


def execution_log(test: str) -> str:
    return "\n".join(
        [
            f"test {test} ... ok",
            "test result: ok. 1 passed; 0 failed; 0 ignored; "
            "0 measured; 0 filtered out; finished in 0.00s",
        ]
    )


def results(passed: set[str]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for case in OWNER.CASES:
        is_passed = case.name in passed
        output.append(
            {
                "name": case.name,
                "passed": is_passed,
                "exitCode": 0 if is_passed else 1,
                "testExecution": OWNER.EXECUTION.validate_output(
                    execution_log(case.test),
                    (case.test,),
                )
                if is_passed
                else None,
            }
        )
    return output


class OwnerRuntimeQualificationTests(unittest.TestCase):
    def test_complete_exact_matrix_supports_each_claim(self) -> None:
        all_cases = {case.name for case in OWNER.CASES}
        self.assertTrue(all(OWNER.claims(results(all_cases)).values()))
        only_progress = OWNER.claims(results({"unrelated-runtime-progress"}))
        self.assertTrue(only_progress["runtimeProgressExercised"])
        self.assertFalse(only_progress["clientCancellationOwnershipExercised"])
        self.assertFalse(only_progress["shutdownTimeoutOwnershipExercised"])

    def test_missing_duplicate_and_false_receipt_are_rejected(self) -> None:
        all_cases = {case.name for case in OWNER.CASES}
        complete = results(all_cases)
        with self.assertRaises(OWNER.QualificationError):
            OWNER.claims(complete[:-1])
        with self.assertRaises(OWNER.QualificationError):
            OWNER.claims(complete + [dict(complete[0])])
        complete[0]["testExecution"] = None
        with self.assertRaises(OWNER.QualificationError):
            OWNER.claims(complete)

    def test_successful_exit_with_zero_tests_is_not_execution(self) -> None:
        case = OWNER.CASES[0]

        def fake_run(command, **kwargs):
            del command
            kwargs["stdout"].write(
                b"test result: ok. 0 passed; 0 failed; 0 ignored; "
                b"0 measured; 1 filtered out; finished in 0.00s\n"
            )
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as directory, patch.object(
            OWNER.subprocess,
            "run",
            side_effect=fake_run,
        ):
            row = OWNER.run_case(case, Path(directory))
        self.assertEqual(row["exitCode"], 0)
        self.assertFalse(row["passed"])
        self.assertIsNotNone(row["validationError"])

    def test_command_is_exact_and_output_owned_by_qualification(self) -> None:
        case = OWNER.CASES[0]
        actual = OWNER.command(case)
        self.assertIn(case.test, actual)
        self.assertIn("--exact", actual)
        self.assertIn("--format=pretty", actual)
        self.assertIn("--test-threads=1", actual)
        self.assertNotIn("--nocapture", actual)


if __name__ == "__main__":
    unittest.main()
