"""Negative/identity tests. Synthetic rows never constitute real-model evidence."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from replacement_gate import EXPECTED, SPLITS, SCALES, assess, score_rows, validate_registry

REGISTRY = json.loads(Path(__file__).with_name("replacement_models.json").read_text())
H = "a" * 64


def sample_rows(split):
    return [dict(source_id=f"{split}-{i}", source_group_id=f"g-{split}-{i}",
                 label=i % 4, probabilities=[.7 if k == i % 4 else .1 for k in range(4)],
                 is_ood=split == "ood", language="en") for i in range(8)]


def arm(spec):
    return dict(repository=spec["repository"], revision=spec["revision"],
                loaded_weight_sha256=spec["weight_sha256"], runtime_mode="SHADOW_ONLY",
                checkpoint_inventory_sha256=H, runtime_sha256=H,
                dataset_sha256=H, model_execution_receipt_sha256=H,
                training_plan_sha256=H, inference_kind=spec["role"],
                actual_model_forward_observed=True, no_production_authority=True,
                trained_head_sha256=H, encoder_frozen=True,
                splits={name: sample_rows(name) for name in SPLITS})


def sample_evidence():
    return dict(schema="hepta.neuron.replacement-evidence.v1",
                arms={name: arm(spec) for name, spec in REGISTRY["models"].items()},
                safety=dict(frozen_threshold_plan_sha256=H,
                            independent_future_window=True,
                            class_imbalance_negative_transfer_tested=True),
                resources={str(scale): dict(logical_cells=scale, active_cells=1,
                  actual_private_head_instances=scale, host_runtime_sha256=H,
                  physical_model_receipt_sha256=H, target_hardware=True,
                  peak_rss_bytes=1024, gpu_peak_bytes=0,
                  throughput_per_second=1.0, latency_samples_ms=[1.0] * 100)
                           for scale in SCALES},
                lifecycle={name: H for name in ("artifact_cas_commit",
                 "predecessor_checkpoint_migration", "route_cutover",
                 "supervisor_generation_fence", "crash_reopen_reconcile",
                 "rollback_restore", "old_generation_final_use_denied",
                 "external_signature_verifier_digest")})


class ReplacementGateTests(unittest.TestCase):
    def test_exact_five_publisher_pins(self):
        self.assertEqual(validate_registry(REGISTRY), [])

    def test_registry_rejects_mutated_weight(self):
        reg = copy.deepcopy(REGISTRY)
        reg["models"]["arctic_305m"]["weight_sha256"] = "not-a-sha"
        self.assertTrue(validate_registry(reg))

    def test_registry_rejects_false_activation(self):
        reg = copy.deepcopy(REGISTRY)
        reg["production_activation_allowed"] = True
        self.assertTrue(validate_registry(reg))

    def test_blank_bundle_keeps_all_gates_open(self):
        verdict = assess(REGISTRY, None)
        self.assertTrue(all(v["preflight"] == "BLOCKED" for v in verdict["stages"].values()))
        self.assertFalse(verdict["production_activation_allowed"])

    def test_synthetic_good_receipts_cannot_authorize(self):
        verdict = assess(REGISTRY, sample_evidence())
        self.assertTrue(all(v["preflight"] == "REVIEW_REQUIRED" for v in verdict["stages"].values()))
        self.assertFalse(verdict["all_six_production_blockers_closed"])
        self.assertEqual(verdict["authority"], "DENY_ALL")

    def test_rows_accuracy_and_brier(self):
        m = score_rows(sample_rows("future_1"))
        self.assertAlmostEqual(m["accuracy"], 1.)
        self.assertAlmostEqual(m["balanced_accuracy"], 1.)
        self.assertAlmostEqual(m["brier_multiclass_sum"], .12)
        self.assertEqual(m["coverage"], 1.)

    def test_nan_prediction_denied(self):
        rows = sample_rows("future_1")
        rows[0]["probabilities"][0] = float("nan")
        with self.assertRaises(ValueError):
            score_rows(rows)

    def test_unnormalized_prediction_denied(self):
        rows = sample_rows("future_1")
        rows[0]["probabilities"] = [1., 1., 0., 0.]
        with self.assertRaises(ValueError):
            score_rows(rows)

    def test_bool_probability_denied(self):
        rows = sample_rows("future_1")
        rows[0]["probabilities"][0] = True
        with self.assertRaises(ValueError):
            score_rows(rows)

    def test_duplicate_group_denied(self):
        rows = sample_rows("future_1")
        rows[0]["source_group_id"] = rows[1]["source_group_id"]
        with self.assertRaises(ValueError):
            score_rows(rows)

    def test_baseline_encoder_only_is_not_full_policy(self):
        ev = sample_evidence()
        ev["arms"][EXPECTED[0]]["inference_kind"] = "encoder_only"
        self.assertEqual(assess(REGISTRY, ev)["stages"]["1_baseline"]["preflight"], "BLOCKED")

    def test_cross_arm_rows_must_match(self):
        ev = sample_evidence()
        ev["arms"][EXPECTED[-1]]["splits"]["future_1"][0]["label"] = 2
        self.assertEqual(assess(REGISTRY, ev)["stages"]["3_encoder_head"]["preflight"], "BLOCKED")

    def test_training_budget_must_match(self):
        ev = sample_evidence()
        ev["arms"][EXPECTED[-1]]["training_plan_sha256"] = "b" * 64
        self.assertEqual(assess(REGISTRY, ev)["stages"]["3_encoder_head"]["preflight"], "BLOCKED")

    def test_ood_split_required(self):
        ev = sample_evidence()
        ev["arms"][EXPECTED[0]]["splits"]["ood"] = sample_rows("future_1")
        self.assertEqual(assess(REGISTRY, ev)["stages"]["1_baseline"]["preflight"], "BLOCKED")

    def test_three_samples_cannot_prove_p99(self):
        ev = sample_evidence()
        ev["resources"]["4096"]["latency_samples_ms"] = [1., 2., 3.]
        self.assertEqual(assess(REGISTRY, ev)["stages"]["5_host_resources"]["preflight"], "BLOCKED")

    def test_cpu_not_target_host_denied(self):
        ev = sample_evidence()
        ev["resources"]["1024"]["target_hardware"] = False
        self.assertEqual(assess(REGISTRY, ev)["stages"]["5_host_resources"]["preflight"], "BLOCKED")

    def test_old_generation_denial_receipt_required(self):
        ev = sample_evidence()
        del ev["lifecycle"]["old_generation_final_use_denied"]
        self.assertEqual(assess(REGISTRY, ev)["stages"]["6_lifecycle"]["preflight"], "BLOCKED")

    def test_external_verifier_needed(self):
        ev = sample_evidence()
        del ev["lifecycle"]["external_signature_verifier_digest"]
        self.assertEqual(assess(REGISTRY, ev)["stages"]["6_lifecycle"]["preflight"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
