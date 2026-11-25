"""Cache parity and refusal checks; never a training-acceleration claim."""

import unittest
import torch
from .model import ModelConfig, SmallHCSN
from .fixed_law_benchmark import FixedLawHCSN, parity


class FixedLawTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(5117)

    def pair(self, width=8):
        config = ModelConfig(neurons=width, slow_every=10**9)
        reference, cached = SmallHCSN(config).eval(), FixedLawHCSN(config).eval()
        cached.load_state_dict(reference.state_dict())
        return reference, cached

    def test_full_population_output_and_all_state_parity_three_widths(self):
        for width in (8, 32, 64):
            reference, cached = self.pair(width)
            x = torch.randn(9, 2, 6, dtype=torch.float64)*.3
            margin = torch.linspace(.3, .8, width, dtype=torch.float64)[None].expand(2, -1)
            with torch.no_grad():
                a = reference(x, state=reference.initial_state(2, margin), return_features=True)
                b = cached(x, state=cached.initial_state(2, margin), return_features=True)
            checked = parity(a, b)
            self.assertLessEqual(checked["maximum_error"], 3e-12)
            self.assertTrue(checked["step_equal"] and checked["all_outputs_and_state_finite"])
            self.assertEqual((cached.plan_builds, cached.cache_hits), (1, 8))

    def test_changing_law_and_enabled_autograd_are_refused(self):
        _, cached = self.pair()
        x = torch.randn(3, 1, 6, dtype=torch.float64)*.3
        with self.assertRaisesRegex(RuntimeError, "inference-only"):
            cached(x)
        with torch.no_grad():
            cached(x)
            changed = x.clone()
            changed[0, 0, 0] += 2.
            with self.assertRaisesRegex(ValueError, "cache mismatch"):
                cached(changed)
        with self.assertRaisesRegex(ValueError, "frozen control schedule"):
            FixedLawHCSN(ModelConfig(slow_every=2))

    def test_new_content_and_continued_state_are_not_cached_outputs(self):
        reference, cached = self.pair()
        x = torch.randn(10, 2, 6, dtype=torch.float64)*.3
        changed = x.clone()
        changed[4:, :, 0] += 1.2
        with torch.no_grad():
            original = cached(x, return_features=True)
            expected = reference(changed, return_features=True)
            prefix = cached(changed[:3], return_features=True)
            tail = cached(changed[3:], state=prefix[2], return_features=True)
            combined = (torch.cat((prefix[0], tail[0])), torch.cat((prefix[1], tail[1])), tail[2])
        self.assertLessEqual(parity(expected, combined)["maximum_error"], 3e-12)
        self.assertGreater(float((original[2].density[..., 1, :]-tail[2].density[..., 1, :]).abs().max()), 1e-5)
        self.assertEqual((cached.plan_builds, cached.cache_hits), (1, 19))


if __name__ == "__main__":
    unittest.main()
