"""Meaningful safety and inference invariants; synthetic fixtures are unit-only."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import Observation, SourceCorpus, SourceSplit
from ..v6.neural import ACTIONS, read_checkpoint
from .data import make_batch, public_information_sufficiency
from .model import SlotPortfolio
from .snapshot import Snapshot


def fixture_corpus():
    rng = torch.Generator().manual_seed(81)
    source = SourceSplit(torch.randint(256, (32, 1, 28, 28), dtype=torch.uint8, generator=rng),
                         torch.arange(32) % 10, tuple(f"unit:{i}" for i in range(32)),
                         tuple(f"unit-hash:{i}" for i in range(32)))
    return SourceCorpus({"train": source}, {"manifest_sha256": "unit-only"})


class SlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.corpus = fixture_corpus()

    def setUp(self):
        torch.manual_seed(17)
        self.snapshot = Snapshot(SlotPortfolio())
        self.batch = make_batch(self.corpus, "train", 4, 77, view="clean", offset=0)

    def test_runtime_accepts_only_public_observation_and_keeps_source_identity(self):
        with self.assertRaises(TypeError):
            self.snapshot.encode(self.batch.target)
        state = self.snapshot.encode(self.batch.observation, noise_seed=11)
        identity = self.snapshot.observation_identity(state)
        original_context = state.context.clone()
        for index, action in enumerate(ACTIONS, 1):
            state = self.snapshot.step(state, action)
            self.assertEqual(state.step_count, index)
            self.assertEqual(self.snapshot.observation_identity(state), identity)
            self.assertTrue(torch.equal(state.context, original_context))
        with self.assertRaises(ValueError):
            self.snapshot.step(state, "refine_semantic")
        output = self.snapshot.decode(state)
        self.assertEqual(tuple(output.image_logits.shape), (4, 1, 28, 56))
        self.assertEqual(tuple(output.token_ids.shape), (4, 8))
        probabilities = self.snapshot.semantic_probabilities(state)
        self.assertTrue(torch.allclose(probabilities.sum(-1), torch.ones(4, 2)))

    def test_allocation_initial_and_all_modality_actions_preserve_shared_h(self):
        full = self.snapshot.encode(self.batch.observation, noise_seed=9)
        state = self.snapshot.encode(self.batch.observation, noise_seed=9, content_control=False)
        self.assertTrue(torch.equal(state.h, full.h))
        self.assertNotEqual(self.snapshot.state_key(state), self.snapshot.state_key(full))
        h = state.h.clone()
        for action in ("refine_image", "refine_text") * 2:
            state = self.snapshot.step(state, action)
            self.assertTrue(torch.equal(state.h, h))
        for action in ("refine_semantic", "couple"):
            with self.assertRaises(ValueError):
                self.snapshot.step(state, action)

    def test_command_affects_learned_context_and_has_actual_gradients(self):
        model = SlotPortfolio()
        observation = self.batch.observation
        tokens = observation.text_tokens.clone()
        tokens[:, 1] = 19 - tokens[:, 1]
        a = model.encode(observation)
        b = model.encode(Observation(observation.pixels, observation.mask, tokens))
        self.assertGreater(float((a.context - b.context).detach().abs().max()), 1e-7)
        for action in ACTIONS:
            a = model.step(a, action)
        output = model.decode(a, self.batch.target.text_tokens)
        model.loss(output, self.batch.target)["joint"].mean().backward()
        for module in (model.command_attention, model.pixel_encoder, model.pixel_decoder,
                       model.text_decoder, model.semantic_cell, model.coupling_cell):
            self.assertGreater(sum(float(p.grad.abs().sum()) for p in module.parameters()
                                   if p.grad is not None), 0)

    def test_saved_restored_exact_outputs_and_configuration_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.pt"
            sha = self.snapshot.save(path)
            restored = Snapshot.load(path, expected_file_sha256=sha)
            a = self.snapshot.encode(self.batch.observation, 19)
            b = restored.encode(self.batch.observation, 19)
            self.assertEqual(self.snapshot.state_key(a), restored.state_key(b))
            self.assertTrue(torch.equal(self.snapshot.decode(a).image_logits,
                                        restored.decode(b).image_logits))
            self.assertTrue(torch.equal(self.snapshot.decode(a).token_ids,
                                        restored.decode(b).token_ids))
            record = read_checkpoint(path, sha)
            record["config"]["noise_scale"] = .25
            with self.assertRaises(ValueError):
                Snapshot.from_record(record)
            restored._model.noise_scale = .25
            with self.assertRaises(RuntimeError):
                restored.encode(self.batch.observation)
            with self.assertRaises(ValueError):
                Snapshot.load(path, expected_file_sha256="0" * 64)

    def test_public_reliability_does_not_reveal_correctness(self):
        batch = make_batch(self.corpus, "train", 1024, 123, view="conflict_untrusted")
        correct = batch.untrusted_hint_correct
        self.assertGreater(sum(correct), 400)
        self.assertLess(sum(correct), 624)
        markers = batch.observation.text_tokens[:, (2, 4)]
        self.assertTrue(((markers == 11).sum(1) == 1).all())
        self.assertTrue(public_information_sufficiency(batch.observation).all())
        missing = make_batch(self.corpus, "train", 1024, 123, view="missing_untrusted")
        self.assertEqual(batch.source_ids, missing.source_ids)
        self.assertEqual(batch.untrusted_hint_correct, missing.untrusted_hint_correct)
        self.assertTrue(torch.equal(batch.observation.text_tokens, missing.observation.text_tokens))
        self.assertFalse(public_information_sufficiency(missing.observation).any())

    def test_native_state_rejects_non_float32_and_non_hex_identity(self):
        state = self.snapshot.encode(self.batch.observation)
        with self.assertRaises(ValueError):
            self.snapshot.decode(replace(state, h=state.h.double()))
        with self.assertRaises(ValueError):
            self.snapshot.decode(replace(state, source_digest="Q" * 64))

    def test_missing_truth_changes_cannot_change_an_identical_public_observation(self):
        batch = make_batch(self.corpus, "train", 2, 35, view="both_missing")
        tokens = batch.observation.text_tokens.clone()
        tokens[:, 1] = 9
        observation = Observation(batch.observation.pixels, batch.observation.mask, tokens)
        self.assertTrue(torch.equal(observation.pixels[0], observation.pixels[1]))
        self.assertTrue(torch.equal(observation.text_tokens[0], observation.text_tokens[1]))
        model = SlotPortfolio().eval()
        state = model.encode(observation, noise=torch.zeros(2, 96))
        self.assertTrue(torch.equal(state.h[0], state.h[1]))
        self.assertTrue(torch.equal(model.decode(state).image_logits[0],
                                    model.decode(state).image_logits[1]))
        changed = replace(self.batch.observation, mask=torch.zeros_like(self.batch.observation.mask))
        with self.assertRaises(ValueError):
            self.snapshot.encode(changed)


if __name__ == "__main__":
    unittest.main()
