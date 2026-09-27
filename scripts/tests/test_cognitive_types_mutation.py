"""Never confuse compiler/setup errors or skipped tests with killed mutants."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cognitive_types_mutation import classify


class ClassificationTests(unittest.TestCase):
    def test_compiled_assertion_failure_kills_mutant(self):
        self.assertEqual(classify(1, "Summary [0.2s] 37 tests run: 36 passed, 1 failed, 0 skipped"), "killed")

    def test_clean_tests_survive(self):
        self.assertEqual(classify(0, "Summary [0.2s] 37 tests run: 37 passed, 0 skipped"), "survived")

    def test_build_and_setup_errors_are_not_kills(self):
        for code, text in [(101, "could not compile crate"), (127, "just: not found"), (0, "")]:
            self.assertEqual(classify(code, text), "error")

    def test_no_executed_test_is_an_error(self):
        self.assertEqual(classify(0, "Summary [0.0s] 0 tests run: 0 passed, 37 skipped"), "error")

    def test_failed_command_without_assertion_failure_is_an_error(self):
        self.assertEqual(classify(1, "Summary [0.2s] 37 tests run: 37 passed, 0 skipped"), "error")

    def test_inconsistent_success_status_is_an_error(self):
        self.assertEqual(classify(0, "Summary [0.2s] 37 tests run: 36 passed, 1 failed"), "error")


if __name__ == "__main__":
    unittest.main()
