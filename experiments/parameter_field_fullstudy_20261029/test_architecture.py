"""Synthetic engineering checks only; no scientific data or holdout is opened."""

import argparse
from copy import deepcopy
from pathlib import Path
import unittest

import torch

from experiments.multimodal_output_portfolio.v6.data import (
    BOS, CAPTION_LENGTH, Observation, Target, VOCAB,
)
from experiments.multimodal_output_portfolio.v6.neural import ACTIONS
from .architecture import TrainableTemporalModule, matched_pair


REFERENCE_ROOT = Path(__file__).resolve().parents[2]


class ArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def module(self, mode):
        with torch.random.fork_rng():
            torch.manual_seed(701)
            return TrainableTemporalModule(3, 4, mode, REFERENCE_ROOT).double()

    def test_sequence_and_gradients_match_pinned_reference(self):
        for mode in ("ordinary", "dual"):
            with self.subTest(mode=mode):
                module = self.module(mode)
                reference = deepcopy(module)
                rng = torch.Generator().manual_seed(117)
                x = torch.randn(2, 6, 3, generator=rng, dtype=torch.float64)
                dt = torch.tensor([[.3, .8, 0, .2, 1., .5], [.5, .2, .7, 0, .4, .9]], dtype=x.dtype)
                actual, state = module(x, dt=dt)
                expected, aux = reference.layer(reference.input_projection(x), dt)
                torch.testing.assert_close(actual, expected, rtol=1e-10, atol=1e-12)
                for value, key in zip(state.tensors()[:3], ("content", "voltage", "adaptation")):
                    torch.testing.assert_close(value, aux[key][:, -1], rtol=1e-10, atol=1e-12)
                actual.square().mean().backward()
                expected.square().mean().backward()
                for (name, first), (_, second) in zip(module.named_parameters(), reference.named_parameters()):
                    self.assertIsNotNone(first.grad, name)
                    torch.testing.assert_close(first.grad, second.grad, rtol=1e-8, atol=1e-10)

    def test_complete_state_restore_replays_next_steps(self):
        for mode in ("ordinary", "dual"):
            module = self.module(mode)
            x = torch.randn(2, 8, 3, generator=torch.Generator().manual_seed(31), dtype=torch.float64)
            prefix, saved = module(x[:, :3])
            checkpoint = saved.detached_clone()
            first, terminal = module(x[:, 3:], saved)
            replay, restored_terminal = module(x[:, 3:], checkpoint)
            self.assertTrue(torch.equal(first, replay))
            for before, after in zip(terminal.tensors(), restored_terminal.tensors()):
                self.assertTrue(torch.equal(before, after))
            whole, _ = module(x)
            self.assertTrue(torch.equal(torch.cat((prefix, first), dim=1), whole))
            self.assertTrue(all(a.data_ptr() != b.data_ptr()
                                for a, b in zip(saved.tensors(), checkpoint.tensors())))

    def test_full_generator_matching_and_backbone_gradients(self):
        models = matched_pair(reference_root=REFERENCE_ROOT, seed=221, hidden=16)
        rng = torch.Generator().manual_seed(15)
        tokens = torch.randint(len(VOCAB), (2, CAPTION_LENGTH), generator=rng)
        tokens[:, 0] = BOS
        pixels = torch.rand(2, 1, 28, 56, generator=rng)
        observation = Observation(pixels, torch.ones_like(pixels), tokens)
        target = Target(torch.rand(2, 1, 28, 56, generator=rng), tokens,
                        torch.randint(10, (2, 2), generator=rng))
        outcomes = []
        for model in models.values():
            state = model.encode(observation)
            for action in ACTIONS:
                state = model.step(state, action)
            output = model.decode(state, teacher_tokens=tokens)
            model.loss(output, target)["joint"].mean().backward()
            for name, parameter in model.named_parameters():
                self.assertTrue(parameter.requires_grad, name)
                self.assertIsNotNone(parameter.grad, name)
                self.assertTrue(torch.isfinite(parameter.grad).all(), name)
                if name.startswith(("text_encoder.", "text_decoder.")):
                    self.assertGreater(float(parameter.grad.abs().sum()), 0., name)
            with torch.no_grad():
                hard = model.decode(state)
            self.assertEqual(hard.token_ids.shape, (2, CAPTION_LENGTH))
            outcomes.append(output.text_logits.detach())
        self.assertFalse(torch.equal(*outcomes))

    def test_decoder_carries_all_states_from_nonzero_initial_content(self):
        module = self.module("dual")
        x = torch.randn(2, 5, 3, generator=torch.Generator().manual_seed(18), dtype=torch.float64)
        initial = module.initial_state(2, content=torch.full((2, 4), .2, dtype=torch.float64))
        expected, final = module(x, initial)
        steps, state = [], initial
        for item in x.unbind(1):
            value, state = module.step(item, state)
            steps.append(value)
        self.assertTrue(torch.equal(expected, torch.stack(steps, dim=1)))
        for before, after in zip(final.tensors(), state.tensors()):
            self.assertTrue(torch.equal(before, after))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-root", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    REFERENCE_ROOT = args.reference_root
    unittest.main(argv=[__file__, *remaining])
