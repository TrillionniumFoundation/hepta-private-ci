"""Validator fixtures are deliberately not measurements of Agentd."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import subprocess
import unittest

from scripts import hepta_memory_retrieval_slo as s


class SloTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        self.tree = "b" * 40
        case = {"cache": "warm", "concurrency": 1, "owner_write_contention": False,
                "provider_rotation_contention": False}
        sample = case | {"total_us": 100, "stages_us": {stage: 10 for stage in s.STAGES},
                         "cpu_us": 80, "peak_rss_bytes": 1024, "allocation_count": 10,
                         "sqlite_read_count": 2, "candidate_count": 2, "node_count": 2,
                         "synapse_count": 1, "traversed_synapses": 4,
                         "abstained": False, "stale_rejected": False}
        # synthetic_fixture=False exercises validation acceptance in this UNIT
        # TEST ONLY. These values must never be retained as product baselines.
        self.document = {"schema": "hepta.memory-retrieval.e2e-samples.v2",
                         "source_head": self.head, "source_tree": self.tree, "producer": "agentd-product",
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
        return s.validate(self.document, self.policy, self.head, self.tree)

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


    def test_wrong_or_absent_tree_fails(self):
        for value in (None, "c" * 40, True, "B" * 40):
            self.document["source_tree"] = value
            self.refused()

    def test_old_samples_are_not_silently_upgraded(self):
        self.document["schema"] = "hepta.memory-retrieval.e2e-samples.v1"
        self.refused()

    def test_malformed_objects_fail_with_typed_errors(self):
        for value in (None, [], True, "not an object"):
            with self.assertRaises(s.SloError):
                s.validate(value, self.policy, self.head, self.tree)
            with self.assertRaises(s.SloError):
                s.validate(self.document, value, self.head, self.tree)
        for name in ("samples", "stages_us"):
            original = deepcopy(self.document)
            if name == "samples":
                self.document["samples"][0] = None
            else:
                self.document["samples"][0][name] = None
            self.refused()
            self.document = original

    def test_optional_limits_are_also_strict_integers(self):
        for value in (True, -1, float("inf"), float("nan"), 1.5):
            self.policy["limits"]["cpu_us"] = value
            self.refused()

    def test_duplicate_workload_and_out_of_range_rate_refused(self):
        self.policy["required_cases"] *= 2
        self.refused()
        self.policy["required_cases"].pop()
        self.policy["limits"]["abstention_ppm"] = 1_000_001
        self.refused()

    def test_fractional_ppm_cannot_hide_a_rate_breach(self):
        # One rejection in 101 observations is 9900.99 ppm, not <= 9900.
        self.document["samples"].append(deepcopy(self.document["samples"][0]) | {"sample_id": "100"})
        self.document["samples"][0]["stale_rejected"] = True
        self.policy["limits"]["stale_rejection_ppm"] = 9900
        result = self.validate()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["workloads"][0]["stale_rejection_ppm"], 9901)
        self.assertEqual(result["rate_rounding"], "ceiling_ppm")

    def test_raw_json_rejects_duplicate_keys_and_nonfinite_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.json"
            for value in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                path.write_text(value)
                with self.assertRaises(s.SloError):
                    s.load(path)


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "SLO unit test")
        self.git("config", "user.email", "slo-unit@example.invalid")
        (self.root / "source.txt").write_text("real temporary Git object; no product measurements\n")
        self.git("add", "source.txt")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_actual_commit_tree_and_parent_are_observed(self):
        self.assertEqual(s.bind_source(self.root, self.head), {
            "commit": self.head, "tree": self.git("rev-parse", "HEAD^{tree}"), "parents": []})
        (self.root / "source.txt").write_text("second real Git object\n")
        self.git("commit", "-qam", "second fixture")
        second = self.git("rev-parse", "HEAD")
        self.assertEqual(s.bind_source(self.root, second)["parents"], [self.head])

    def test_wrong_head_and_invalid_identity_refused(self):
        for head in ("a" * 40, None, "HEAD", "A" * 40, "--help"):
            with self.assertRaises(s.SloError):
                s.bind_source(self.root, head)

    def test_tracked_and_untracked_changes_refused(self):
        (self.root / "source.txt").write_text("dirty\n")
        with self.assertRaises(s.SloError):
            s.bind_source(self.root, self.head)
        self.git("checkout", "--", "source.txt")
        (self.root / "untracked.txt").write_text("untracked\n")
        with self.assertRaises(s.SloError):
            s.bind_source(self.root, self.head)

    def test_non_repository_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(s.SloError):
                s.bind_source(Path(directory), self.head)


if __name__ == "__main__":
    unittest.main()
