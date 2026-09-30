"""Real subprocess reply corruption and shared-rule regressions, not model trust."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

import torch
import test_frozen_process as process_fixture
from decision_cell_process import FrozenEncoderProcess, WorkerTransportError, canonical
from decision_cell_tensors import HeadSupportRuleV2, bound_support_rule

SHAPES = {"action": 6, "target": 4, "disposition": 6, "postcondition": 6, "ood": 2, "value_cost": 2}


class CalibrationBindingTests(unittest.TestCase):
    setUp = process_fixture.FrozenProcessTests.setUp
    tearDown = process_fixture.FrozenProcessTests.tearDown
    request = process_fixture.FrozenProcessTests.request
    assert_reaped = process_fixture.FrozenProcessTests.assert_reaped

    def snapshot_manifest(self):
        raw = canonical(self.manifest)
        self.manifest_path.write_bytes(raw)
        self.ready["head_manifest_sha256"] = hashlib.sha256(raw).hexdigest()

    def observation(self):
        scores = {name: torch.arange(width, dtype=torch.float32).reshape(1, -1)
                  for name, width in SHAPES.items()}
        rule = bound_support_rule(self.manifest_path, self.ready)
        return {"schema": "hepta.frozen-encoder-observation.v2",
                "input_sha256": self.request()["projection_sha256"],
                "base_snapshot_digest": self.ready["base_snapshot_digest"],
                "head_manifest_sha256": self.ready["head_manifest_sha256"],
                "scores": {name: value.tolist() for name, value in scores.items()},
                "probabilities": {name: value.tolist() for name, value in rule.apply(scores).items()},
                "base_forward_passes": 2, "latency_ns": 1,
                "advisory_only": True, "external_effect": False}

    def launch(self, observation):
        code = process_fixture.HELPER.replace('    if mode=="authority":',
            '    x["status"]="observed";x["observation"]=json.loads(sys.argv[3])\n    if mode=="authority":')
        child = FrozenEncoderProcess([sys.executable, "-u", "-c", code,
            json.dumps(self.ready), "observed", json.dumps(observation)], self.ready,
            environment={"PATH": os.defpath}, manifest_path=self.manifest_path, startup_seconds=3)
        self.children.append(child)
        return child

    def test_shared_rule_matches_real_float32_softmax(self):
        for seed in range(20):
            torch.manual_seed(seed)
            temperatures = {name: 0.5 + seed / 17 for name in SHAPES if name != "value_cost"}
            calibration = {"temperatures": temperatures, "minimum_confidence": 0.25,
                           "maximum_ood_probability": 0.7}
            rule = HeadSupportRuleV2.from_calibration(calibration)
            logits = {name: torch.randn(4, width) for name, width in SHAPES.items()}
            observed = rule.apply(logits)
            expected = {name: torch.softmax(logits[name] / temp, dim=-1)
                        for name, temp in temperatures.items()}
            expected["supported"] = (expected["action"].max(-1).values >= 0.25) & (expected["ood"][:, 1] < 0.7)
            for name in expected:
                self.assertTrue(torch.equal(observed[name], expected[name]))

    def test_actual_pipe_accepts_consistent_observation(self):
        value = self.observation(); child = self.launch(value)
        self.assertEqual(child.exchange(self.request(), "a" * 64)["observation"], value)
        self.assertEqual(child.exchange(self.request(), "a" * 64, kind="lookup")["observation"], value)
        self.assertFalse(child._closed)

    def test_rehashed_normalized_probabilities_cannot_replace_logits(self):
        for name in SHAPES:
            if name == "value_cost": continue
            with self.subTest(head=name):
                value = self.observation()
                value["probabilities"][name][0].reverse()
                child = self.launch(value)
                with self.assertRaisesRegex(WorkerTransportError, "contradict bound calibration"):
                    child.exchange(self.request(), "a" * 64)
                self.assert_reaped(child)

    def test_support_flip_rejects_even_when_every_probability_is_correct(self):
        value = self.observation()
        value["probabilities"]["supported"][0] = not value["probabilities"]["supported"][0]
        child = self.launch(value)
        with self.assertRaisesRegex(WorkerTransportError, "contradict bound calibration"):
            child.exchange(self.request(), "a" * 64)
        self.assert_reaped(child)

    def test_reject_all_cannot_be_overridden_by_saturated_confidence(self):
        self.calibration.update(minimum_confidence=1.0, maximum_ood_probability=0.0)
        self.snapshot_manifest()
        value = self.observation()
        value["scores"]["action"] = [[1000.0, 0., 0., 0., 0., 0.]]
        value["scores"]["ood"] = [[1000.0, 0.0]]
        logits = {name: torch.tensor(rows, dtype=torch.float32) for name, rows in value["scores"].items()}
        value["probabilities"] = {name: tensor.tolist() for name, tensor in
            bound_support_rule(self.manifest_path, self.ready).apply(logits).items()}
        self.assertEqual(value["probabilities"]["supported"], [False])
        self.assertEqual(value["probabilities"]["action"][0][0], 1.0)
        value["probabilities"]["supported"] = [True]
        child = self.launch(value)
        with self.assertRaisesRegex(WorkerTransportError, "contradict bound calibration"):
            child.exchange(self.request(), "a" * 64)
        self.assert_reaped(child)

    def test_manifest_change_after_launch_cannot_change_captured_rule(self):
        value = self.observation(); child = self.launch(value)
        self.calibration.update(minimum_confidence=0.0, maximum_ood_probability=1.0)
        self.snapshot_manifest()
        self.assertEqual(child.exchange(self.request(), "a" * 64)["observation"], value)
        with self.assertRaises(AttributeError): child._support_rule.maximum_ood = 1.0

    def test_invalid_manifest_rejects_before_creating_child_or_snapshot(self):
        self.manifest_path.write_bytes(b"changed")
        with mock.patch("decision_cell_process.subprocess.Popen") as spawn, mock.patch(
                "decision_cell_process.tempfile.TemporaryDirectory") as directory:
            with self.assertRaises(ValueError):
                FrozenEncoderProcess([sys.executable], self.ready, environment={}, manifest_path=self.manifest_path)
            spawn.assert_not_called(); directory.assert_not_called()

    def test_correctly_hashed_wrong_base_or_profile_rejects(self):
        for kind in ("base", "profile", "schema", "temperature"):
            with self.subTest(kind=kind):
                original = copy.deepcopy(self.manifest)
                if kind == "base": self.manifest["base_model"]["snapshot_digest"] = "a" * 64
                elif kind == "profile": self.manifest["runtime_profile"]["maximum_length"] = 300
                elif kind == "schema": self.manifest["schema"] = "hepta.unsupported.v1"
                else: self.manifest["calibration"]["temperatures"]["ood"] = 0
                self.snapshot_manifest()
                with self.assertRaises(ValueError): bound_support_rule(self.manifest_path, self.ready)
                self.manifest = original; self.snapshot_manifest()

    def test_noncanonical_float32_scores_cannot_be_rounded_into_acceptance(self):
        for bad in (1e100, 0.1):
            with self.subTest(value=bad):
                value = self.observation(); value["scores"]["action"][0][0] = bad
                child = self.launch(value)
                with self.assertRaisesRegex(WorkerTransportError, "canonical finite float32"):
                    child.exchange(self.request(), "a" * 64)
                self.assert_reaped(child)
