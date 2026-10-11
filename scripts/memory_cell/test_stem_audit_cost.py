"""Test only resource accounting; no pretend production cost measurement."""

from copy import deepcopy
import unittest

from stem_audit_archive import AuditError
from stem_audit_cost import audit_resources


def sample():
    result = dict(
        caches={
            "frozen": dict(
                hits=2,
                misses=2,
                evictions=0,
                retained_estimated_bytes=100,
                maximum_bytes=1024,
            )
        },
        backend_resident_weight_bytes={"frozen": 100_000},
        learning=[
            dict(
                arm="linear",
                stage=16,
                status="succeeded",
                inclusive_attempt_seconds=0.15,
                artifact_bytes=220,
                receipt=dict(
                    consumed_steps=4,
                    parameter_bytes=40,
                    gradient_bytes=40,
                    persistent_optimizer_bytes=0,
                ),
            ),
            dict(
                arm="linear",
                stage=32,
                status="failed",
                inclusive_attempt_seconds=0.2,
                error="fixture",
            ),
        ],
        reader=dict(
            actual_attempts=2,
            actual_successes=1,
            cache_hits=3,
            measured_call_seconds=1.5,
        ),
        index_costs=[dict(scope="s", seconds=0.5, file_bytes=1024)],
        cold_load={"shared": 1.0},
        process_peak_rss_kib=500000,
        retained_output_bytes_before_report=18000,
    )
    encoding = [
        dict(
            backend="frozen",
            cost=dict(
                cache_hit=False,
                incremental_encoder_seconds=0.75,
                extraction=dict(seconds=0.75, pairs=5, pair_tokens=250),
            ),
        ),
        dict(
            backend="frozen", cost=dict(cache_hit=True, incremental_encoder_seconds=0.0)
        ),
        dict(
            backend="frozen", cost=dict(cache_hit=True, incremental_encoder_seconds=0.0)
        ),
    ]
    return result, encoding


class CostTests(unittest.TestCase):
    def test_resource_receipt_keeps_unknown_work_explicit(self):
        report, encoded = sample()
        output = audit_resources(report, encoded)
        frozen = output["encoders"]["frozen"]
        self.assertEqual(frozen["successful_encoder_misses"], 1)
        self.assertEqual(frozen["total_reported_misses"], 2)
        self.assertEqual(frozen["unmatched_or_failed_encoder_misses"], 1)
        self.assertEqual(frozen["executed_query_candidate_pairs"], 5)
        self.assertEqual(frozen["executed_pair_tokens"], 250)
        self.assertEqual(frozen["measured_successful_encoding_seconds"], 0.75)
        self.assertEqual(output["head_training"]["linear"]["sgd_optimizer_steps"], 4)
        self.assertEqual(output["head_training"]["linear"]["failed_sessions"], 1)
        self.assertAlmostEqual(
            output["head_training"]["linear"]["attempted_training_seconds"], 0.35
        )
        self.assertEqual(output["reader_actual_calls"], 2)
        self.assertEqual(output["reader_cache_hits"], 3)
        self.assertEqual(output["index_files_reported_bytes"], 1024)
        self.assertFalse(output["hardware_benefit_over_421m_replicas_proven"])
        self.assertTrue(output["per_arm_energy_and_dollar_tco_unknown"])

    def test_cached_work_cannot_be_charged_as_new_forward_or_vice_versa(self):
        for mutate in ("cached-seconds", "missing-extraction", "relabelled-seconds"):
            report, encoded = sample()
            if mutate == "cached-seconds":
                encoded[1]["cost"]["incremental_encoder_seconds"] = 0.1
            elif mutate == "missing-extraction":
                del encoded[0]["cost"]["extraction"]
            else:
                encoded[0]["cost"]["extraction"]["seconds"] = 0.4
            with self.assertRaises(AuditError):
                audit_resources(report, encoded)

    def test_mismatched_cache_hits_fail_instead_of_proving_savings(self):
        report, encoded = sample()
        report["caches"]["frozen"]["hits"] = 3
        with self.assertRaisesRegex(AuditError, "cache hits"):
            audit_resources(report, encoded)

    def test_unmeasured_failed_miss_is_not_silently_removed(self):
        report, encoded = sample()
        report["caches"]["frozen"]["misses"] = 0
        with self.assertRaisesRegex(AuditError, "cache misses"):
            audit_resources(report, encoded)

    def test_unpinned_new_backend_cannot_be_inserted(self):
        report, encoded = sample()
        encoded.append(dict(backend="surprise", cost=deepcopy(encoded[1]["cost"])))
        with self.assertRaisesRegex(AuditError, "unknown logged"):
            audit_resources(report, encoded)

    def test_resource_limits_and_nan_are_hard_failures(self):
        for field, value in (
            ("retained_estimated_bytes", 1025),
            ("retained_estimated_bytes", -1),
        ):
            report, encoded = sample()
            report["caches"]["frozen"][field] = value
            with self.assertRaises(AuditError):
                audit_resources(report, encoded)
        report, encoded = sample()
        report["learning"][0]["inclusive_attempt_seconds"] = float("nan")
        with self.assertRaises(AuditError):
            audit_resources(report, encoded)

    def test_reader_reuse_does_not_masquerade_as_production_tco(self):
        report, encoded = sample()
        out = audit_resources(report, encoded)
        self.assertTrue(
            out["backend_shared_reader_cannot_be_naively_assigned_to_single_arm"]
        )
        self.assertTrue(out["per_arm_serving_latency_unknown"])
        self.assertFalse(out["energy_savings_proven"])


if __name__ == "__main__":
    unittest.main()
