import tempfile
import unittest
from pathlib import Path
from windows_current_ci import assess, execute_groups, valid_source

GROUP = {
    "id": "original",
    "package": "owner",
    "filter": "test(=original)",
    "expectedTestCount": 1,
    "requiredTests": ["original"],
}
PASS = "Starting 1 tests across 1 binary (99 tests skipped)\nPASS [ 0.1s] (1/1) owner original\n"


class StrictWindowsReceiptTests(unittest.TestCase):
    def test_nonzero_exit_is_never_pass(self):
        self.assertFalse(assess(GROUP, 100, PASS)["passed"])

    def test_skipped_or_different_test_is_not_the_original(self):
        for text in (
            "99 tests skipped",
            PASS.replace("owner original", "owner replacement"),
            PASS.replace("Starting 1 tests", "Starting 0 tests"),
        ):
            self.assertFalse(assess(GROUP, 0, text)["passed"])

    def test_actual_windows_ci_terminal_lines_without_progress_counts(self):
        actual = "Starting 1 tests across 1 binary (99 tests skipped)\n        PASS [   3.283s] owner original\nSummary [ 3.283s] 1 tests run: 1 passed, 99 skipped\n"
        self.assertTrue(assess(GROUP, 0, actual)["passed"])
        self.assertEqual(assess(GROUP, 0, actual)["observedTests"], ["original"])
        for replacement in ("SKIP", "FAIL", "TIMEOUT", "EXECFAIL", "LEAK"):
            self.assertFalse(
                assess(GROUP, 0, actual.replace("PASS [", replacement + " ["))["passed"]
            )
        self.assertFalse(
            assess(GROUP, 0, actual.replace("owner original", "other original"))[
                "passed"
            ]
        )
        self.assertFalse(
            assess(
                {**GROUP, "requiredTests": []}, 0, "Starting 1 tests across 1 binary"
            )["passed"]
        )

    def test_diagnostics_continue_but_each_failure_is_retained(self):
        seen = []

        def invoke(command):
            seen.append(command)
            return (100 if len(seen) == 1 else 0), PASS

        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            results = execute_groups(
                output, output, [GROUP, {**GROUP, "id": "second"}], invoke
            )
        self.assertEqual([result["passed"] for result in results], [False, True])
        self.assertEqual(len(seen), 2)
        for command in seen:
            self.assertEqual(command[-2:], ["--retries", "0"])
            self.assertIn("--locked", command)
            self.assertEqual(command[command.index("--no-tests") + 1], "fail")

    def test_changed_source_or_wrong_head_never_qualifies(self):
        before = {
            "head": "a" * 40,
            "tree": "b" * 40,
            "trackedChanges": "",
            "cargoLockSha256": "c" * 64,
        }
        self.assertTrue(valid_source("a" * 40, before, before))
        self.assertFalse(valid_source("d" * 40, before, before))
        self.assertFalse(
            valid_source("a" * 40, before, {**before, "cargoLockSha256": "d" * 64})
        )
        self.assertFalse(
            valid_source(
                "a" * 40,
                {**before, "trackedChanges": " M source.rs"},
                {**before, "trackedChanges": " M source.rs"},
            )
        )


if __name__ == "__main__":
    unittest.main()
