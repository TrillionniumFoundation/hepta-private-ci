"""Exercise the shared inference.worker tensor loader, not a mock backend."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import torch

from safetensors.torch import save_file

TENSOR_PATH = Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python/decision_cell_tensors.py"
spec = importlib.util.spec_from_file_location("hepta_tensor_bundle_tests", TENSOR_PATH)
shared = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = shared
spec.loader.exec_module(shared)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def fixture_manifest(model, calibration, weights):
    actions = ["open_path", "navigate", "copy_text", "notify", "request_evidence", "stop"]
    profile = {
        "schema": "hepta.decision-cell-runtime-profile.v2",
        "composition": "shared-base/organ-adapter/cell-adapter/typed-heads",
        "projection_schema": "hepta.decision-cell-text-projection.v1",
        "actions": actions,
        "action_semantic_digests": {name: hashlib.sha256(
            b"hepta.decision-cell-action-label.v1\0" + name.encode()).hexdigest() for name in actions},
        "dispositions": ["continue", "stop", "abstain", "request_evidence", "slow_path", "success"],
        "target_count": 4, "maximum_length": 192, "head_width": 4,
        "target_pointer_profile": "candidate-pair-shared-scorer.v1",
        "pooling": "attention-mask-mean-v1", "parameter_values": "none-v1",
        "postcondition_labels": actions,
        "postcondition_semantic_digests": {name: hashlib.sha256(
            b"hepta.decision-cell-postcondition-label.v1\0" + name.encode()).hexdigest() for name in actions},
    }
    return {"schema": "hepta.decision-cell-head-artifact.v2",
            "base_model": {"snapshot_digest": "d" * 64}, "calibration": calibration,
            "runtime_profile": profile, "weights_sha256": hashlib.sha256(weights).hexdigest(),
            "weights_bytes": len(weights), "head_parameter_count": sum(p.numel() for p in model.parameters()),
            "parameter_group_sha256": shared.parameter_group_digests(model)}


class TensorBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        torch.manual_seed(23)
        self.model = shared.TypedHeads(8, 4).eval()
        self.calibration = {"temperatures": {key: 0.5 for key in ("action", "target", "disposition", "postcondition", "ood")},
                            "minimum_confidence": 0.2, "maximum_ood_probability": 0.7}
        weights_path = self.root / "head.safetensors"
        save_file(self.model.state_dict(), weights_path)
        self.manifest = fixture_manifest(self.model, self.calibration, weights_path.read_bytes())
        manifest_path = self.root / "manifest.json"
        raw = canonical(self.manifest)
        manifest_path.write_bytes(raw)
        self.artifact = {"manifest_path": str(manifest_path), "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                         "weights_path": str(weights_path), "weights_sha256": self.manifest["weights_sha256"]}

    def load(self, **overrides):
        args = {"manifest_path": Path(self.artifact["manifest_path"]),
                "manifest_sha256": self.artifact["manifest_sha256"],
                "weights_path": Path(self.artifact["weights_path"]),
                "weights_sha256": self.artifact["weights_sha256"],
                "expected_base_snapshot": "d" * 64,
                "expected_runtime_profile": self.manifest["runtime_profile"]}
        return shared.HeadTensorBundleV2(**{**args, **overrides})

    def rewrite_manifest(self):
        data = canonical(self.manifest)
        Path(self.artifact["manifest_path"]).write_bytes(data)
        self.artifact["manifest_sha256"] = hashlib.sha256(data).hexdigest()

    def test_reload_uses_identical_organ_cell_and_head_tensors(self):
        state = torch.randn(2, 8)
        targets = torch.randn(2, 4, 8)
        expected = self.model(state, targets)
        bundle = self.load()
        observed = bundle.observe(state, targets)
        for key in expected:
            self.assertTrue(torch.equal(expected[key], observed[key]), key)
        probabilities = bundle.probabilities(state, targets)
        for key in self.calibration["temperatures"]:
            self.assertTrue(torch.equal(probabilities[key], torch.softmax(expected[key] / 0.5, dim=-1)))
        expected_support = (probabilities["action"].max(dim=-1).values >= 0.2) & (probabilities["ood"][:, 1] < 0.7)
        self.assertTrue(torch.equal(probabilities["supported"], expected_support))

    def test_base_and_profile_substitution_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "base snapshot"):
            self.load(expected_base_snapshot="e" * 64)
        profile = {**self.manifest["runtime_profile"], "pooling": "unregistered"}
        with self.assertRaisesRegex(ValueError, "profile substitution"):
            self.load(expected_runtime_profile=profile)

    def test_changed_weight_bytes_do_not_load(self):
        with Path(self.artifact["weights_path"]).open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "content digest"):
            self.load()

    def test_group_substitution_rejects_even_with_rehashed_manifest(self):
        self.manifest["parameter_group_sha256"]["cell_adapter"] = "0" * 64
        self.rewrite_manifest()
        with self.assertRaisesRegex(ValueError, "parameter binding"):
            self.load()

    def test_zero_temperature_is_not_usable_calibration(self):
        self.manifest["calibration"]["temperatures"]["action"] = 0
        self.rewrite_manifest()
        with self.assertRaisesRegex(ValueError, "temperatures"):
            self.load()

    def test_invalid_feature_shape_and_nonfinite_values_reject(self):
        bundle = self.load()
        with self.assertRaisesRegex(ValueError, "shape"):
            bundle.observe(torch.zeros(2, 7), torch.zeros(2, 4, 8))
        with self.assertRaisesRegex(ValueError, "non-finite"):
            bundle.observe(torch.full((2, 8), float("nan")), torch.zeros(2, 4, 8))
        with self.assertRaisesRegex(ValueError, "shape"):
            bundle.observe(torch.zeros(33, 8), torch.zeros(33, 4, 8))

    def test_caller_mutation_of_returned_tensors_cannot_change_the_bundle(self):
        bundle = self.load()
        x, t = torch.randn(2, 8), torch.randn(2, 4, 8)
        first = bundle.observe(x, t)
        saved = first["action"].clone()
        first["action"].fill_(0)
        self.assertTrue(torch.equal(saved, bundle.observe(x, t)["action"]))

    def test_rehashed_unsupported_profile_cannot_reinterpret_the_weights(self):
        original = self.manifest["runtime_profile"]
        variants = [
            {**original, "pooling": "first-token"},
            {**original, "projection_schema": "different-projection"},
            {**original, "target_count": 4.0},
            {**original, "maximum_length": 256},
            {**original, "unknown_critical_field": True},
            {**original, "action_semantic_digests": {**original["action_semantic_digests"], "stop": "f" * 64}},
            {**original, "postcondition_semantic_digests": {**original["postcondition_semantic_digests"], "stop": "e" * 64}},
        ]
        for profile in variants:
            with self.subTest(profile=profile):
                self.manifest["runtime_profile"] = profile
                self.rewrite_manifest()
                with self.assertRaisesRegex(ValueError, "runtime profile"):
                    self.load()

    def test_nonfinite_after_float32_conversion_rejects(self):
        bundle = self.load()
        with self.assertRaisesRegex(ValueError, "non-finite"):
            bundle.observe(torch.full((2, 8), 1e100, dtype=torch.float64), torch.zeros(2, 4, 8))

    def test_complex_or_integer_features_are_not_silently_reinterpreted(self):
        bundle = self.load()
        for dtype in (torch.complex64, torch.int64, torch.bool):
            with self.subTest(dtype=dtype), self.assertRaisesRegex(ValueError, "floating-point"):
                bundle.observe(torch.ones(2, 8, dtype=dtype), torch.zeros(2, 4, 8))

    def test_valid_positive_temperature_cannot_produce_unchecked_nan(self):
        self.manifest["calibration"]["temperatures"]["action"] = 1e-300
        self.rewrite_manifest()
        bundle = self.load()
        with self.assertRaisesRegex(ValueError, "non-finite calibrated"):
            bundle.probabilities(torch.randn(2, 8), torch.randn(2, 4, 8))

    def test_duplicate_fields_and_nonfinite_json_reject(self):
        for raw in (b'{"version":2,"version":1}', b'{"temperature":NaN}'):
            with self.assertRaises(ValueError):
                shared.strict_json(raw)

    def test_symlink_and_oversize_file_reject(self):
        link = self.root / "manifest-link.json"
        link.symlink_to(self.artifact["manifest_path"])
        with self.assertRaises((ValueError, OSError)):
            self.load(manifest_path=link)
        with self.assertRaisesRegex(ValueError, "bounded regular"):
            shared.checked_bytes(Path(self.artifact["manifest_path"]), self.artifact["manifest_sha256"], 1)


if __name__ == "__main__":
    unittest.main()
