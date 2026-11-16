"""Protocol tests use synthetic signed paired outcomes, never a performance claim."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import a0_deployment_evidence as a0
import paired_shadow_analysis as pair


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class PairedShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.fingerprint = sha(public)
        self.pub_path = self.root / "evaluator.pem"
        self.pub_path.write_bytes(self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ))
        budget = lambda name: {
            "artifact_digest": sha(name.encode()),
            "encoder_digest": sha(b"same frozen encoder"),
            "training_data_digest": sha(b"same training examples"),
            "parameter_count_total": 64,
            "state_bytes": 2048,
            "optimizer_steps": 100,
        }
        one = lambda v: {
            "utility_micro": v,
            "long_reward_micro": v * 2,
            "future_retained": True,
            "negative_transfer": False,
            "ood_false_accept": False,
            "cpu_micros": 10,
            "peak_rss_bytes": 4096,
            "latency_micros": 20,
        }
        self.payload = {
            "schema": pair.SCHEMA,
            "experiment_id": "synthetic-qualification-only",
            "phase": "A1",
            "evaluator_key_id": self.fingerprint,
            "executor_key_id": sha(b"executor"),
            "selector_key_id": sha(b"selector"),
            "preregistered_at_utc": "2026-10-01T00:00:00Z",
            "training_cutoff_utc": "2026-10-03T00:00:00Z",
            "evaluation_asof_utc": "2026-10-07T00:00:00Z",
            "host_profile_digest": sha(b"host"),
            "a0_registry_sha256": sha(b"registry"),
            "frozen_baseline": True,
            "no_change_arm": "no-change-v1",
            "arms": {
                "no-change-v1": {**budget("no-change"), "optimizer_steps": 0},
                "v2": budget("v2"),
            },
            "candidate_optimizer_steps": 100,
            "training_dataset_digest": sha(b"same training examples"),
            "total_parameter_ceiling": 128,
            "total_state_bytes_ceiling": 4096,
            "samples": [
                {
                    "case_id": "case-future",
                    "cell_id": "cell-a",
                    "input_digest": sha(b"future-input"),
                    "split": "future",
                    "event_time_utc": "2026-10-05T00:00:00Z",
                    "label_available_at_utc": "2026-10-06T00:00:00Z",
                    "outcomes": {"no-change-v1": one(10), "v2": one(11)},
                },
                {
                    "case_id": "case-ood",
                    "cell_id": "cell-a",
                    "input_digest": sha(b"ood-input"),
                    "split": "ood",
                    "event_time_utc": "2026-10-05T00:00:00Z",
                    "label_available_at_utc": "2026-10-06T00:00:00Z",
                    "outcomes": {"no-change-v1": one(10), "v2": one(7)},
                },
            ],
            "scale_receipts": [],
        }
        self.evidence_file = self.root / "signed-evaluation.json"

    def verify(self) -> dict:
        envelope = {
            "payload": self.payload,
            "signer_key_id": self.fingerprint,
            "signature_b64": base64.b64encode(
                self.key.sign(a0.canonical(self.payload))
            ).decode(),
        }
        self.evidence_file.write_bytes(a0.canonical(envelope))
        public, identity = a0.load_public_key(self.pub_path)
        value = a0.verify_signed(self.evidence_file, public, identity, pair.SCHEMA)
        return pair.analyze(value, identity)

    def test_valid_paired_metrics_never_authorize_promotion(self) -> None:
        result = self.verify()
        self.assertEqual(result["decision"], "NO_PRODUCTION_PROMOTION")
        self.assertFalse(result["all_scale_slots_observed"])
        self.assertEqual(result["comparisons_vs_frozen_no_change"]["v2"]["future"]
                         ["mean_utility_delta_micro"], 1)
        self.assertEqual(result["comparisons_vs_frozen_no_change"]["v2"]["ood"]
                         ["negative_transfer_rate"], 1)

    def test_binary_brier_and_ece_are_descriptive_only(self) -> None:
        for row in self.payload["samples"]:
            row["outcomes"]["no-change-v1"].update({
                "binary_probability_ppm": 500_000, "binary_label": True,
            })
            row["outcomes"]["v2"].update({
                "binary_probability_ppm": 750_000, "binary_label": True,
            })
        result = self.verify()
        outcome = result["comparisons_vs_frozen_no_change"]["v2"]["future"]
        self.assertEqual(outcome["candidate_calibration"]["brier_ppm"], 62_500)
        self.assertEqual(outcome["candidate_calibration"]["ece_ppm"], 250_000)
        self.assertEqual(outcome["baseline_calibration"]["brier_ppm"], 250_000)
        self.assertEqual(result["decision"], "NO_PRODUCTION_PROMOTION")

    def test_partial_probability_or_selective_calibration_blocks(self) -> None:
        self.payload["samples"][0]["outcomes"]["v2"]["binary_probability_ppm"] = 750_000
        with self.assertRaisesRegex(a0.EvidenceError, "partial binary"):
            self.verify()
        del self.payload["samples"][0]["outcomes"]["v2"]["binary_probability_ppm"]
        for name, row in self.payload["samples"][0]["outcomes"].items():
            row.update({"binary_probability_ppm": 500_000, "binary_label": True})
        # Add another case in the same split that does not have binary labels.
        future = copy.deepcopy(self.payload["samples"][0])
        future["case_id"] = "no-calibration-case"
        future["input_digest"] = sha(b"no-calibration")
        for row in future["outcomes"].values():
            del row["binary_probability_ppm"]
            del row["binary_label"]
        self.payload["samples"].append(future)
        with self.assertRaisesRegex(a0.EvidenceError, "selective or incomplete"):
            self.verify()

    def test_mismatched_binary_ground_truth_rejected(self) -> None:
        for sample in self.payload["samples"]:
            sample["outcomes"]["no-change-v1"].update({
                "binary_probability_ppm": 500_000, "binary_label": True,
            })
            sample["outcomes"]["v2"].update({
                "binary_probability_ppm": 750_000, "binary_label": False,
            })
        with self.assertRaisesRegex(a0.EvidenceError, "disagree on binary"):
            self.verify()

    def test_no_change_must_remain_frozen(self) -> None:
        self.payload["arms"]["no-change-v1"]["optimizer_steps"] = 100
        with self.assertRaisesRegex(a0.EvidenceError, "zero experimental training"):
            self.verify()

    def test_preregistered_training_dataset_required(self) -> None:
        self.payload["arms"]["v2"]["training_data_digest"] = sha(b"other training")
        with self.assertRaisesRegex(a0.EvidenceError, "preregistered dataset"):
            self.verify()

    def test_only_available_labels_can_be_evaluated(self) -> None:
        self.payload["samples"][0]["label_available_at_utc"] = "2026-10-10T00:00:00Z"
        with self.assertRaisesRegex(a0.EvidenceError, "unavailable at signed evaluation"):
            self.verify()

    def test_cluster_ci_is_not_confused_with_case_count(self) -> None:
        self.payload["samples"].append({
            **copy.deepcopy(self.payload["samples"][0]),
            "case_id": "other-future-case",
            "input_digest": sha(b"other-future-input"),
        })
        result = self.verify()
        future = result["comparisons_vs_frozen_no_change"]["v2"]["future"]
        self.assertEqual(future["paired_count"], 2)
        self.assertEqual(future["independent_cell_count"], 1)
        self.assertIsNone(future["cluster_mean_95ci_micro"])
        self.assertEqual(future["uncertainty"], "INSUFFICIENT_INDEPENDENT_CELLS")

    def test_distinct_second_cell_yields_clustered_ci(self) -> None:
        self.payload["samples"][0]["cell_id"] = "cell-b"
        result = self.verify()
        future = result["comparisons_vs_frozen_no_change"]["v2"]["future"]
        self.assertEqual(future["independent_cell_count"], 1)
        self.assertIsNone(future["cluster_mean_95ci_micro"])
        self.payload["samples"].append({
            **copy.deepcopy(self.payload["samples"][0]),
            "case_id": "third-case",
            "cell_id": "cell-c",
            "input_digest": sha(b"third-input"),
        })
        result = self.verify()
        future = result["comparisons_vs_frozen_no_change"]["v2"]["future"]
        self.assertEqual(future["independent_cell_count"], 2)
        self.assertEqual(future["cluster_mean_95ci_micro"], [1.0, 1.0])

    def test_independent_evaluator_required(self) -> None:
        self.payload["selector_key_id"] = self.fingerprint
        with self.assertRaisesRegex(a0.EvidenceError, "different owners"):
            self.verify()

    def test_training_budget_equality_required(self) -> None:
        self.payload["arms"]["v2"]["optimizer_steps"] = 101
        with self.assertRaisesRegex(
            a0.EvidenceError, "candidate optimizer steps differ from preregistered budget"
        ):
            self.verify()

    def test_frozen_shared_encoder_required(self) -> None:
        self.payload["arms"]["v2"]["encoder_digest"] = sha(b"larger encoder")
        with self.assertRaisesRegex(a0.EvidenceError, "different Encoder"):
            self.verify()

    def test_parameter_and_state_limits_fail_closed(self) -> None:
        self.payload["arms"]["v2"]["parameter_count_total"] = 129
        with self.assertRaisesRegex(a0.EvidenceError, "exceeds equal parameter budget"):
            self.verify()

    def test_future_window_leakage_fails_closed(self) -> None:
        self.payload["samples"][0]["event_time_utc"] = "2026-10-02T00:00:00Z"
        with self.assertRaisesRegex(a0.EvidenceError, "future example leaks"):
            self.verify()

    def test_missing_paired_arm_fails_closed(self) -> None:
        del self.payload["samples"][0]["outcomes"]["v2"]
        with self.assertRaisesRegex(a0.EvidenceError, "joined outcome"):
            self.verify()

    def test_no_ood_split_rejected(self) -> None:
        self.payload["samples"].pop()
        with self.assertRaisesRegex(a0.EvidenceError, "missing future or OOD"):
            self.verify()

    def test_a4_rejects_unverified_scale_measurement_type(self) -> None:
        self.payload["phase"] = "A4"
        self.payload["scale_receipts"].append({
            "arm": "v2",
            "cell_count": 64,
            "host_profile_digest": self.payload["host_profile_digest"],
            "cpu_micros": 100,
            "peak_rss_bytes": 4096,
            "p95_micros": 20,
            "p99_micros": 22,
            "throughput_tasks_per_second_milli": 1000,
            "measurement_kind": "synthetic",
            "execution_receipt_digest": sha(b"execution"),
            "recovery_receipt_digest": sha(b"recovery"),
        })
        with self.assertRaisesRegex(a0.EvidenceError, "synthetic or projected"):
            self.verify()

    def test_a4_needs_every_scale_and_no_promotion(self) -> None:
        self.payload["phase"] = "A4"
        with self.assertRaisesRegex(a0.EvidenceError, "A4 requires all"):
            self.verify()
        for arm in self.payload["arms"]:
            for n in pair.SCALE_CELLS:
                self.payload["scale_receipts"].append({
                    "arm": arm,
                    "cell_count": n,
                    "host_profile_digest": self.payload["host_profile_digest"],
                    "cpu_micros": 100 * n,
                    "peak_rss_bytes": 4096 * n,
                    "p95_micros": 20,
                    "p99_micros": 22,
                    "throughput_tasks_per_second_milli": 1000,
                    "measurement_kind": "target-host-observed",
                    "execution_receipt_digest": sha(b"execution"),
                    "recovery_receipt_digest": sha(b"recovery"),
                })
        result = self.verify()
        self.assertTrue(result["all_scale_slots_observed"])
        self.assertEqual(result["decision"], "NO_PRODUCTION_PROMOTION")

    def test_duplicate_sample_and_censored_label_fails_closed(self) -> None:
        self.payload["samples"].append(copy.deepcopy(self.payload["samples"][0]))
        with self.assertRaisesRegex(a0.EvidenceError, "duplicate Cell/case"):
            self.verify()
        self.payload["samples"].pop()
        self.payload["samples"][0]["label_available_at_utc"] = "2026-10-04T00:00:00Z"
        with self.assertRaisesRegex(a0.EvidenceError, "label before event"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
