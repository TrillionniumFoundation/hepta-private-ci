"""Validator fixtures are deliberately not measurements of Agentd."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import hepta_memory_retrieval_slo as s


class SloTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        case = {"cache": "warm", "concurrency": 1, "owner_write_contention": False,
                "provider_rotation_contention": False}
        sample = case | {"total_us": 100, "stages_us": {stage: 10 for stage in s.STAGES},
                         "cpu_us": 80, "peak_rss_bytes": 1024, "allocation_count": 10,
                         "sqlite_read_count": 2, "candidate_count": 2, "node_count": 2,
                         "synapse_count": 1, "traversed_synapses": 4,
                         "abstained": False, "stale_rejected": False}
        # synthetic_fixture=False exercises validation acceptance in this UNIT
        # TEST ONLY. These values must never be retained as product baselines.
        self.document = {"schema": "hepta.memory-retrieval.e2e-samples.v1",
                         "source_head": self.head, "producer": "agentd-product",
                         "synthetic_fixture": False, "host_profile": "unit-fixture",
                         "measurement_run_id": "unit-fixture-not-production",
                         "clock": "fixture", "allocator_instrumentation": "fixture",
                         "sqlite_instrumentation": "fixture", "ranker_enabled": True,
                         "learning_sink_enabled": True,
                         "samples": [deepcopy(sample) | {"sample_id": str(i)} for i in range(100)]}
        self.policy = {"schema": "hepta.memory-retrieval.slo-policy.v1",
                       "host_profile": "unit-fixture", "minimum_samples_per_case": 100,
                       "required_cases": [case],
                       "limits": {"p95_us": 100, "p99_us": 100, "max_us": 100,
                                  "peak_rss_bytes": 1024, "abstention_ppm": 0,
                                  "stale_rejection_ppm": 0}}

    def validate(self):
        return s.validate(self.document, self.policy, self.head)

    def refused(self):
        with self.assertRaises(s.SloError):
            self.validate()

    def test_complete_sample_contract_has_no_release_authority(self):
        result = self.validate()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["workloads"][0]["p99_us"], 100)
        self.assertEqual(result["workloads"][0]["allocation_count"], 1000)
        self.assertFalse(result["productionImplementation"])
        self.assertFalse(result["independentAcceptance"])

    def test_wrong_head_fails(self):
        self.document["source_head"] = "b" * 40
        self.refused()

    def test_microbenchmark_fails(self):
        self.document["producer"] = "hnmf-microbenchmark"
        self.refused()

    def test_explicit_fixture_fails(self):
        self.document["synthetic_fixture"] = True
        self.refused()

    def test_wrong_host_fails(self):
        self.document["host_profile"] = "other-host"
        self.refused()

    def test_missing_stage_fails(self):
        del self.document["samples"][0]["stages_us"][s.STAGES[0]]
        self.refused()

    def test_missing_allocation_count_fails(self):
        del self.document["samples"][0]["allocation_count"]
        self.refused()

    def test_null_sqlite_count_is_not_zero(self):
        self.document["samples"][0]["sqlite_read_count"] = None
        self.refused()

    def test_boolean_counter_is_not_an_integer_measurement(self):
        self.document["samples"][0]["allocation_count"] = True
        self.refused()

    def test_nan_fails(self):
        self.document["samples"][0]["total_us"] = float("nan")
        self.refused()

    def test_overlapping_stages_fail(self):
        self.document["samples"][0]["stages_us"][s.STAGES[0]] = 100
        self.refused()

    def test_resource_ceiling_fails(self):
        self.document["samples"][0]["candidate_count"] = 513
        self.refused()

    def test_missing_learning_sink_fails(self):
        self.document["learning_sink_enabled"] = False
        self.refused()

    def test_missing_ranker_fails(self):
        self.document["ranker_enabled"] = False
        self.refused()

    def test_missing_workload_fails(self):
        self.policy["required_cases"].append(self.policy["required_cases"][0] | {"cache": "cold"})
        self.refused()

    def test_missing_contention_field_fails(self):
        del self.document["samples"][0]["owner_write_contention"]
        self.refused()

    def test_too_few_samples_fail(self):
        self.document["samples"].pop()
        self.refused()

    def test_duplicate_samples_fail(self):
        self.document["samples"][1]["sample_id"] = self.document["samples"][0]["sample_id"]
        self.refused()

    def test_real_limit_breach_returns_failed_receipt(self):
        self.policy["limits"]["p99_us"] = 99
        result = self.validate()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failures"][0]["metric"], "p99_us")

    def test_rates_are_computed_not_supplied_by_caller(self):
        self.document["samples"][0]["stale_rejected"] = True
        result = self.validate()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["workloads"][0]["stale_rejection_ppm"], 10000)

    def test_nearest_rank_tail_percentile(self):
        self.assertEqual(s.percentiles(list(range(1, 101))),
                         {"p50_us": 50, "p95_us": 95, "p99_us": 99, "max_us": 100})

    def test_content_addressed_receipt_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = s.retain({"unit_fixture": True}, directory)
            second = s.retain({"unit_fixture": True}, directory)
            self.assertEqual(first, second)
            self.assertEqual(json.loads(first.read_bytes()), {"unit_fixture": True})
            first.write_text("corrupt")
            with self.assertRaises(s.SloError):
                s.retain({"unit_fixture": True}, directory)


if __name__ == "__main__":
    unittest.main()
