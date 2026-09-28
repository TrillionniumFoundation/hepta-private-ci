import copy
import unittest
from summarize_measurements import summarize

class MeasurementsTests(unittest.TestCase):
    def samples(self):
        before = {"file_bytes": 200, "io": {"sync_calls": 0, "sync_errors": 0, "sync_micros": 0}}
        return [{"schema": "hepta.neuron.diagnostic.v2", "source_sha": "a" * 40,
                 "test_binary_digest": "b" * 64, "sample": i,
                 "model_kind": "deterministic_fixture_not_production", "qualification": False,
                 "recovery_micros": 10, "process_peak_rss_kib": None,
                 "measurement": {"returned_success": True, "total_micros": 20 + i,
                     "store_before": copy.deepcopy(before), "index_before": copy.deepcopy(before),
                     "store_after": {"file_bytes": 500, "io": {"sync_calls": 2, "sync_errors": 0, "sync_micros": 5}},
                     "index_after": {"file_bytes": 400, "io": {"sync_calls": 3, "sync_errors": 0, "sync_micros": 6}},
                     "witness_sync": {"sync_calls": 1, "sync_errors": 0, "sync_micros": 3}}} for i in range(64)]

    def test_executed_sample_summary_does_not_invent_rss_or_qualification(self):
        result = summarize(self.samples(), "a" * 40)
        self.assertEqual(result["request_micros"], {"p50": 51, "p95": 80, "p99": 83})
        self.assertIsNone(result["process_high_water_rss_kib"])
        self.assertFalse(result["qualification"])

    def test_source_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize(self.samples(), "c" * 40)

    def test_duplicate_observations_are_rejected(self):
        samples = self.samples(); samples[-1] = samples[0]
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_unmeasured_witness_is_rejected(self):
        samples = self.samples(); samples[0]["measurement"]["witness_sync"] = None
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

    def test_wrong_executed_sync_count_is_rejected(self):
        samples = self.samples(); samples[0]["measurement"]["index_after"]["io"]["sync_calls"] = 2
        with self.assertRaises(ValueError):
            summarize(samples, "a" * 40)

if __name__ == "__main__":
    unittest.main()
