"""Native artifact smoke tests with handmade inputs and untrained weights."""

import base64
import copy
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from contracts import ContractError, RunSession, digest
from control import Controller
from model import JointModel
from multimodal_contract import SCHEMA, UnsupportedCapability
from independent.native import compile_native
from independent.serve import export_bundle, infer, load_bundle


class NativeServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.build.cleanup)
        cls.library = Path(cls.build.name) / "kernel.so"
        cls.compilation = compile_native(cls.library)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"; (self.run / "build").mkdir(parents=True)
        shutil.copyfile(self.library, self.run / "build/native.so")
        self.model = JointModel(202, 12, 192, hidden=4, seed=19)
        self.model.save(self.run / "model.npz")
        critic = Controller(12, np.zeros(31), np.ones(31), np.zeros(31), .2, np.array([.2, .2]))
        np.savez_compressed(self.run / "critic.npz", **critic.to_arrays())
        row = {"system": "ndu_control", "seed": 11, "mode": "continuation", "model_file": "model.npz",
               "model_sha256": digest((self.run / "model.npz").read_bytes()), "model_digest": self.model.digest(),
               "controller_file": "critic.npz", "controller_sha256": digest((self.run / "critic.npz").read_bytes())}
        static = {**row, "system": "ndu", "mode": "full", "controller_file": None, "controller_sha256": None}
        self.selection = {"schema": "hepta.joint-generation.efficient-selection.v2", "selected": [row, static],
            "plan": {"runtime_backend": "native", "rho": 1.5, "compute_price": .02,
                     "inference_cap_full_equivalents": 2., "runtime_batch_size": 64},
            "native_library": "build/native.so", "native_library_sha256": digest(self.library.read_bytes()),
            "source_commit": "f" * 40, "plan_sha256": "b" * 64, "selection_ready": False}
        (self.run / "selection.json").write_text(json.dumps(self.selection))
        self.bundle = self.root / "bundle"
        self.artifact = export_bundle(self.run, "ndu_control", 11, self.bundle)

    def request(self):
        image = np.zeros((8, 8, 3)); image[2:6, 1:4, 0] = 1
        timing = {"clock_id": "manual:1", "sync_group": "manual:1", "start_ns": 1, "end_ns": 2}
        return {"schema": SCHEMA, "objective_id": "scene-transform-v1", "run_id": "native-smoke:1",
            "artifact_sha256": self.artifact, "deadline_ns": time.monotonic_ns() + 60 * 10**9,
            "budget": {"compute_units": 100000, "input_bytes": 8192, "output_bytes": 4096},
            "decoding": {"mode": "sample", "seed": 42}, "outputs": ["text", "image"], "sync_tolerance_ns": 0,
            "streams": [{"stream_id": "text:1", "modality": "text", "timing": timing,
                         "payload": {"encoding": "utf-8", "text": "blue cross right"}},
                        {"stream_id": "image:1", "modality": "image", "timing": timing,
                         "payload": {"dtype": "float32", "color_space": "RGB", "pixels": image.tolist()}}]}

    def test_standalone_reload_replays_native_outputs_without_any_observer(self):
        shutil.rmtree(self.run)
        first_bundle, second_bundle = load_bundle(self.bundle), load_bundle(self.bundle)
        self.assertEqual(first_bundle.digest, second_bundle.digest)
        self.assertEqual(first_bundle.model.digest(), self.model.digest())
        request = self.request()
        with patch("independent.evaluation.dataset", side_effect=AssertionError("dataset called")), \
             patch("independent.evaluation.outcome_table", side_effect=AssertionError("observer called")), \
             patch("independent.evaluation.decoded_metrics", side_effect=AssertionError("labels called")):
            first = infer(self.bundle, request, self.root / "first")
            second = infer(self.bundle, request, self.root / "second")
        self.assertEqual(first["choices"], second["choices"])
        self.assertEqual(first["image_sha256"], second["image_sha256"])
        self.assertTrue(first["route"]["continued"][0])
        self.assertFalse(first["selection_ready"])
        self.assertTrue(first["qualification_only"])
        self.assertEqual((self.root / "first/output.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        checkpoint = json.loads((self.root / "first/checkpoint.json").read_text())
        restored = RunSession.restore(checkpoint, expected_artifact_sha256=self.artifact, now_ns=time.monotonic_ns())
        self.assertEqual(restored.prefix("text").decode(), first["caption"])
        self.assertEqual(digest(restored.prefix("image")), first["image_sha256"])
        charged = first["spent"]["controller"] + first["spent"]["generator"]
        self.assertEqual(charged, first["preparation"]["consumed_units"] + first["runtime_cost"]["consumed_units"])
        self.assertLessEqual(charged, request["budget"]["compute_units"])

    def test_static_selected_system_executes_no_unused_critic(self):
        target = self.root / "static"
        artifact = export_bundle(self.run, "ndu", 11, target)
        request = self.request(); request["artifact_sha256"] = artifact
        with patch("independent.serve._controller", side_effect=AssertionError("unused critic loaded")):
            output = infer(target, request, self.root / "static-out")
        self.assertEqual(output["spent"]["controller"], 0)
        self.assertEqual(output["route"]["model_forwards"], 1)
        self.assertEqual(output["preparation"]["consumed_units"], 0)

    def test_modified_model_critic_and_native_hashes_reject_before_c_loading(self):
        for name in ("model.npz", "controller.npz", "native.so"):
            target = self.root / name.replace(".", "-"); shutil.copytree(self.bundle, target)
            with (target / name).open("ab") as stream:
                stream.write(b"changed")
            with self.subTest(name=name), patch("independent.serve.NativeGenerator", side_effect=AssertionError("C loaded")):
                with self.assertRaises(ValueError):
                    infer(target, self.request(), self.root / (name + "-output"))

    def test_input_backend_binding_and_compute_reject_before_execution(self):
        cases = []
        request = self.request(); request["budget"]["compute_units"] = 1; cases.append(request)
        request = self.request(); request["artifact_sha256"] = "c" * 64; cases.append(request)
        request = self.request(); request["decoding"]["mode"] = "greedy"; cases.append(request)
        request = self.request(); request["labels"] = [11]; cases.append(request)
        request = self.request()
        request["streams"] = [{"stream_id": "audio:1", "modality": "audio",
            "timing": {"clock_id": "capture:1", "sync_group": "clip:1", "start_ns": 1, "end_ns": 1000001},
            "payload": {"dtype": "float32", "channels": 1, "sample_rate_hz": 16000, "samples": [[0.]] * 16}}]
        cases.append(request)
        for index, request in enumerate(cases):
            with self.subTest(case=index), patch("independent.serve.NativeGenerator", side_effect=AssertionError("unadmitted native call")):
                with self.assertRaises((ContractError, UnsupportedCapability)):
                    infer(self.bundle, request, self.root / ("invalid-" + str(index)))

    def test_output_budget_and_existing_directory_are_preserved(self):
        request = self.request(); request["budget"]["output_bytes"] = 1
        with self.assertRaises(ContractError):
            infer(self.bundle, request, self.root / "no-output")
        self.assertFalse((self.root / "no-output").exists())
        target = self.root / "existing"; target.mkdir(); (target / "keep").write_text("retain")
        with self.assertRaises(FileExistsError): infer(self.bundle, self.request(), target)
        self.assertEqual((target / "keep").read_text(), "retain")


if __name__ == "__main__":
    unittest.main()
