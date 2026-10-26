import unittest

from windows_final_safety import assess_exact


class ExactSafetyResultTests(unittest.TestCase):
    def setUp(self):
        self.group = {
            "id": "test-only",
            "package": "real-package",
            "expectedTestCount": 3,
            "requiredTests": ["target::one", "target::two", "target::three"],
        }
        self.log = "Starting 3 tests across 1 binary (99 tests skipped)\n" + "\n".join(
            f"        PASS [   0.001s] real-package target::{name}"
            for name in ("one", "two", "three")
        )

    def test_exact_native_terminal_set_passes(self):
        self.assertTrue(assess_exact(self.group, 0, self.log)["passed"])

    def test_duplicate_pass_is_not_deduplicated_into_success(self):
        result = assess_exact(
            self.group, 0, self.log + "\nPASS [ 0.1s] real-package target::one"
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["duplicateTests"], ["target::one"])

    def test_missing_and_unknown_names_cannot_substitute_for_originals(self):
        for log in (
            self.log.replace("target::three", "target::other"),
            "\n".join(self.log.splitlines()[:-1]),
        ):
            with self.subTest(log=log):
                self.assertFalse(assess_exact(self.group, 0, log)["passed"])

    def test_wrong_package_and_second_run_are_refused(self):
        for log in (
            self.log.replace("real-package", "unrelated-package"),
            self.log + "\nStarting 3 tests across 1 binary",
        ):
            with self.subTest(log=log):
                self.assertFalse(assess_exact(self.group, 0, log)["passed"])

    def test_nonzero_process_or_nonpassing_terminal_is_never_success(self):
        self.assertFalse(assess_exact(self.group, 100, self.log)["passed"])
        for status in ("FAIL", "TIMEOUT", "EXECFAIL", "LEAK", "SKIP"):
            with self.subTest(status=status):
                self.assertFalse(
                    assess_exact(self.group, 0, self.log.replace("PASS", status, 1))[
                        "passed"
                    ]
                )


if __name__ == "__main__":
    unittest.main()
