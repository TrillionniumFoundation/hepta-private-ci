#!/usr/bin/env python3
"""Synthetic postflight tests; these are not Rust/product execution evidence."""
import tempfile
from pathlib import Path
import unittest

from hepta_kg_execution_audit import PYTHON_TESTS
from hepta_kg_execution_audit import audit
from hepta_kg_execution_audit import native_execution_proved
from hepta_kg_execution_audit import read_results
from hepta_kg_execution_audit import required_checks

SOURCE, BASE, TREE = "1" * 40, "2" * 40, "3" * 40
PASS = (
    "test result: ok. 1 passed; 0 failed; 0 ignored; "
    "0 measured; 0 filtered out;\n"
)


class ExecutionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.checks = required_checks("kernel", "source-head")
        (self.directory / "identity.txt").write_text(
            f"source={SOURCE}\nbase={BASE}\n{SOURCE}\n{TREE}\n",
            encoding="utf-8",
        )
        self.results({name: 0 for name in self.checks})
        for name in self.checks:
            (self.directory / (name + ".log")).write_text(
                "Ran 12 tests in 0.1s\n\nOK\n"
                if name in PYTHON_TESTS
                else PASS,
                encoding="utf-8",
            )

    def results(self, values):
        (self.directory / "results.tsv").write_text(
            "".join(f"{key}\t{value}\n" for key, value in values.items()),
            encoding="utf-8",
        )

    def run_audit(self):
        return audit(
            self.directory,
            "kernel",
            "source-head",
            SOURCE,
            BASE,
            SOURCE,
            TREE,
        )

    def test_complete_inventory_and_log_binding(self):
        result = self.run_audit()
        self.assertTrue(result["completeAndPassed"])
        self.assertEqual(len(result["checks"]["kg-kernel"]["logSha256"]), 64)
        self.assertFalse(result["targetHostQualified"])
        self.assertFalse(result["independentAcceptance"])

    def test_missing_result_is_not_success(self):
        self.results({name: 0 for name in self.checks if name != "kg-kernel"})
        self.assertFalse(self.run_audit()["completeAndPassed"])

    def test_missing_log_is_not_success(self):
        (self.directory / "kg-clippy.log").unlink()
        self.assertFalse(self.run_audit()["completeAndPassed"])

    def test_nonzero_not_lost_after_success(self):
        self.results(
            {name: int(name == "implementation-maps") for name in self.checks}
        )
        result = self.run_audit()
        self.assertFalse(result["completeAndPassed"])
        self.assertTrue(result["checks"]["kg-kernel"]["passed"])

    def test_cancelled_zero_test_and_partial_test_are_not_success(self):
        for log in (
            "",
            "running 2 tests\ntest partial ... ok\n",
            "test result: ok. 0 passed; 0 failed; 1 ignored;\n",
            PASS + "test result: FAILED. 0 passed; 1 failed; 0 ignored;\n",
        ):
            with self.subTest(log=log):
                (self.directory / "kg-kernel.log").write_text(
                    log,
                    encoding="utf-8",
                )
                self.assertFalse(self.run_audit()["completeAndPassed"])

    def test_duplicate_unknown_and_malformed_results_rejected(self):
        for text in (
            "kg-kernel\t0\nkg-kernel\t0\n",
            "unknown\t0\n",
            "kg-kernel\t-1\n",
            "kg-kernel\t256\n",
            "kg-kernel\t00\n",
            "kg-kernel\t0\textra\n",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_results(text, self.checks)

    def test_stale_identity_rejected(self):
        path = self.directory / "identity.txt"
        path.write_text(
            path.read_text(encoding="utf-8").replace(TREE, "4" * 40),
            encoding="utf-8",
        )
        self.assertFalse(self.run_audit()["completeAndPassed"])

    def test_source_head_substitution_rejected(self):
        self.assertFalse(
            audit(
                self.directory,
                "kernel",
                "source-head",
                "4" * 40,
                BASE,
                SOURCE,
                TREE,
            )["completeAndPassed"]
        )

    def test_zero_python_tests_rejected(self):
        (self.directory / "execution-audit-tests.log").write_text(
            "Ran 0 tests in 0.0s\n\nOK\n",
            encoding="utf-8",
        )
        self.assertFalse(self.run_audit()["completeAndPassed"])

    def test_missing_inventory_still_emits_failed_report(self):
        (self.directory / "results.tsv").unlink()
        self.assertFalse(self.run_audit()["completeAndPassed"])

    def test_invalid_profile_and_lane_rejected(self):
        for profile, lane in (("kernel", "skip"), ("other", "source-head")):
            with self.assertRaises(ValueError):
                required_checks(profile, lane)

    def test_product_lane_requires_delivery_recovery_and_destructive_checks(self):
        checks = required_checks("product", "base-merge")
        self.assertTrue(
            {
                "delivery-consistency",
                "agentd-default",
                "agentd-witness",
                "crash-reopen",
                "history-reopen",
            }
            <= set(checks)
        )
        self.assertNotIn("release-measurement", checks)
        self.assertIn(
            "release-measurement",
            required_checks("product", "source-head"),
        )

    def test_exact_crash_must_execute_one_not_two_or_skipped(self):
        self.assertTrue(native_execution_proved("crash-reopen", PASS))
        for log in (
            PASS.replace("1 passed", "2 passed"),
            PASS.replace("0 ignored", "1 ignored"),
            PASS + PASS,
        ):
            self.assertFalse(native_execution_proved("crash-reopen", log))


if __name__ == "__main__":
    unittest.main()
