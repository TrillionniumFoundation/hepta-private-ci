import unittest
from context_compiler_execution import observed_tests


class ExecutionSummaryTests(unittest.TestCase):
    def test_cargo_summary(self):
        self.assertEqual(observed_tests("test result: ok. 11 passed; 0 failed; 0 ignored;"), 11)

    def test_nextest_summary(self):
        self.assertEqual(observed_tests("Summary [1.23s] 8 tests run: 8 passed, 120 skipped"), 8)

    def test_empty_and_no_tests(self):
        for text in ["", "build passed", "test result: ok. 0 passed; 0 failed;", "Summary [0s] 0 tests run: 0 passed"]:
            self.assertEqual(observed_tests(text), 0)

    def test_ansi(self):
        self.assertEqual(observed_tests("\x1b[32mSummary\x1b[0m [1s] 19 tests run: 19 passed"), 19)

    def test_unrelated_log_text_is_not_test_execution(self):
        self.assertEqual(observed_tests("there are 500 passed in the specification"), 0)

    def test_multiple_cargo_suites(self):
        self.assertEqual(observed_tests("test result: ok. 11 passed;\ntest result: ok. 8 passed;"), 19)


if __name__ == "__main__":
    unittest.main(verbosity=2)
