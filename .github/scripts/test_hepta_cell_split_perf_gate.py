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
                "physical_split": 0.9,
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

    def test_reject_unmatched_ablation_request_counts(self):
        packet = synthetic_matrix()
        packet["runs"][2]["attempted"] += 1
        packet["runs"][2]["completed"] += 1
        with self.assertRaisesRegex(InvalidEvidence, "unmatched attempted-request"):
            analyze(packet)

    def test_native_batch_requires_actual_backend_call(self):
        packet = synthetic_matrix()
        run = next(row for row in packet["runs"]
                   if row["scopes"] == 64 and row["mode"] == "optimized_logical_split")
        run["native_backend_calls"] = 0
        with self.assertRaisesRegex(InvalidEvidence, "without a backend call"):
            analyze(packet)

    def test_reject_float_or_unsafe_rounded_integer_counters(self):
        packet = synthetic_matrix()
        packet["runs"][0]["attempted"] = 1000.0
        with self.assertRaisesRegex(InvalidEvidence, "exact bounded integer"):
            analyze(packet)
        packet = synthetic_matrix()
        packet["runs"][0]["communication_bytes"] = 2**63
        with self.assertRaisesRegex(InvalidEvidence, "exact bounded integer"):
            analyze(packet)
        packet = synthetic_matrix()
        packet["runs"][0]["fsync_count"] = True
        with self.assertRaisesRegex(InvalidEvidence, "exact bounded integer"):
            analyze(packet)

    def test_single_request_native_calls_are_not_physical_batches(self):
        packet = synthetic_matrix()
        optimized = next(
            row for row in packet["runs"]
            if row["mode"] == "optimized_logical_split" and row["scopes"] == 256
        )
        optimized["native_backend_calls"] = optimized["native_batch_requests"]
        with self.assertRaisesRegex(InvalidEvidence, "density below two"):
            analyze(packet)

    def test_rss_and_recovery_regressions_are_blocking(self):
        packet = synthetic_matrix()
        run = next(row for row in packet["runs"]
                   if row["scopes"] == 64 and row["mode"] == "optimized_logical_split")
        run["rss_peak_bytes"] += 1
        run["recovery_ms"] += 1
        result = analyze(packet)
        self.assertFalse(result["comparative_gate_passed"])
        self.assertTrue(any("peak RSS regressed" in v for v in result["violations"]))
        self.assertTrue(any("recovery time regressed" in v for v in result["violations"]))

    def test_physical_split_never_implicitly_qualifies_on_throughput_alone(self):
        packet = synthetic_matrix()
        result = analyze(packet)
        self.assertFalse(result["comparisons"][0]["physical_split_resource_eligible"])
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
