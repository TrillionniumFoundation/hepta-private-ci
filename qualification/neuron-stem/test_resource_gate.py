"""Offline budget gate contracts; all numbers are synthetic test fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from resource_gate import (load_strict_resource_evidence, paired_resource_gate,
                           verify_summary, write_immutable_resource_gate)


def fixture(model="jina-v5-text-nano"):
    return {
        "schema": "hepta.jina-v5-shadow-scale-probe.v1",
        "status": "real_backend_research_only",
        "model": model, "revision": "a" * 40,
        "production_promotion_permitted": False,
        "production_worker_microbatch_verified": False,
        "sqlite_clean_reopen_ok": True,
        "sqlite_unclean_crash_recovery_verified": False,
        "ndu_signed_verified": False,
        "heads_initialized_not_learned": True,
        "full_active_cell_coverage": True,
        "total_logical_cells": 64, "actual_active_heads": 10,
        "distinct_ticked_cells": 10, "total_requests": 40,
        "seed": 11, "head_type": "linear", "head_parameter_ceiling": 16384,
        "feature_dimension": 256, "context_token_budget": 512,
        "representation": "joint", "requested_batch_size": 8,
        "task_similarity": "medium", "input_repeat_fraction": .5,
        "active_fraction": .25,
        "actual_encoder_batch_calls": 5, "actual_encoder_examples": 20,
        "process_wall_seconds": 1., "process_cpu_seconds": .8,
        "aggregate_throughput_rps": 40.,
        "max_observed_rss_bytes": 500000000,
        "observed_total_physical_ram_bytes": 16000000000,
        "environment": {
            "os": "Linux", "machine_arch": "x86_64",
            "logical_cpu_count": 8, "python": "3.12",
            "dependency_versions": {"torch": "test-version"},
        },
        "dataset": {"dataset_digest": "sha256-of-test-cases"},
        "scales": [{
            "logical_cells": 64, "active_fraction": .25,
            "input_repeat_fraction": .5, "task_similarity": "medium",
            "observed_records": 40, "latency_paths": {
                "backend_batch": {"n": 30, "p99_ms": 70.},
                "cache_hit_head": {"n": 10, "p99_ms": 12.},
            },
        }],
    }


BUDGET = {
    "schema": "hepta.neuron-research-resource-budget.v1",
    "signed_production_budget": False,
    "max_peak_rss_bytes": 1000000000,
    "max_request_p99_ms": 100.,
    "min_throughput_rps": 20.,
    "max_cpu_seconds_ratio": 2.,
}


class ResourceGateTests(unittest.TestCase):
    def test_resource_json_cannot_hide_duplicate_metric_or_replace_prior_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "resource.json"
            source.write_text('{"candidate_rss_bytes":100,"candidate_rss_bytes":0}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON evidence field"):
                load_strict_resource_evidence(source)
            source.write_text('{"p99_ms":NaN}')
            with self.assertRaisesRegex(ValueError, "non-standard JSON number"):
                load_strict_resource_evidence(source)
            source.write_text('[1,2,3]')
            with self.assertRaisesRegex(ValueError, "JSON object"):
                load_strict_resource_evidence(source)
            source.write_text(json.dumps({"schema": "safe"}))
            self.assertEqual(load_strict_resource_evidence(source)["schema"], "safe")
            report_path = root / "qualified.json"
            write_immutable_resource_gate(report_path, {"production_promotion_permitted": False})
            first = report_path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_immutable_resource_gate(
                    report_path, {"production_promotion_permitted": True})
            self.assertEqual(report_path.read_bytes(), first)
            with self.assertRaises(ValueError):
                write_immutable_resource_gate(root / "nan.json", {"rss": float("nan")})
            self.assertFalse((root / "nan.json").exists())

    def test_pair_pass_is_always_research_only(self):
        before = fixture()
        after = fixture("jina-v5-text-small")
        after["process_cpu_seconds"] = 1.0
        after["aggregate_throughput_rps"] = 30.
        report = paired_resource_gate(before, after, BUDGET)
        self.assertTrue(report["research_resource_gate_passed"])
        self.assertFalse(report["production_promotion_permitted"])
        self.assertFalse(report["production_microbatch_qualified"])
        self.assertFalse(report["same_physical_host_attested"])
        self.assertEqual(report["candidate_model"], "jina-v5-text-small")

    def test_failing_quality_budget_is_not_hidden(self):
        before = fixture()
        after = fixture("jina-v5-text-small")
        after["max_observed_rss_bytes"] = 1100000000
        report = paired_resource_gate(before, after, BUDGET)
        self.assertFalse(report["research_resource_gate_passed"])
        self.assertFalse(report["checks"]["peak_rss"])

    def test_mismatched_workload_or_hardware_fails_closed(self):
        before = fixture()
        after = fixture("jina-v5-text-small")
        after["feature_dimension"] = 512
        with self.assertRaisesRegex(ValueError, "workload mismatch"):
            paired_resource_gate(before, after, BUDGET)
        after = fixture("jina-v5-text-small")
        after["environment"]["logical_cpu_count"] = 24
        with self.assertRaisesRegex(ValueError, "host environment"):
            paired_resource_gate(before, after, BUDGET)
        after = fixture("jina-v5-text-small")
        after["dataset"]["dataset_digest"] = "different-data"
        with self.assertRaisesRegex(ValueError, "different data evidence"):
            paired_resource_gate(before, after, BUDGET)

    def test_source_and_coverage_spoof_rejected(self):
        base = fixture()
        base["full_active_cell_coverage"] = False
        with self.assertRaisesRegex(ValueError, "not actually covered"):
            verify_summary(base)
        base = fixture()
        base["status"] = "synthetic_only"
        with self.assertRaisesRegex(ValueError, "synthetic"):
            verify_summary(base)
        base = fixture()
        base["actual_encoder_batch_calls"] = 0
        with self.assertRaisesRegex(ValueError, "real Encoder"):
            verify_summary(base)
        base = fixture()
        base["scales"][0]["latency_paths"]["backend_batch"]["n"] = 15
        with self.assertRaisesRegex(ValueError, "do not cover"):
            verify_summary(base)

    def test_budget_must_be_explicit_and_non_authoritative(self):
        before = fixture()
        after = fixture("jina-v5-text-small")
        policy = dict(BUDGET)
        policy["signed_production_budget"] = True
        with self.assertRaisesRegex(ValueError, "cannot issue production"):
            paired_resource_gate(before, after, policy)


if __name__ == "__main__":
    unittest.main()
