import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from operational_observer import classify


class OperationalObserverTests(unittest.TestCase):
    def run_case(self, source, selector, runner="unittest"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(source)
            output = root / "result.json"
            child = subprocess.run([sys.executable, str(Path(__file__).with_name("operational_observer.py")),
                "--runner", runner, "--output", str(output), "--", "-q", selector],
                cwd=root, capture_output=True, timeout=10)
            return child.returncode, json.loads(output.read_text())

    def test_actual_assertion_pass_and_import_failure_have_distinct_observations(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_a(self): self.assertEqual(2,3)\n def test_b(self): self.assertEqual(2,2)\n"
        code, result = self.run_case(source, "sample.T.test_a")
        self.assertEqual((code, result["outcome"], result["test_call_failures"]), (1, "test_failure", 1))
        code, result = self.run_case(source, "sample.T.test_b")
        self.assertEqual((code, result["outcome"], result["test_call_passes"]), (0, "pass", 1))
        code, result = self.run_case(source, "absent_module.Test.test_missing")
        self.assertEqual((code, result["outcome"], result["non_call_failures"]), (1, "infrastructure_error", 1))

    def test_setup_failure_and_skip_are_not_semantic_failure_or_success(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def setUp(self): self.fail('fixture')\n def test_a(self): pass\n"
        code, result = self.run_case(source, "sample.T.test_a")
        self.assertEqual((result["outcome"], result["observations"][0]["phase"]), ("infrastructure_error", "setup"))
        source = "import unittest\nclass T(unittest.TestCase):\n @unittest.skip('unsupported')\n def test_a(self): pass\n"
        code, result = self.run_case(source, "sample.T.test_a")
        self.assertEqual((code, result["outcome"]), (0, "uninformative"))

    def test_collection_or_teardown_errors_override_partial_passes(self):
        passed = {"id": "a", "phase": "call", "status": "passed"}
        for phase in ("setup", "teardown", "collection", "unknown"):
            with self.subTest(phase=phase):
                result = classify([passed, {"id": "b", "phase": phase, "status": "failed"}], 1)
                self.assertEqual(result["outcome"], "infrastructure_error")

    def test_real_pytest_call_and_collection_are_distinct(self):
        code, result = self.run_case("def test_a(): assert 2 == 3\n", "sample.py::test_a", "pytest")
        self.assertEqual((code, result["outcome"], result["test_call_failures"]), (1, "test_failure", 1))
        code, result = self.run_case("raise ImportError('missing dependency')\n", "sample.py", "pytest")
        self.assertEqual((code, result["outcome"], result["non_call_failures"]), (2, "infrastructure_error", 1))
        source = "import unittest\nclass T(unittest.TestCase):\n def setUp(self): self.fail('fixture')\n def test_a(self): pass\n"
        code, result = self.run_case(source, "sample.py::T::test_a", "pytest")
        self.assertEqual((result["outcome"], result["non_call_failures"]), ("infrastructure_error", 1))

    def test_real_twisted_trial_assertion_remains_a_test_call_failure(self):
        source = "from twisted.trial.unittest import TestCase\nclass T(TestCase):\n def test_a(self): self.assertEqual(1,2)\n"
        code, result = self.run_case(source, "sample.T.test_a")
        self.assertEqual((code, result["outcome"], result["test_call_failures"]), (1, "test_failure", 1))


if __name__ == "__main__":
    unittest.main()
