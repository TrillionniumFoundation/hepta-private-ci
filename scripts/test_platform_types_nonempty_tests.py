"""No Rust is executed by these parser regressions."""
import unittest

from platform_types_nonempty_tests import executed_tests


def suite(
    running: int,
    *,
    passed: int,
    failed: int = 0,
    ignored: int = 0,
    measured: int = 0,
    filtered: int = 0,
    state: str = "ok",
) -> str:
    noun = "test" if running == 1 else "tests"
    return (
        f"running {running} {noun}\n"
        f"test result: {state}. {passed} passed; {failed} failed; "
        f"{ignored} ignored; {measured} measured; {filtered} filtered out; "
        "finished in 0.01s"
    )


class NonemptyTests(unittest.TestCase):
    def test_actual_execution_and_terminal_summary_are_required(self):
        self.assertEqual(executed_tests(suite(2, passed=2)), 2)
        self.assertEqual(
            executed_tests(suite(0, passed=0) + "\n" + suite(3, passed=3)),
            3,
        )
        for text in (
            "Finished dev profile",
            "test result: ok. 2 passed; 0 failed; 0 ignored;",
            "running 2 tests",
            "example: running 2 tests\nexample: test result: ok. 2 passed; 0 failed; 0 ignored;",
            "",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                executed_tests(text)

    def test_running_and_summary_counts_must_agree(self):
        for text in (
            suite(3, passed=2),
            suite(3, passed=1, ignored=1),
            "running 1 test\nrunning 1 test\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored;",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                executed_tests(text)

    def test_auxiliary_empty_targets_do_not_discard_real_tests(self):
        text = suite(0, passed=0) + "\n" + suite(2, passed=2, filtered=3) + "\n"
        self.assertEqual(executed_tests(text), 2)

    def test_empty_ignored_failed_and_orphan_summaries_reject(self):
        for text in (
            suite(0, passed=0),
            suite(8, passed=0, ignored=8),
            suite(4, passed=3, failed=1, state="FAILED"),
            "test result: ok. 3 passed; 0 failed; 0 ignored; "
            "0 measured; 0 filtered out; finished in 0.01s",
            suite(3, passed=3) + "\n"
            "test result: FAILED. 1 passed; 1 failed; 0 ignored;",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                executed_tests(text)


if __name__ == "__main__":
    unittest.main()
