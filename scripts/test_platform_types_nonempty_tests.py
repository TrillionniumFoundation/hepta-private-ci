"""No Rust is executed by these parser regressions."""
import unittest

from platform_types_nonempty_tests import executed_tests


class NonemptyTests(unittest.TestCase):
    def test_actual_test_summary_is_required(self):
        self.assertEqual(executed_tests("test result: ok. 2 passed; 0 failed; 0 ignored;"), 2)
        self.assertEqual(executed_tests("test result: ok. 0 passed; 0 failed; 0 ignored;\n"
                                        "test result: ok. 3 passed; 0 failed; 0 ignored;"), 3)
        for text in ("Finished dev profile", "test result: ok. 0 passed; 0 failed; 8 ignored;",
                     "test result: FAILED. 1 passed; 1 failed; 0 ignored;", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                executed_tests(text)

    def test_passed_tests_are_counted(self):
        self.assertEqual(executed_tests("test result: ok. 3 passed; 0 failed; 0 ignored;"), 3)

    def test_auxiliary_empty_targets_do_not_discard_real_tests(self):
        text = ("test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n"
                "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 3 filtered out; finished in 0.10s\n")
        self.assertEqual(executed_tests(text), 2)

    def test_compile_empty_ignored_failed_and_quoted_logs_reject(self):
        for text in (
            "Finished release profile", "",
            "test result: ok. 0 passed; 0 failed; 0 ignored;",
            "test result: ok. 0 passed; 0 failed; 9 ignored;",
            "test result: FAILED. 3 passed; 1 failed; 0 ignored;",
            "example: test result: ok. 3 passed; 0 failed; 0 ignored;",
            "test result: ok. 3 passed; 0 failed; 0 ignored; not a summary",
            "test result: ok. 3 passed; 0 failed; 0 ignored;\ntest result: FAILED. 1 passed; 1 failed; 0 ignored;",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                executed_tests(text)


if __name__ == "__main__":
    unittest.main()
