"""Actual waited tool-process integration and failure-retention tests."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .tool_runtime import TARIFF, invoke, run_episode
from . import tool_runtime


class RealToolTests(unittest.TestCase):
    def test_real_repair_check_and_independent_delivery_oracle(self):
        task = {"id": "development-two-bugs", "scale": -3, "offset": 5, "bugs": ["scale", "offset"]}
        plan = ("CHECK", "REPAIR", "CHECK", "REPAIR", "STOP")
        result = run_episode(lambda history: plan[len(history)], task)
        self.assertEqual((result["status"], result["quality"], result["delivered"]), ("completed", 1, True))
        self.assertEqual(
            result["history"],
            (("CHECK", "2"), ("REPAIR", "attempted"), ("CHECK", "1"), ("REPAIR", "attempted"), ("STOP", "delivered")),
        )
        self.assertNotEqual(result["initial_sha256"], result["final_sha256"])
        self.assertEqual(result["events"][-1]["result"], {"quality": 1, "failed_inputs": []})
        self.assertAlmostEqual(result["tariff"], sum(TARIFF[a] for a in plan) + TARIFF["ORACLE"])
        self.assertTrue(all(e["returncode"] == 0 for e in result["events"] if "returncode" in e))

    def test_expiry_and_cancel_retain_work_and_do_not_deliver_repaired_source(self):
        task = {"id": "development-correct", "scale": 2, "offset": 3, "bugs": []}
        expired = run_episode(lambda _: "REPAIR", task)
        cancelled = run_episode(lambda _: "CHECK", task, cancel_after=1)
        self.assertEqual((expired["status"], expired["quality"]), ("expired", 0))
        self.assertEqual((cancelled["status"], cancelled["quality"]), ("cancelled", 0))
        self.assertEqual(expired["events"][-1]["result"]["quality"], 1)
        self.assertAlmostEqual(expired["tariff"], 5 * TARIFF["REPAIR"] + TARIFF["ORACLE"])
        self.assertAlmostEqual(cancelled["tariff"], TARIFF["CHECK"] + TARIFF["ORACLE"])

    def test_real_failure_timeout_and_marker_independent_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.py"
            path.write_text("def solve(: pass", encoding="utf-8")
            failed = invoke("CHECK", path, 2, 3)
            self.assertEqual(failed["status"], "failed")
            self.assertIn("SyntaxError", failed["stderr"])
            self.assertEqual(failed["tariff"], TARIFF["CHECK"])
            path.write_text("while True: pass", encoding="utf-8")
            timed = invoke("CHECK", path, 2, 3, timeout=0.05)
            self.assertEqual(timed["status"], "timeout")
            self.assertIsNotNone(timed["returncode"])
            path.write_text("def solve(x): return 2*x+102", encoding="utf-8")
            oracle = invoke("ORACLE", path, 2, 3)
            self.assertEqual(oracle["result"]["quality"], 0)
            self.assertEqual(oracle["result"]["failed_inputs"], list(range(-11, 14)))

    def test_exit_zero_malformed_tool_results_fail_with_raw_bytes_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.py"
            for output in ("[]", "null", "{}", '{"outcome":3}', '{"outcome":"bad"}'):
                path.write_text(f"import sys\nprint({output!r})\nsys.exit(0)\n", encoding="utf-8")
                result = invoke("CHECK", path, 2, 3)
                self.assertEqual(
                    (result["returncode"], result["status"], result["stdout"]), (0, "failed", output + "\n")
                )
                self.assertFalse(result["output_schema_valid"])

    def test_cancel_reason_survives_real_verification_failure(self):
        def corrupt_oracle(mode, path, *args, **kwargs):
            if mode == "ORACLE":
                path.write_text("def solve(: pass", encoding="utf-8")
            return invoke(mode, path, *args, **kwargs)

        task = {"id": "development-cancel-and-failure", "scale": 2, "offset": 3, "bugs": []}
        with patch.object(tool_runtime, "invoke", side_effect=corrupt_oracle):
            row = run_episode(lambda _: "CHECK", task, cancel_after=1)
        self.assertEqual(
            (row["status"], row["termination_reason"], row["verification_status"], row["quality"]),
            ("cancelled", "cancelled", "failed", 0),
        )
        self.assertIn("SyntaxError", row["events"][-1]["stderr"])


if __name__ == "__main__":
    unittest.main()
