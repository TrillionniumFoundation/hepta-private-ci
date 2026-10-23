import json
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from contracts import ContractError, RunSession, digest
from control import Controller
from model import JointModel
from serve import encode_request, infer, load_bundle


class ServeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name) / "bundle"
        self.bundle.mkdir()
        model = JointModel(202, 12, 192, hidden=4)
        model.save(self.bundle / "model.npz")
        controller = Controller(12, np.zeros(31), np.ones(31), np.zeros(31), 0.2, np.array([0.2, 0.2]))
        np.savez_compressed(self.bundle / "controller.npz", **controller.to_arrays())
        self.manifest = {"schema": "hepta.joint-generation.bundle.v1", "model_digest": model.digest(),
                         "input_profile": "rgb8-instruction10-v1",
                         "utility_profile": {"rho": 1.5, "compute_price": 0.02,
                                             "behavior_policy": "independent-categorical-v1"}}
        for name in ("model", "controller"):
            self.manifest[name + "_sha256"] = digest((self.bundle / (name + ".npz")).read_bytes())
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest))
        self.request = {"objective_id": "objective:1", "run_id": "run:1", "image": np.zeros((8, 8, 3)).tolist(),
                        "instruction": {"color": "red", "shape": "cross", "position": "left"},
                        "decoding": {"mode": "sample", "seed": 73},
                        "budget": {"compute_units": 5000, "output_bytes": 4096}, "deadline_ns": time.monotonic_ns() + 10**10}

    def test_frozen_external_input_generates_real_png_and_checkpoint(self):
        out = Path(self.tmp.name) / "out"
        result = infer(self.bundle, self.request, out)
        self.assertTrue(result["continued"])
        self.assertEqual((out / "output.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        restored = RunSession.restore(json.loads((out / "checkpoint.json").read_text()),
                                      expected_artifact_sha256=result["bundle_digest"], now_ns=time.monotonic_ns())
        self.assertEqual(restored.prefix("text").decode(), result["caption"])
        self.assertEqual(digest(restored.prefix("image")), result["image_sha256"])
        self.assertEqual(load_bundle(self.bundle)[0].digest(), result["model_digest"])
        self.assertEqual(result["utility_profile"], self.manifest["utility_profile"])
        self.assertEqual(result["decoding"], self.request["decoding"])
        with self.assertRaises(ContractError):
            RunSession.restore(json.loads((out / "checkpoint.json").read_text()),
                               expected_artifact_sha256=result["model_digest"], now_ns=time.monotonic_ns())

    def test_price_changes_action_and_bundle_binding_without_model_change(self):
        before = infer(self.bundle, self.request, Path(self.tmp.name) / "before")
        self.manifest["utility_profile"]["compute_price"] = 0.3
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest))
        after = infer(self.bundle, self.request, Path(self.tmp.name) / "after")
        self.assertTrue(before["continued"])
        self.assertFalse(after["continued"])
        self.assertEqual(before["model_digest"], after["model_digest"])
        self.assertNotEqual(before["bundle_digest"], after["bundle_digest"])

    def test_sample_seed_replays_content_and_greedy_is_explicit(self):
        first = infer(self.bundle, self.request, Path(self.tmp.name) / "first")
        second = infer(self.bundle, self.request, Path(self.tmp.name) / "second")
        self.assertEqual(first["choices"], second["choices"])
        self.assertEqual(first["image_sha256"], second["image_sha256"])
        self.request["decoding"]["mode"] = "greedy"
        greedy = infer(self.bundle, self.request, Path(self.tmp.name) / "greedy")
        self.assertEqual(greedy["decoding"]["mode"], "greedy")

    def test_budget_disables_second_pass_and_insufficient_budget_rejects(self):
        self.request["budget"]["compute_units"] = 3000
        self.assertFalse(infer(self.bundle, self.request, Path(self.tmp.name) / "one")["continued"])
        self.request["budget"]["compute_units"] = 10
        with self.assertRaises(ContractError):
            infer(self.bundle, self.request, Path(self.tmp.name) / "none")

    def test_nonfinite_and_out_of_range_utility_profiles_reject(self):
        for value in (float("nan"), float("inf"), -1, 10**100, True):
            self.manifest["utility_profile"]["compute_price"] = value
            (self.bundle / "manifest.json").write_text(json.dumps(self.manifest))
            with self.assertRaises(ContractError):
                load_bundle(self.bundle)

    def test_labels_unknown_words_and_corrupt_artifacts_reject(self):
        for field, value in (("labels", [1]), ("image", np.full((8, 8, 3), float("nan")).tolist())):
            request = dict(self.request, **{field: value})
            with self.assertRaises(ContractError):
                encode_request(request)
        self.request["instruction"]["shape"] = "triangle"
        with self.assertRaises(ContractError):
            encode_request(self.request)
        with (self.bundle / "model.npz").open("ab") as stream:
            stream.write(b"corrupt")
        with self.assertRaises(ContractError):
            load_bundle(self.bundle)


if __name__ == "__main__":
    unittest.main()
