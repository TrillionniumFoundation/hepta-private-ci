"""Real frozen-model execution fixtures; no training or qualification claim."""

from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import torch

from .data import Observation, render_tokens
from .neural import CONDITIONED_ARCHITECTURE, NeuralPortfolio, NeuralSnapshot, model_from_config, snapshot_from_model
from .owner_worker import ROOT, SCHEMA, device_digest, execute, parameters_digest, runtime_versions, sha, source_digest


def prepare_fixture(directory, profile="legacy"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(7301)
        if profile in ("legacy", "controlled_legacy"):
            snapshot = NeuralSnapshot(NeuralPortfolio(hidden=16))
        elif profile in ("conditioned", "controlled"):
            snapshot = snapshot_from_model(model_from_config({"hidden": 16, "noise_scale": .15,
                                                              "architecture": CONDITIONED_ARCHITECTURE}))
        else:
            raise ValueError("Unknown fixture profile")
        if profile in ("controlled", "controlled_legacy"):
            from .plan_training import ControlledSnapshot, PlanHead
            snapshot = ControlledSnapshot(snapshot, PlanHead(16))
    checkpoint = directory / "base.pt"
    snapshot.save(checkpoint)
    pins = {"checkpoint_sha256": sha(checkpoint.read_bytes()), "snapshot_sha256": snapshot.fingerprint,
            "parameters_sha256": parameters_digest(snapshot),
            "config_sha256": sha(json.dumps(snapshot.config, sort_keys=True, separators=(",", ":")).encode()),
            "source_sha256": source_digest(), "python_sha256": sha(Path(sys.executable).read_bytes()),
            "device_sha256": device_digest(),
            "runtime_versions": runtime_versions(), "hidden": 16}
    pixels = np.linspace(0, 1, 28 * 56, dtype="<f4")
    request = {"schema": SCHEMA, "request_id": "generation.fixture.1", "objective_sha256": sha(b"test objective"),
               "input_source_sha256": sha(pixels.tobytes()), "model": pins, "required_modalities": 3,
               "pixels_f32": pixels.view("<u4").tolist(), "mask_f32": [0x3f800000] * (28 * 56),
               "text_tokens": [1, 9, 12, 14, 13, 15, 11, 2], "noise_seed": 17,
               "content_control": True, "actions": ["refine_image", "couple"]}
    fixture = {"repository": str(ROOT), "python": sys.executable, "artifact_root": str(directory.absolute()),
               "checkpoint_name": checkpoint.name, "model_id": "v6.fixture", "pins": pins, "request": request}
    (directory / "fixture.json").write_text(json.dumps(fixture, separators=(",", ":")))
    return fixture, snapshot


class OwnerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture, self.snapshot = prepare_fixture(self.temporary.name)

    def run_request(self, request=None):
        return execute({"checkpoint": str(Path(self.temporary.name) / "base.pt"),
                        "request_json": json.dumps(request or self.fixture["request"], separators=(",", ":"))})

    def test_real_transition_raw_outputs_match_direct_frozen_model(self):
        self.check_direct_output()

    def check_direct_output(self):
        output = self.run_request()
        request = self.fixture["request"]
        pixels = torch.from_numpy(np.asarray(request["pixels_f32"], dtype="<u4").view("<f4").copy()).reshape(1, 1, 28, 56)
        observation = Observation(pixels, torch.ones_like(pixels), torch.tensor([request["text_tokens"]]))
        state = self.snapshot.encode(observation, noise_seed=17)
        for action, recorded in zip(request["actions"], output["states"][1:]):
            state = self.snapshot.step(state, action)
            self.assertEqual(recorded["backend_state_sha256"], self.snapshot.state_key(state))
            self.assertEqual(recorded["values_f32"], self.snapshot.state_features(state).numpy().astype("<f4").view("<u4").reshape(-1).tolist())
        decoded = self.snapshot.decode(state)
        self.assertEqual(output["token_ids"], decoded.token_ids[0].tolist())
        self.assertEqual(output["caption"], render_tokens(decoded.token_ids[0]))
        expected_pixels = (decoded.image_logits.sigmoid().squeeze().numpy() * 255).round().astype(np.uint8)
        expected_png = io.BytesIO()
        Image.fromarray(expected_pixels).save(expected_png, format="PNG")
        self.assertEqual(bytes(output["png"]), expected_png.getvalue())
        with Image.open(io.BytesIO(bytes(output["png"]))) as image:
            np.testing.assert_array_equal(np.asarray(image), expected_pixels)
        self.assertNotEqual(output["states"][0]["state_sha256"], output["states"][-1]["state_sha256"])
        self.assertEqual(output["authority"], "deny_all")
        self.assertEqual(self.snapshot.verify_integrity(), self.fixture["pins"]["snapshot_sha256"])

    def test_conditioned_and_both_controlled_schemas_load_exact_bytes_and_execute(self):
        for profile in ("conditioned", "controlled", "controlled_legacy"):
            self.fixture, self.snapshot = prepare_fixture(self.temporary.name, profile)
            self.check_direct_output()

    def test_invalid_checkpoint_config_rejects_before_any_constructor(self):
        from .conditioned import ConditionedPortfolio
        from .plan_training import PlanHead
        for profile in ("legacy", "conditioned", "controlled_legacy", "controlled"):
            self.fixture, self.snapshot = prepare_fixture(self.temporary.name, profile)
            checkpoint = Path(self.temporary.name) / "base.pt"
            original = torch.load(checkpoint, weights_only=True)
            mutations = ("width", "noise", "unknown_field", "pin")
            if profile.startswith("controlled"):
                mutations += ("gate_width", "gate_context", "gate_unknown_field")
            for mutation in mutations:
                with self.subTest(profile=profile, mutation=mutation):
                    record, request = deepcopy(original), deepcopy(self.fixture["request"])
                    config = (record["base_config"] if profile == "controlled_legacy" else
                              record["base_record"]["config"] if profile == "controlled" else record["config"])
                    if mutation == "width":
                        config["hidden"] = 10**9
                    elif mutation == "noise":
                        config["noise_scale"] = float("nan")
                    elif mutation == "unknown_field":
                        config["unexpected_allocation"] = 10**9
                    elif mutation == "pin":
                        request["model"]["config_sha256"] = "a" * 64
                    elif mutation == "gate_width":
                        record["gate_config"]["hidden"] = 10**9
                    elif mutation == "gate_context":
                        record["gate_config"]["context_size"] = 10**9
                    else:
                        record["gate_config"]["unexpected_allocation"] = 10**9
                    torch.save(record, checkpoint)
                    request["model"]["checkpoint_sha256"] = sha(checkpoint.read_bytes())
                    with (patch.object(NeuralPortfolio, "__init__", side_effect=AssertionError("base allocated")) as base,
                          patch.object(ConditionedPortfolio, "__init__", side_effect=AssertionError("conditioned allocated")) as conditioned,
                          patch.object(PlanHead, "__init__", side_effect=AssertionError("gate allocated")) as gate):
                        with self.assertRaises(ValueError):
                            self.run_request(request)
                        for constructor in (base, conditioned, gate):
                            constructor.assert_not_called()

    def test_pin_target_unknown_action_and_missing_decoder_rejected(self):
        for field, value in (("required_modalities", 15), ("actions", ["repair_caption"]), ("target", [3, 5])):
            request = deepcopy(self.fixture["request"])
            request[field] = value
            with self.assertRaises(ValueError):
                self.run_request(request)
        request = deepcopy(self.fixture["request"])
        request["model"]["config_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "configuration identity"):
            self.run_request(request)

    def test_changed_checkpoint_and_nonfinite_input_rejected(self):
        request = deepcopy(self.fixture["request"])
        request["pixels_f32"][0] = 0x7fc00000
        with self.assertRaisesRegex(ValueError, "Unbounded public input"):
            self.run_request(request)
        checkpoint = Path(self.temporary.name) / "base.pt"
        checkpoint.write_bytes(checkpoint.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.run_request()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--prepare-fixture":
        prepare_fixture(sys.argv[2])
        for profile in ("conditioned", "controlled"):
            prepare_fixture(Path(sys.argv[2]) / profile, profile)
    else:
        unittest.main()
