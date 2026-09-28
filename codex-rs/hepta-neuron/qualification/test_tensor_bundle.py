"""Exercise the shared inference.worker tensor loader, not a mock backend."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import torch

spec = importlib.util.spec_from_file_location("bakeoff_tensor_tests", Path(__file__).with_name("decision_cell_bakeoff.py"))
bakeoff = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bakeoff
spec.loader.exec_module(bakeoff)
shared = bakeoff._tensor_module


class TensorBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        torch.manual_seed(23)
        self.model = bakeoff.TypedHeads(8, 4).eval()
        self.calibration = {"temperatures": {key: 0.5 for key in ("action", "target", "disposition", "postcondition", "ood")},
                            "minimum_confidence": 0.2, "maximum_ood_probability": 0.7}
        _, self.artifact = bakeoff.save_head_artifact(self.root, "unit-fixture", self.model,
            {"base_model": {"snapshot_digest": "d" * 64}, "calibration": self.calibration})
        self.manifest = json.loads(Path(self.artifact["manifest_path"]).read_text())

    def load(self, **overrides):
        args = {"manifest_path": Path(self.artifact["manifest_path"]),
                "manifest_sha256": self.artifact["manifest_sha256"],
                "weights_path": Path(self.artifact["weights_path"]),
                "weights_sha256": self.artifact["weights_sha256"],
                "expected_base_snapshot": "d" * 64,
                "expected_runtime_profile": self.manifest["runtime_profile"]}
        return shared.HeadTensorBundleV2(**{**args, **overrides})

    def rewrite_manifest(self):
        data = bakeoff.canonical_json(self.manifest)
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
