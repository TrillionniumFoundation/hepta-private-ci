"""Receipt accounting must distinguish methods, subtests, and fixture errors."""

import contextlib
import io
import json
import sys
import unittest
from unittest import mock

from qualification.hcsn import checks


def run_cases(case, *, require_torch=True):
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0,
                                    resultclass=checks.QualificationResult).run(suite)
    return checks.summarize_result(result, require_torch=require_torch)


class ReceiptCountingTests(unittest.TestCase):
    def test_multiple_failing_subtests_count_one_failed_method(self):
        class Example(unittest.TestCase):
            def test_many(self):
                for value in range(3):
                    with self.subTest(value=value):
                        self.fail("intentional accounting probe")

        report, code = run_cases(Example)
        self.assertEqual((report["tests_run"], report["passed"], report["failed"], report["errors"]),
                         (1, 0, 1, 0))
        self.assertEqual(report["failure_records"], 3)
        self.assertEqual((report["status"], code), ("failed", 1))

    def test_failure_and_error_in_one_method_have_one_outcome(self):
        class Example(unittest.TestCase):
            def test_many(self):
                with self.subTest(kind="assertion"):
                    self.fail("intentional failure")
                with self.subTest(kind="exception"):
                    raise RuntimeError("intentional error")

        report, code = run_cases(Example)
        self.assertEqual((report["tests_run"], report["passed"], report["failed"], report["errors"]),
                         (1, 0, 0, 1))
        self.assertEqual((report["failure_records"], report["error_records"]), (1, 1))
        self.assertEqual(report["method_outcomes"][0]["events"], ["error", "failed"])
        self.assertEqual(code, 1)

    def test_setup_class_error_does_not_invent_executed_methods(self):
        called = []

        class Example(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("intentional class setup error")

            def test_first(self):
                called.append("first")

            def test_second(self):
                called.append("second")

        report, code = run_cases(Example)
        self.assertEqual(called, [])
        self.assertEqual((report["tests_run"], report["passed"], report["errors"], report["fixture_errors"]),
                         (0, 0, 0, 1))
        self.assertEqual(report["error_records"], 1)
        self.assertIn("setUpClass", report["fixture_outcomes"][0]["test"])
        self.assertEqual((report["status"], code), ("failed", 1))

    def test_teardown_class_error_preserves_real_method_pass(self):
        class Example(unittest.TestCase):
            @classmethod
            def tearDownClass(cls):
                raise RuntimeError("intentional class teardown error")

            def test_passes(self):
                self.assertTrue(True)

        report, code = run_cases(Example)
        self.assertEqual((report["tests_run"], report["passed"], report["errors"], report["fixture_errors"]),
                         (1, 1, 0, 1))
        self.assertEqual((report["status"], code), ("failed", 1))

    def test_subtest_and_fixture_skips_cannot_qualify_strict_gate(self):
        class PartialMethod(unittest.TestCase):
            def test_mixed(self):
                with self.subTest(kind="completed"):
                    self.assertEqual(2+2, 4)
                with self.subTest(kind="unavailable"):
                    self.skipTest("optional input is missing")

        report, code = run_cases(PartialMethod)
        self.assertEqual((report["tests_run"], report["passed"], report["skipped"], report["fixture_skipped"]),
                         (1, 0, 1, 0))
        self.assertEqual((report["status"], code), ("partial", 2))
        self.assertEqual(run_cases(PartialMethod, require_torch=False)[1], 0)

        class SkippedFixture(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("class resource is missing")

            def test_never_runs(self):
                raise AssertionError("the fixture should prevent this method")

        report, code = run_cases(SkippedFixture)
        self.assertEqual((report["tests_run"], report["passed"], report["skipped"], report["fixture_skipped"]),
                         (0, 0, 0, 1))
        self.assertEqual((report["status"], code), ("partial", 2))

    def test_passing_methods_can_qualify_without_subtest_overcounting(self):
        class Example(unittest.TestCase):
            def test_many(self):
                for value in range(3):
                    with self.subTest(value=value):
                        self.assertGreaterEqual(value, 0)

            def test_other(self):
                self.assertEqual(2+2, 4)

        report, code = run_cases(Example)
        self.assertEqual((report["tests_run"], report["passed"], report["failed"], report["errors"], report["skipped"]),
                         (2, 2, 0, 0, 0))
        self.assertEqual((report["status"], code), ("passed", 0))
        json.dumps(report, allow_nan=False)

    def test_require_torch_missing_returns_exit_two_without_running_tests(self):
        # Intercept all output writes: this verifies the CLI branch without
        # creating a misleading qualification receipt for these synthetic tests.
        with (mock.patch.object(sys, "argv", ["checks", "--require-torch", "--output", "/unused/receipt.json"]),
              mock.patch.object(checks.importlib.util, "find_spec", return_value=None),
              mock.patch.object(checks.Path, "mkdir"),
              mock.patch.object(checks.Path, "write_text") as writer,
              mock.patch.object(checks.unittest.defaultTestLoader, "discover") as discover,
              contextlib.redirect_stdout(io.StringIO())):
            code = checks.main()
        report = json.loads(writer.call_args.args[0])
        discover.assert_not_called()
        self.assertEqual((code, report["status"], report["tests_run"], report["passed"], report["skipped"]),
                         (2, "unavailable", 0, 0, 0))
        self.assertEqual(report["reason"], "PyTorch is required but not installed")


if __name__ == "__main__":
    unittest.main()
