"""Command conditioning, checkpoint custody, and legacy compatibility tests."""

from pathlib import Path
import tempfile
import unittest

import torch

from .conditioned import ConditionedPortfolio, ConditionedSnapshot
from .data import Observation, SourceCorpus, SourceSplit, Target
from .neural import (ACTIONS, CONDITIONED_ARCHITECTURE, CONDITIONED_SCHEMA, NeuralPortfolio,
                     NeuralSnapshot, TrainConfig, checkpoint_file_sha256, load_snapshot,
                     model_from_config, parameter_hash, read_checkpoint, snapshot_from_model,
                     train_profiles)
from .plan_training import ControlledSnapshot, PlanHead


class ConditionedBoundaryTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(17)
        self.model = ConditionedPortfolio(hidden=16)
        pixels = torch.rand(1, 1, 28, 56).repeat(2, 1, 1, 1)
        tokens = torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0],
                               [1, 10, 12, 11, 13, 11, 2, 0]])
        self.observation = Observation(pixels, torch.ones_like(pixels), tokens)

    def test_public_command_changes_content_and_receives_gradients(self):
        pixels, tokens = self.observation.pixels.clone(), self.observation.text_tokens.clone()
        state = self.model.encode(self.observation)
        output = self.model.decode(state)
        self.assertFalse(torch.equal(state.context[0], state.context[1]))
        self.assertFalse(torch.equal(output.image_logits[0], output.image_logits[1]))
        objective = output.image_logits.square().mean() + output.text_logits.square().mean()
        objective.backward()
        self.assertGreater(float(self.model.command_embedding.weight.grad[[9, 10]].abs().sum()), 0.)
        self.assertGreater(float(self.model.command_film.weight.grad.abs().sum()), 0.)
        for action in ACTIONS:
            changed = self.model.step(state, action)
            self.assertTrue(torch.equal(changed.context, state.context))
            if action in ("refine_image", "refine_text"):
                self.assertTrue(torch.equal(changed.h, state.h))
        self.assertTrue(torch.equal(self.observation.pixels, pixels))
        self.assertTrue(torch.equal(self.observation.text_tokens, tokens))
        with self.assertRaises(TypeError):
            self.model.encode(Target(pixels, tokens, torch.zeros(2, 2, dtype=torch.long)))

    def test_same_weights_different_noise_config_have_different_state_identities(self):
        first = snapshot_from_model(self.model)
        other_model = ConditionedPortfolio(hidden=16, noise_scale=.2)
        other_model.load_state_dict(self.model.state_dict())
        other = snapshot_from_model(other_model)
        self.assertEqual(parameter_hash(first._model), parameter_hash(other._model))
        self.assertNotEqual(first.fingerprint, other.fingerprint)
        with self.assertRaises(ValueError):
            other.decode(first.encode(self.observation))
        for change in ("snapshot_config", "model_noise", "model_gain", "normalization_epsilon"):
            with self.subTest(change=change):
                snapshot = snapshot_from_model(self.model)
                if change == "snapshot_config":
                    snapshot.config["noise_scale"] = .2
                elif change == "model_noise":
                    snapshot._model.noise_scale = .2
                elif change == "model_gain":
                    snapshot._model.command_gain = .7
                else:
                    snapshot._model.pixel_encoder[6].eps = .01
                with self.assertRaises(RuntimeError):
                    snapshot.verify_integrity()

    def test_variant_roundtrip_binds_config_and_pinned_file_bytes(self):
        snapshot = snapshot_from_model(self.model)
        expected = snapshot.decode(snapshot.encode(self.observation, noise_seed=23))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conditioned.pt"
            snapshot.save(path)
            digest = checkpoint_file_sha256(path)
            restored = load_snapshot(path, expected_file_sha256=digest)
            actual = restored.decode(restored.encode(self.observation, noise_seed=23))
            self.assertIsInstance(restored, ConditionedSnapshot)
            self.assertEqual(restored.config, snapshot.config)
            self.assertEqual(restored.fingerprint, snapshot.fingerprint)
            for name in ("image_logits", "text_logits", "token_ids", "digit_logits"):
                self.assertTrue(torch.equal(getattr(actual, name), getattr(expected, name)))
            with self.assertRaises(ValueError):
                NeuralSnapshot.load(path)
            record = read_checkpoint(path)
            self.assertEqual(record["schema"], CONDITIONED_SCHEMA)
            record["config"]["noise_scale"] = .2
            torch.save(record, path)
            with self.assertRaisesRegex(ValueError, "file SHA-256"):
                load_snapshot(path, expected_file_sha256=digest)
            with self.assertRaisesRegex(ValueError, "parameter/configuration hash"):
                load_snapshot(path)

    def test_controlled_variant_roundtrip_and_complete_allocation_ablation(self):
        base = snapshot_from_model(self.model)
        snapshot = ControlledSnapshot(base, PlanHead(16))
        state = snapshot.encode(self.observation, noise_seed=23, content_control=False)
        initial = base.encode(self.observation, noise_seed=23)
        self.assertEqual(state.plan_indices, (-1, -1))
        self.assertTrue(torch.equal(initial.h, state.neural.h))
        with self.assertRaises(ValueError):
            snapshot.step(state, "couple")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controlled.pt"
            snapshot.save(path)
            digest = checkpoint_file_sha256(path)
            restored = ControlledSnapshot.load(path, expected_file_sha256=digest)
            expected = snapshot.decode(snapshot.encode(self.observation, noise_seed=23))
            actual = restored.decode(restored.encode(self.observation, noise_seed=23))
            self.assertEqual(restored.fingerprint, snapshot.fingerprint)
            self.assertEqual(restored.config, snapshot.config)
            self.assertTrue(torch.equal(expected.image_logits, actual.image_logits))
            self.assertTrue(torch.equal(expected.token_ids, actual.token_ids))
            record = read_checkpoint(path)
            self.assertEqual(record["schema"], "hepta.ndu-v6.controlled-snapshot.v2")
            record["base_record"]["config"]["noise_scale"] = .2
            torch.save(record, path)
            with self.assertRaisesRegex(ValueError, "file SHA-256"):
                ControlledSnapshot.load(path, expected_file_sha256=digest)
            with self.assertRaisesRegex(ValueError, "parameter/configuration hash"):
                ControlledSnapshot.load(path)

    def test_legacy_factory_and_shared_parameter_initialization_are_unchanged(self):
        torch.manual_seed(17)
        legacy = NeuralPortfolio(hidden=16)
        torch.manual_seed(17)
        factory_legacy = model_from_config({"hidden": 16, "noise_scale": .15})
        self.assertEqual(parameter_hash(legacy), parameter_hash(factory_legacy))
        for name, value in legacy.state_dict().items():
            self.assertTrue(torch.equal(value, self.model.state_dict()[name]))
        snapshot = snapshot_from_model(factory_legacy)
        self.assertIs(type(snapshot), NeuralSnapshot)
        self.assertEqual(snapshot.fingerprint, parameter_hash(factory_legacy))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.pt"
            snapshot.save(path)
            restored = NeuralSnapshot.load(path, expected_file_sha256=checkpoint_file_sha256(path))
            self.assertEqual(restored.fingerprint, snapshot.fingerprint)
            self.assertEqual(read_checkpoint(path)["schema"], "hepta.ndu-v6.neural-snapshot.v1")
        with self.assertRaises(ValueError):
            NeuralSnapshot(self.model)

    def test_architecture_option_trains_both_profiles_with_matched_schedules(self):
        # Tiny synthetic fixtures verify API integration, never research quality.
        pixels = (torch.rand(12, 1, 28, 28) * 255).to(torch.uint8)
        source = SourceSplit(pixels, torch.arange(12) % 10,
                             tuple(f"fixture:{i}" for i in range(12)),
                             tuple(f"fixture-hash:{i}" for i in range(12)))
        corpus = SourceCorpus({"train": source}, {"manifest_sha256": "fixture"})
        snapshots, reports = train_profiles(corpus, TrainConfig(seed=13, steps=2, batch_size=4,
            hidden=16, threads=1, architecture=CONDITIONED_ARCHITECTURE))
        for profile, snapshot in snapshots.items():
            self.assertIsInstance(snapshot, ConditionedSnapshot)
            self.assertGreater(reports[profile]["gradient_abs_sum_max"]["command_embedding"], 0.)
            self.assertGreater(reports[profile]["gradient_abs_sum_max"]["command_film"], 0.)
            self.assertEqual(reports[profile]["final_snapshot_sha256"], snapshot.fingerprint)
            self.assertEqual(reports[profile]["final_parameter_sha256"], parameter_hash(snapshot._model))
        for key in ("initial_parameter_sha256", "batch_action_schedule_sha256", "optimizer_updates"):
            self.assertEqual(reports["supervised"][key], reports["terminal_entropic_ndu"][key])


if __name__ == "__main__":
    unittest.main()
