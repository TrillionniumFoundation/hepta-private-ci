"""Regression tests for diagnostic-only CellSplit performance comparison."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from hepta_cell_split_perf_gate import InvalidEvidence, MODES, SCOPES, analyze


def synthetic_matrix():
    runs = []
    for scopes in SCOPES:
        for mode in MODES:
            speed = {
                "no_split": 1.0,
                "logical_split": 1.2,
                "optimized_logical_split": 1.5,
                "physical_split": 1.1,
            }[mode]
            work = 1000
            optimized = mode == "optimized_logical_split"
            runs.append({
                "mode": mode,
                "scopes": scopes,
                "attempted": work,
                "completed": work,
                "failed_requests": 0,
                "elapsed_seconds": 10 / speed,
                "p50_ms": 2 if not optimized else 1,
                "p95_ms": 5 if not optimized else 3,
                "p99_ms": 10 if not optimized else 7,
                "cpu_seconds": 30 if not optimized else 20,
                "rss_peak_bytes": 10000000,
                "communication_bytes": 100000 if not optimized else 70000,
                "native_backend_calls": 1000 if not optimized else 250,
                "native_batch_requests": 0 if not optimized else 1000,
                "fsync_count": 500 if not optimized else 125,
                "lock_wait_ms": 500 if not optimized else 200,
                "recovery_ms": 100,
                "negative_transfer_rate": 0,
            })
    return {
        "schema": "hepta.cell-split.performance.v1",
        "source_sha": "a" * 40,
        "hardware_id": "test-fixture-not-attested",
        "model_digest": "test-model",
        "workload_digest": "synthetic-workload",
        "runs": runs,
    }


class CellSplitPerformanceGateTests(unittest.TestCase):
    def test_complete_four_by_four_matrix_remains_diagnostic(self):
        result = analyze(synthetic_matrix())
        self.assertTrue(result["comparative_gate_passed"])
        self.assertEqual(len(result["comparisons"]), 4)
        self.assertFalse(result["production_evidence_verified"])
        self.assertFalse(result["production_activation_authorized"])

    def test_physical_split_must_not_regress_against_no_change(self):
        packet = synthetic_matrix()
        candidate = next(row for row in packet["runs"]
                         if row["scopes"] == 4096 and row["mode"] == "physical_split")
        candidate["elapsed_seconds"] = 12
        result = analyze(packet)
        self.assertFalse(result["comparative_gate_passed"])
        self.assertTrue(any("4096: physical throughput" in reason
                            for reason in result["violations"]))
        self.assertFalse(result["production_activation_authorized"])

    def test_reject_missing_and_duplicate_runs(self):
        packet = synthetic_matrix()
        packet["runs"].pop()
        with self.assertRaises(InvalidEvidence):
            analyze(packet)
        packet = synthetic_matrix()
        packet["runs"][1] = packet["runs"][0]
        with self.assertRaises(InvalidEvidence):
            analyze(packet)

    def test_detect_p99_and_communication_regression(self):
        packet = synthetic_matrix()
        target = next(row for row in packet["runs"]
                      if row["scopes"] == 1024 and row["mode"] == "optimized_logical_split")
        target["p99_ms"] = 20
        target["communication_bytes"] = 200000
        result = analyze(packet)
        self.assertFalse(result["comparative_gate_passed"])
        self.assertTrue(any("1024: optimized p99" in x for x in result["violations"]))
        self.assertFalse(result["production_activation_authorized"])

    def test_reject_nonfinite_and_inconsistent_measurements(self):
        packet = synthetic_matrix()
        packet["runs"][0]["cpu_seconds"] = float("nan")
        with self.assertRaises(InvalidEvidence):
            analyze(packet)
        packet = synthetic_matrix()
        packet["runs"][0]["completed"] = 1001
        with self.assertRaises(InvalidEvidence):
            analyze(packet)
        packet = synthetic_matrix()
        packet["runs"][0]["p95_ms"] = 99
        with self.assertRaises(InvalidEvidence):
            analyze(packet)


if __name__ == "__main__":
    unittest.main()
