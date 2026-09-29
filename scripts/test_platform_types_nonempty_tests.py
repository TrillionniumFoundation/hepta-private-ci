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


if __name__ == "__main__":
    unittest.main()
