import copy
import unittest

from summarize_measurements import summarize


class MeasurementsTests(unittest.TestCase):
    def samples(self):
        before = {
            "file_bytes": 200,
            "io": {"sync_calls": 0, "sync_errors": 0, "sync_micros": 0},
        }
        return [
            {
                "schema": "hepta.neuron.diagnostic.v2",
                "source_sha": "a" * 40,
                "test_binary_digest": "b" * 64,
                "sample": index,
                "model_kind": "deterministic_fixture_not_production",
                "qualification": False,
                "recovery_micros": 10,
                "process_peak_rss_kib": None,
                "measurement": {
                    "returned_success": True,
                    "total_micros": 20 + index,
                    "receipt_encode_micros": 8,
                    "full_receipt_materialize_micros": 3,
                    "store_commit_micros": 9,
                    "index_commit_micros": 10,
                    "store_before": copy.deepcopy(before),
                    "index_before": copy.deepcopy(before),
                    "store_after": {
                        "file_bytes": 500,
                        "io": {
                            "sync_calls": 2,
                            "sync_errors": 0,
                            "sync_micros": 5,
                        },
                    },
                    "index_after": {
                        "file_bytes": 400,
                        "io": {
                            "sync_calls": 3,
                            "sync_errors": 0,
                            "sync_micros": 6,
                        },
                    },
                    "witness_sync": {
                        "sync_calls": 1,
                        "sync_errors": 0,
                        "sync_micros": 3,
                    },
                },
            }
            for index in range(64)
        ]

    def test_executed_sample_summary_keeps_phase_boundaries(self):
        result = summarize(self.samples(), "a" * 40)
        self.assertEqual(result["request_micros"], {"p50": 51, "p95": 80, "p99": 83})
        self.assertEqual(
            result["request_minus_measured_sync_micros"],
            {"p50": 37, "p95": 66, "p99": 69},
        )
        self.assertEqual(
            result["receipt_encode_micros_per_request"],
            {"p50": 8, "p95": 8, "p99": 8},
        )
        self.assertEqual(
            result["full_receipt_materialize_micros_per_request"],
            {"p50": 3, "p95": 3, "p99": 3},
        )
        self.assertEqual(
            result["receipt_encode_minus_materialize_micros_per_request"],
            {"p50": 5, "p95": 5, "p99": 5},
        )
        self.assertEqual(
            result["generation_store_non_sync_micros_per_request"],
            {"p50": 4, "p95": 4, "p99": 4},
        )
        self.assertEqual(
            result["runtime_index_non_sync_micros_per_request"],
            {"p50": 4, "p95": 4, "p99": 4},
        )
        self.assertEqual(
            result["store_sync_micros_per_request"],
            {"p50": 5, "p95": 5, "p99": 5},
        )
        self.assertEqual(
            result["index_sync_micros_per_request"],
            {"p50": 6, "p95": 6, "p99": 6},
        )
        self.assertEqual(
            result["witness_sync_micros_per_request"],
            {"p50": 3, "p95": 3, "p99": 3},
        )
        self.assertEqual(
            result["summed_sync_micros_per_request"],
            {"p50": 14, "p95": 14, "p99": 14},
        )
        self.assertEqual(
            result["phase_share_basis_points"]["receipt_encode"],
            {"p50": 1538, "p95": 3478, "p99": 4000},
        )
        self.assertEqual(
            result["phase_share_basis_points"]["full_receipt_materialize"],
            {"p50": 577, "p95": 1304, "p99": 1500},
        )
        self.assertEqual(
            result["phase_share_basis_points"]["summed_sync"],
            {"p50": 2692, "p95": 6087, "p99": 7000},
        )
        self.assertTrue(result["phase_shares_are_independent"])
        self.assertEqual(
            result["generation_store_growth_bytes"],
            {"p50": 300, "p95": 300, "p99": 300},
        )
        self.assertEqual(
            result["runtime_index_growth_bytes"],
            {"p50": 200, "p95": 200, "p99": 200},
        )
        self.assertIsNone(result["process_high_water_rss_kib"])
        self.assertFalse(result["qualification"])

    def test_source_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize(self.samples(), "c" * 40)

    def test_duplicate_observations_are_rejected(self):
        samples = self.samples()
        samples[-1] = samples[0]
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_unmeasured_witness_is_rejected(self):
        samples = self.samples()
        samples[0]["measurement"]["witness_sync"] = None
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_wrong_executed_sync_count_is_rejected(self):
        samples = self.samples()
        samples[0]["measurement"]["index_after"]["io"]["sync_calls"] = 2
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_measured_sync_cannot_exceed_total_request_time(self):
        samples = self.samples()
        samples[0]["measurement"]["total_micros"] = 13
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_nested_materialization_cannot_exceed_receipt_encode(self):
        samples = self.samples()
        samples[0]["measurement"]["full_receipt_materialize_micros"] = 9
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_sync_cannot_exceed_enclosing_commit_phase(self):
        samples = self.samples()
        samples[0]["measurement"]["store_commit_micros"] = 4
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_phase_cannot_exceed_total_request_time(self):
        samples = self.samples()
        samples[0]["measurement"]["receipt_encode_micros"] = 21
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)


if __name__ == "__main__":
    unittest.main()
