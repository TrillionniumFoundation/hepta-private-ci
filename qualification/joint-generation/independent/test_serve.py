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
               "controller_file": "critic.npz", "controller_sha256": digest((self.run / "critic.npz").read_bytes()),
               "decision_price": .02, "cost_ratio": 1.,
               "controller_calibration": self.calibration(.02)}
        static = {**row, "system": "ndu", "mode": "full", "controller_file": None, "controller_sha256": None,
                  "decision_price": None, "cost_ratio": None, "controller_calibration": None}
        self.selection = {"schema": "hepta.joint-generation.efficient-selection.v2", "selected": [row, static],
            "plan": {"runtime_backend": "native", "rho": 1.5, "compute_price": .02,
                     "inference_cap_full_equivalents": 2., "runtime_batch_size": 64},
            "native_library": "build/native.so", "native_library_sha256": digest(self.library.read_bytes()),
            "source_commit": "f" * 40, "plan_sha256": "b" * 64, "selection_ready": False,
            "common": {"calibration_identity": {"inputs_sha256": "e" * 64}}}
        (self.run / "selection.json").write_text(json.dumps(self.selection))
        self.bundle = self.root / "bundle"
        self.artifact = export_bundle(self.run, "ndu_control", 11, self.bundle)

    def calibration(self, decision_price):
        ratio = decision_price / .02
        return {"schema": "hepta.joint-generation.controller-cost-calibration.v1", "seed": 11,
            "gain_objective": "raw-decoded-task-utility", "model_digest": self.model.digest(),
            "calibration_inputs_sha256": "e" * 64, "reference_full_cpu_ns": 1000.,
            "paired_cpu_deltas_ns_per_request": [ratio * 1000.] * 3,
            "median_incremental_cpu_ns_per_request": ratio * 1000.,
            "nonnegative_incremental_cpu_ns_per_request": ratio * 1000.,
            "compute_price": .02, "cost_ratio": ratio, "decision_price": decision_price}

    def affine_bundle(self, decision_price=.02):
        from independent.accounting import WorkLedger
        from independent.gain_head import AffineGainHead, KIND
        full = np.zeros((4, 202)); full[:, 192] = full[:, 196] = full[:, 199] = 1
        _, hidden, _, _ = self.model._forward(full)
        config = {"gain_head": KIND, "ridge_regularization": .001}
        head, fitted = AffineGainHead.fit(hidden, full[:, 192:], np.full(4, .1), config,
                                         11, WorkLedger("manual-serving-fit"))
        np.savez_compressed(self.run / "affine.npz", **head.to_arrays())
        receipt = self.calibration(decision_price)
        receipt.update(critic_kind=KIND, gain_head_fit=fitted,
                       raw_target={"rows": 4, "values_sha256": fitted["target"]["sha256"]})
        row = self.selection["selected"][0]
        row.update(controller_file="affine.npz", controller_sha256=digest((self.run / "affine.npz").read_bytes()),
                   decision_price=decision_price, cost_ratio=decision_price/.02,
                   controller_calibration=receipt, critic_kind=KIND, gain_head_kind=KIND)
        self.selection["plan"]["controller"] = config
        self.selection["datasets"] = {"train": {"rows": 4}}
        (self.run / "selection.json").write_text(json.dumps(self.selection))
        target = self.root / ("affine-" + str(decision_price))
        artifact = export_bundle(self.run, "ndu_control", 11, target)
        return head, target, artifact

    def test_affine_v2_native_replay_binds_kind_and_actual_controller_cost(self):
        from independent.inference import units
        for price, continued in ((.02, True), (.2, False)):
            head, target, artifact = self.affine_bundle(price)
            bundle = load_bundle(target)
            self.assertEqual(bundle.controller.kind, head.kind)
            self.assertEqual(bundle.manifest["provenance"]["controller_calibration"]["critic_kind"], head.kind)
            request = self.request(); request["artifact_sha256"] = artifact
            with patch("independent.evaluation.dataset", side_effect=AssertionError("no data")), \
                    patch.object(Controller, "predict_gain", side_effect=AssertionError("legacy features")):
                first = infer(target, request, self.root / ("affine-out-" + str(price)))
                second = infer(target, request, self.root / ("affine-replay-" + str(price)))
            self.assertEqual(first["choices"], second["choices"])
            self.assertEqual(first["image_sha256"], second["image_sha256"])
            self.assertEqual(first["route"]["continued"], [continued])
            self.assertEqual(first["spent"]["controller"], units(head.work(1)))
            self.assertEqual(first["frozen_runtime"]["compute_price"], .02)
            self.assertEqual(first["spent"]["controller"] + first["spent"]["generator"],
                             first["preparation"]["consumed_units"] + first["runtime_cost"]["consumed_units"])

    def test_affine_receipt_kind_and_fit_parameters_reject_before_native_loading(self):
        _, target, _ = self.affine_bundle()
        original = load_bundle(target).manifest
        for field in ("kind", "weights", "normalizer", "hidden"):
            changed = self.root / ("affine-tamper-" + field); shutil.copytree(target, changed)
            manifest = copy.deepcopy(original)
            receipt = manifest["provenance"]["controller_calibration"]
            if field == "kind": receipt["critic_kind"] = "probability-ridge-v1"
            elif field == "hidden": receipt["gain_head_fit"]["hidden_dim"] = 5
            else: receipt["gain_head_fit"][field + "_sha256"] = "c" * 64
            manifest["provenance"]["controller_calibration_sha256"] = digest(
                json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
            (changed / "manifest.json").write_text(json.dumps(manifest))
            with self.subTest(field=field), patch("independent.serve.NativeGenerator", side_effect=AssertionError("C loaded")):
                with self.assertRaises(ContractError):
                    load_bundle(changed)

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
        self.assertTrue(first["controller_cost_calibrated"])
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
        self.assertIsNone(output["frozen_runtime"]["decision_price"])
        self.assertIsNone(load_bundle(target).manifest["provenance"]["controller_calibration"])

    def test_decision_price_changes_native_law_without_changing_global_price(self):
        results, identities = [], []
        for price in (0., .2):
            row = self.selection["selected"][0]
            row.update(decision_price=price, cost_ratio=price / .02,
                       controller_calibration=self.calibration(price))
            (self.run / "selection.json").write_text(json.dumps(self.selection))
            target = self.root / ("price-" + str(price))
            artifact = export_bundle(self.run, "ndu_control", 11, target)
            manifest = load_bundle(target).manifest
            self.assertEqual(manifest["provenance"]["controller_calibration"], row["controller_calibration"])
            request = self.request(); request["artifact_sha256"] = artifact
            results.append(infer(target, request, self.root / ("result-" + str(price))))
            identities.append(artifact)
        self.assertTrue(results[0]["route"]["continued"][0])
        self.assertFalse(results[1]["route"]["continued"][0])
        self.assertEqual([row["frozen_runtime"]["compute_price"] for row in results], [.02, .02])
        self.assertEqual([row["model_digest"] for row in results], [self.model.digest()] * 2)
        self.assertNotEqual(*identities)

    def test_calibration_hash_formula_model_and_training_binding_reject_tampering(self):
        original = load_bundle(self.bundle).manifest
        for index, field in enumerate(("decision_price", "cost_ratio", "model_digest", "training_hash", "target", "median", "receipt_hash")):
            target = self.root / ("tampered-" + str(index)); shutil.copytree(self.bundle, target)
            manifest = copy.deepcopy(original); receipt = manifest["provenance"]["controller_calibration"]
            if field in ("decision_price", "cost_ratio"): manifest["runtime"][field] += 1.
            elif field == "model_digest": receipt["model_digest"] = "c" * 64
            elif field == "training_hash": manifest["provenance"]["calibration_inputs_sha256"] = "d" * 64
            elif field == "target": receipt["gain_objective"] = "entropic-certainty-equivalent"
            elif field == "median": receipt["median_incremental_cpu_ns_per_request"] += 1.
            else: receipt["cost_ratio"] += 1.
            if field != "receipt_hash":
                manifest["provenance"]["controller_calibration_sha256"] = digest(
                    json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
            (target / "manifest.json").write_text(json.dumps(manifest))
            with self.subTest(field=field), self.assertRaises(ContractError): load_bundle(target)

    def test_legacy_bundle_reloads_without_claiming_the_calibrated_law(self):
        target = self.root / "legacy"; shutil.copytree(self.bundle, target)
        manifest = json.loads((target / "manifest.json").read_text())
        manifest["schema"] = "hepta.joint-generation.native-bundle.v1"
        for key in ("decision_price", "cost_ratio"): manifest["runtime"].pop(key)
        for key in ("controller_calibration", "controller_calibration_sha256", "calibration_inputs_sha256"):
            manifest["provenance"].pop(key)
        (target / "manifest.json").write_text(json.dumps(manifest))
        request = self.request(); request["artifact_sha256"] = load_bundle(target).digest
        result = infer(target, request, self.root / "legacy-out")
        self.assertFalse(result["controller_cost_calibrated"])
        self.assertTrue(result["route"]["continued"][0])

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
