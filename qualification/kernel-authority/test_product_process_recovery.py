#!/usr/bin/env python3
"""Negative tests for exact two-process product recovery qualification."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).with_name("product_process_recovery.py")
SPEC = importlib.util.spec_from_file_location(
    "kernel_authority_product_process_recovery", MODULE
)
assert SPEC is not None and SPEC.loader is not None
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)


def output(
    *,
    name: str = RECOVERY.TEST_NAME,
    result: str = "ok",
    passed: int = 1,
    failed: int = 0,
    ignored: int = 0,
    measured: int = 0,
    summaries: int = 1,
) -> str:
    lines = [f"test {name} ... {result}"]
    for _ in range(summaries):
        status = "ok" if failed == 0 else "FAILED"
        lines.append(
            f"test result: {status}. {passed} passed; {failed} failed; "
            f"{ignored} ignored; {measured} measured; 0 filtered out; "
            "finished in 0.01s"
        )
    return "\n".join(lines)


class ProductProcessRecoveryTests(unittest.TestCase):
    def test_exact_single_execution_passes(self) -> None:
        receipt = RECOVERY.parse_execution(output())
        self.assertEqual(receipt["test"], RECOVERY.TEST_NAME)
        self.assertEqual(receipt["passedCount"], 1)

    def test_zero_or_renamed_test_is_rejected(self) -> None:
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(
                "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; "
                "1 filtered out; finished in 0.00s"
            )
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(output(name="renamed_process_test"))

    def test_ignored_failed_and_duplicate_execution_are_rejected(self) -> None:
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(output(result="ignored", passed=0, ignored=1))
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(output(result="FAILED", passed=0, failed=1))
        duplicate = "\n".join(
            [
                f"test {RECOVERY.TEST_NAME} ... ok",
                f"test {RECOVERY.TEST_NAME} ... ok",
                "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; "
                "0 filtered out; finished in 0.01s",
            ]
        )
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(duplicate)

    def test_summary_count_or_totals_cannot_overclaim(self) -> None:
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(output(summaries=2))
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(output(passed=2))
        with self.assertRaises(RECOVERY.QualificationError):
            RECOVERY.parse_execution(output(measured=1))

    def test_command_selects_one_exact_integration_test(self) -> None:
        command = RECOVERY.command()
        self.assertEqual(command[:2], ("cargo", "test"))
        self.assertIn("authority_effect_process_restart", command)
        self.assertIn(RECOVERY.TEST_NAME, command)
        self.assertIn("--exact", command)
        self.assertIn("--test-threads=1", command)
        self.assertNotIn("--nocapture", command)


if __name__ == "__main__":
    unittest.main()
