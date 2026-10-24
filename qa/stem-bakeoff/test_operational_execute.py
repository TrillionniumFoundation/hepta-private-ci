import json
from pathlib import Path
import sys
import tempfile
import unittest

from operational_cohort_plan import canonical
from operational_execute import command_pair_qualifies, execute_command, sha_file, validate_result


class OperationalExecutionTests(unittest.TestCase):
    def test_deadline_has_real_kill_and_never_becomes_test_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("import time,unittest\nclass T(unittest.TestCase):\n def test_a(self): time.sleep(10)\n")
            result = execute_command({"id": "timeout", "runner": "unittest", "args": ["-q", "sample.T.test_a"]},
                sys.executable, root, root / "observation", {"cpu_seconds": 2, "address_space_bytes": 512 * 1024**2,
                "log_file_bytes": 1024 * 1024, "wall_timeout_seconds": 0.2})
            self.assertTrue(result["timed_out"])
            self.assertLess(result["returncode"], 0)
            self.assertEqual(result["outcome"], "infrastructure_error")
            self.assertFalse(command_pair_qualifies({"base": result, "candidate": {"outcome": "pass"}}))

    def test_resume_binds_actual_evidence_and_rejects_unsealed_extras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stderr.log").write_bytes(b"actual log\n")
            value = {"case_sha256": "case", "execution_plan_sha256": "plan", "files": {
                "stderr.log": {"bytes": 11, "sha256": sha_file(root / "stderr.log")}}}
            (root / "result.json").write_bytes(canonical(value))
            self.assertEqual(validate_result(root, "case", "plan"), value)
            with self.assertRaises(ValueError):
                validate_result(root, "different", "plan")
            (root / "extra.log").write_text("unsealed")
            with self.assertRaisesRegex(ValueError, "unsealed"):
                validate_result(root, "case", "plan")
            (root / "extra.log").unlink()
            (root / "stderr.log").write_bytes(b"altered log")
            with self.assertRaisesRegex(ValueError, "changed"):
                validate_result(root, "case", "plan")


if __name__ == "__main__":
    unittest.main()
