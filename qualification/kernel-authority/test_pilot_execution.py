"""Regression tests: successful exit alone never proves a pilot ran."""
import copy
import unittest

from pilot_execution import ExecutionError, checked_command, validate_output, validate_receipt


def log(names=("module::case",), result="ok", passed=None, ignored=0):
    if passed is None:
        passed = len(names)
    return "\n".join([
        *(f"test {name} ... {result}" for name in names),
        f"test result: ok. {passed} passed; 0 failed; {ignored} ignored; 0 measured; 0 filtered out; finished in 0.00s",
    ])


class ExactExecutionTests(unittest.TestCase):
    def test_exact_case(self):
        result = validate_output(log(), ("module::case",))
        self.assertTrue(validate_receipt(result, ("module::case",)))

    def test_zero_tests(self):
        with self.assertRaises(ExecutionError):
            validate_output(log((), passed=0), ("module::case",))

    def test_renamed_or_unexpected_case(self):
        for names in (("other::case",), ("module::case", "other::case")):
            with self.subTest(names=names), self.assertRaises(ExecutionError):
                validate_output(log(names), ("module::case",))

    def test_ignored_is_not_pass(self):
        with self.assertRaises(ExecutionError):
            validate_output(log(result="ignored", passed=0, ignored=1), ("module::case",))

    def test_ignored_with_reason_is_not_pass(self):
        with self.assertRaises(ExecutionError):
            validate_output(log(result="ignored, platform unavailable", passed=0, ignored=1), ("module::case",))

    def test_failed_is_not_pass(self):
        with self.assertRaises(ExecutionError):
            validate_output(log(result="FAILED"), ("module::case",))

    def test_duplicate_case(self):
        with self.assertRaises(ExecutionError):
            validate_output(log(("module::case", "module::case")), ("module::case",))

    def test_summary_required_and_counts_must_match(self):
        for text in ("test module::case ... ok", log(passed=0), log(passed=2), log(ignored=1)):
            with self.subTest(text=text), self.assertRaises(ExecutionError):
                validate_output(text, ("module::case",))

    def test_other_empty_targets_do_not_mask_execution(self):
        result = validate_output(log((), passed=0) + "\n" + log(), ("module::case",))
        self.assertEqual(result["suiteSummaries"], 2)

    def test_complete_matrix_identity(self):
        names = ("unix::one", "unix::two")
        self.assertEqual(validate_output(log(names), names)["passedCount"], 2)
        with self.assertRaises(ExecutionError):
            validate_output(log(names[:1]), names)

    def test_exact_numeric_types_and_projection(self):
        baseline = validate_output(log(), ("module::case",))
        for key, value in (("passedCount", True), ("ignoredCount", False),
                           ("suiteSummaries", 0), ("passedTests", []), ("extra", 1)):
            altered = copy.deepcopy(baseline)
            altered[key] = value
            self.assertFalse(validate_receipt(altered, ("module::case",)))

    def test_owned_output_flags_preserve_selection(self):
        command = ("cargo", "test", "--locked", "-p", "package", "module::case", "--", "--exact", "--nocapture")
        checked = checked_command(command)
        self.assertEqual(checked[:7], command[:7])
        self.assertIn("--exact", checked)
        self.assertNotIn("--nocapture", checked)
        self.assertIn("--test-threads=1", checked)
        with self.assertRaises(ExecutionError):
            checked_command(("cargo", "test", "--", "--format=json"))


if __name__ == "__main__":
    unittest.main()
