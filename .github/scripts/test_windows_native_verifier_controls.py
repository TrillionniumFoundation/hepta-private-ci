"""Strict-parser controls only; these strings are never native qualification."""

import unittest

from windows_native_verifier_controls import assess_exact, command_for


GROUP = {"id": "test-only", "package": "fixture", "names": ["one", "two"], "runIgnored": True}
ACTUAL_SHAPE = """Starting 2 tests across 1 binary (3 tests skipped)
    PASS [ 0.001s] fixture one
    PASS [ 0.001s] fixture two
Summary [ 0.002s] 2 tests run: 2 passed, 3 skipped
"""


class StrictControls(unittest.TestCase):
    def test_valid_phase_and_exact_ignored_command(self):
        self.assertTrue(assess_exact(GROUP, 0, ACTUAL_SHAPE)["passed"])
        command = command_for(GROUP)
        self.assertEqual(command[-2:], ["--run-ignored", "ignored-only"])
        self.assertEqual(command[command.index("--retries") + 1], "0")

    def test_duplicate_summary_counts_are_refused(self):
        for suffix in (", 999 passed", ", 0 failed, 0 failed", ", 0 unknown", ", 0 skipped"):
            with self.subTest(suffix=suffix):
                text = ACTUAL_SHAPE.rstrip() + suffix + "\n"
                self.assertFalse(assess_exact(GROUP, 0, text)["passed"])

    def test_missing_duplicate_or_unknown_case_is_refused(self):
        for name in ("one", "unknown"):
            with self.subTest(name=name):
                self.assertFalse(assess_exact(GROUP, 0, ACTUAL_SHAPE.replace("fixture two", "fixture " + name))["passed"])
        self.assertFalse(assess_exact(GROUP, 0, ACTUAL_SHAPE.replace("    PASS [ 0.001s] fixture two\n", ""))["passed"])

    def test_nonpassing_terminal_is_not_relabelled(self):
        for status in ("FAIL", "TIMEOUT", "LEAK", "SKIP", "EXECFAIL"):
            with self.subTest(status=status):
                text = ACTUAL_SHAPE.replace("PASS [ 0.001s] fixture two", status + " [ 0.001s] fixture two")
                self.assertFalse(assess_exact(GROUP, 0, text)["passed"])

    def test_extra_phase_or_wrong_package_is_refused(self):
        self.assertFalse(assess_exact(GROUP, 0, ACTUAL_SHAPE + ACTUAL_SHAPE)["passed"])
        self.assertFalse(assess_exact(GROUP, 0, ACTUAL_SHAPE.replace("fixture two", "other two"))["passed"])
        self.assertFalse(assess_exact(GROUP, 1, ACTUAL_SHAPE)["passed"])

    def test_failed_or_leaky_actual_process_stays_nonpass(self):
        failed = ACTUAL_SHAPE.replace("PASS [ 0.001s] fixture two", "FAIL [ 0.001s] fixture two").replace("2 passed", "1 passed, 1 failed")
        failed += "    FAIL [ 0.001s] fixture two\n"
        self.assertFalse(assess_exact(GROUP, 100, failed)["passed"])
        leaked = ACTUAL_SHAPE.replace("PASS [ 0.001s] fixture two", "LEAK [ 0.001s] fixture two").replace("2 passed", "2 passed (1 leaky)")
        self.assertFalse(assess_exact(GROUP, 0, leaked)["passed"])


if __name__ == "__main__":
    unittest.main()
