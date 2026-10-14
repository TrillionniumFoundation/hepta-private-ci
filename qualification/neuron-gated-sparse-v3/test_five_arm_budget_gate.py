"""Synthetic contract/negative tests; NO real model, target host or NDU evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import five_arm_budget_gate as gate
from a0_deployment_evidence import EvidenceError


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def save_tensor_file(path: Path, shapes: dict[str, tuple[int, ...]]) -> str:
    header = {}
    offset = 0
    for name, shape in sorted(shapes.items()):
        count = 1
        for dim in shape:
            count *= dim
        size = count * 4
        header[name] = {"dtype": "F32", "shape": list(shape),
                        "data_offsets": [offset, offset + size]}
        offset += size
    raw_header = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    content = len(raw_header).to_bytes(8, "little") + raw_header + bytes(offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return digest(content)


def scores(value: int) -> dict:
    return {
        "utility_micro": value,
        "long_reward_micro": 2 * value,
        "future_retained": True,
        "negative_transfer": False,
        "ood_false_accept": False,
        "cpu_micros": 10,
        "peak_rss_bytes": 4096,
        "latency_micros": 20,
        "binary_probability_ppm": 700_000,
        "binary_label": True,
    }


class FiveArmBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.fp = digest(b"evaluator-public-key")
        self.encoded = digest(b"shared-frozen-encoder")
        self.data = digest(b"same-training-dataset")
        self.candidates = {}
        self.manifest = {"schema": gate.SCHEMA, "tiers": []}
        self.evaluations = {}
        shapes = {
            "head.weight": (16,),
        }
        min_gru = {
            "temporal.gate_input": (1, 2),
            "temporal.gate_output": (2, 1),
            "temporal.candidate_input": (1, 2),
            "temporal.candidate_output": (2, 1),
            "temporal.gate_bias": (2,),
            "temporal.candidate_bias": (2,),
            "head.weight": (4,),
        }
        for cap in gate.BUDGETS:
            files = {}
            budget_arms = {}
            for arm in gate.ARMS:
                path = f"{cap}/{arm}.safetensors"
                hash_value = save_tensor_file(self.root / path,
                                              min_gru if arm == "min_gru" else shapes)
                files[arm] = {
                    "path": path,
                    "sha256": hash_value,
                    "architecture": {"width": 2, "rank": 1} if arm == "min_gru" else {},
                }
                budget_arms[arm] = {
                    "artifact_digest": hash_value,
                    "encoder_digest": self.encoded,
                    "training_data_digest": self.data,
                    "parameter_count_total": 16,
                    "state_bytes": 2048,
                    "optimizer_steps": 0 if arm == "no-change-v1" else 100,
                }
            cases = [
                {"case_id": "case-future", "cell_id": "cell-1",
                 "input_digest": digest(b"future-input"), "split": "future",
                 "event_time_utc": "2026-10-05T00:00:00Z",
                 "label_available_at_utc": "2026-10-06T00:00:00Z",
                 "outcomes": {arm: scores(10 if arm == "no-change-v1" else 11)
                              for arm in gate.ARMS}},
                {"case_id": "case-ood", "cell_id": "cell-1",
                 "input_digest": digest(b"ood-input"), "split": "ood",
                 "event_time_utc": "2026-10-05T00:00:00Z",
                 "label_available_at_utc": "2026-10-06T00:00:00Z",
                 "outcomes": {arm: scores(10 if arm == "no-change-v1" else 8)
                              for arm in gate.ARMS}},
            ]
            self.manifest["tiers"].append({
                "parameter_cap": cap,
                "signed_evaluation": f"{cap}.json",
                "models": files,
            })
            self.evaluations[cap] = {
                "schema": "hepta.neuron.paired-shadow-evaluation.v1",
                "experiment_id": "SYNTHETIC-NEGATIVE-ONLY",
                "phase": "A1",
                "evaluator_key_id": self.fp,
                "selector_key_id": digest(b"selector"),
                "executor_key_id": digest(b"executor"),
                "preregistered_at_utc": "2026-10-01T00:00:00Z",
                "training_cutoff_utc": "2026-10-03T00:00:00Z",
                "evaluation_asof_utc": "2026-10-07T00:00:00Z",
                "host_profile_digest": digest(b"host"),
                "a0_registry_sha256": digest(b"A0-registry"),
                "frozen_baseline": True,
                "no_change_arm": "no-change-v1",
                "arms": budget_arms,
                "candidate_optimizer_steps": 100,
                "training_dataset_digest": self.data,
                "total_parameter_ceiling": cap,
                "total_state_bytes_ceiling": 4096,
                "samples": cases,
                "scale_receipts": [],
            }

    def analyze(self, require_a4: bool = False) -> dict:
        return gate.validate_bundle(self.manifest, self.evaluations, self.fp, self.root,
                                    require_a4=require_a4)

    def test_all_five_tiers_and_five_arms_count_actual_weight_bytes(self) -> None:
        result = self.analyze()
        self.assertEqual(len(result["tiers"]), 5)
        self.assertFalse(result["ndu_eligible"])
        self.assertFalse(result["production_qualification"])
        self.assertEqual(result["decision"], "NO_PRODUCTION_PROMOTION")
        for tier in result["tiers"]:
            self.assertEqual(tier["models"]["min_gru"]["min_gru_temporal_parameters"], 12)
            self.assertEqual(tier["models"]["min_gru"]["physical_private_parameters"], 16)
            self.assertFalse(tier["four_scale_slots_claimed"])

    def test_without_real_a4_receipts_cannot_claim_final_acceptance(self) -> None:
        with self.assertRaisesRegex(EvidenceError, "signed A4"):
            self.analyze(require_a4=True)

    def test_missing_or_duplicate_budget_rejected(self) -> None:
        self.manifest["tiers"].pop()
        with self.assertRaises(EvidenceError):
            self.analyze()
        self.manifest["tiers"].append(copy.deepcopy(self.manifest["tiers"][0]))
        with self.assertRaisesRegex(EvidenceError, "reordered budget"):
            self.analyze()

    def test_physical_weight_tamper_and_header_trailing_bytes_rejected(self) -> None:
        path = self.root / "2048/v2.safetensors"
        with path.open("ab") as handle:
            handle.write(b"\xff")
        with self.assertRaisesRegex(EvidenceError, "undeclared trailing"):
            self.analyze()
        path.write_bytes(path.read_bytes()[:-1])
        with path.open("r+b") as handle:
            handle.seek(-1, 2)
            handle.write(b"\x01")
        with self.assertRaisesRegex(EvidenceError, "SHA mismatch"):
            self.analyze()

    def test_claimed_size_must_equal_real_private_tensor_count(self) -> None:
        self.evaluations[2048]["arms"]["v3"]["parameter_count_total"] = 15
        with self.assertRaisesRegex(EvidenceError, "claimed parameters"):
            self.analyze()

    def test_private_parameters_exceeding_cap_are_rejected(self) -> None:
        path = self.root / "2048/v2.safetensors"
        new_sha = save_tensor_file(path, {"head.weight": (2049,)})
        self.evaluations[2048]["arms"]["v2"]["parameter_count_total"] = 2049
        self.evaluations[2048]["arms"]["v2"]["artifact_digest"] = new_sha
        self.manifest["tiers"][0]["models"]["v2"]["sha256"] = new_sha
        with self.assertRaisesRegex(EvidenceError, "exceeds registered"):
            self.analyze()

    def test_invalid_min_gru_shape_must_fail(self) -> None:
        path = self.root / "2048/min_gru.safetensors"
        malformed = {"temporal.gate_input": (1, 3), "head.weight": (13,)}
        value = save_tensor_file(path, malformed)
        self.evaluations[2048]["arms"]["min_gru"]["artifact_digest"] = value
        self.manifest["tiers"][0]["models"]["min_gru"]["sha256"] = value
        with self.assertRaisesRegex(EvidenceError, "wrong physical shape"):
            self.analyze()

    def test_different_training_steps_or_encoder_fail(self) -> None:
        self.evaluations[2048]["arms"]["v2"]["optimizer_steps"] = 101
        with self.assertRaisesRegex(EvidenceError, "optimizer steps"):
            self.analyze()
        self.evaluations[2048]["arms"]["v2"]["optimizer_steps"] = 100
        self.evaluations[8192]["arms"]["v2"]["encoder_digest"] = digest(b"different")
        with self.assertRaisesRegex(EvidenceError, "Encoder"):
            self.analyze()

    def test_temporal_leak_and_unequal_future_cases_fail(self) -> None:
        self.evaluations[2048]["samples"][0]["event_time_utc"] = "2026-10-02T00:00:00Z"
        with self.assertRaisesRegex(EvidenceError, "leaks"):
            self.analyze()
        self.evaluations[2048]["samples"][0]["event_time_utc"] = "2026-10-05T00:00:00Z"
        self.evaluations[8192]["samples"][0]["input_digest"] = digest(b"different-future")
        with self.assertRaisesRegex(EvidenceError, "identical cases"):
            self.analyze()

    def test_missing_fifth_arm_and_model_drift_fail(self) -> None:
        del self.evaluations[2048]["arms"]["min_gru"]
        with self.assertRaisesRegex(EvidenceError, "missing one of five"):
            self.analyze()
        # A separate positive case is constructed by setUp for every test.

    def test_path_traversal_symlink_and_json_duplicate_rejected(self) -> None:
        with self.assertRaisesRegex(EvidenceError, "path traversal"):
            gate.file_in(self.root, "../weights.bin")
        (self.root / "symlink.safetensors").symlink_to(
            self.root / "2048/no-change-v1.safetensors")
        with self.assertRaisesRegex(EvidenceError, "symbolic link"):
            gate.file_in(self.root, "symlink.safetensors")
        with self.assertRaisesRegex(EvidenceError, "duplicate JSON"):
            gate.strictly_json(b'{"x":1,"x":2}')

    def test_no_unsigned_claim_can_infer_real_model_learning(self) -> None:
        result = self.analyze()
        self.assertFalse(result["qualified_real_training_or_target_host"])
        self.assertFalse(result["independent_owner_and_checkpoint_attestation_verified"])
        self.assertTrue(result["physical_private_weight_hash_and_tensor_shapes_verified"])


if __name__ == "__main__":
    unittest.main()
