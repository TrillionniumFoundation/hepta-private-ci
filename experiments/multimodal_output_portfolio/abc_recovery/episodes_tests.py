"""Real resident execution preserves the paired current-state information law."""

from collections import Counter
from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import Observation
from ..v7.model import SlotPortfolio
from .episodes import fixed_intervention, resident_episode, root_frame
from .runtime import public_features, public_frame


class EpisodeTests(unittest.TestCase):
    def test_fixed_allocation_and_stop_consume_real_cost_without_truth(self):
        torch.set_num_threads(2)
        with torch.random.fork_rng():
            torch.manual_seed(51)
            model = SlotPortfolio().eval().requires_grad_(False)
        pixels = torch.rand((1, 1, 28, 56), generator=torch.Generator().manual_seed(11))
        observation = Observation(pixels, torch.ones_like(pixels),
                                  torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]))
        with tempfile.TemporaryDirectory() as temporary:
            first = resident_episode(model, observation, policy_name="fixed", actual_stream_key=(7,),
                                     archive_path=Path(temporary) / "first.zip")
            second = resident_episode(model, observation, policy_name="tuned_static",
                                      static_plan=("refine_image", "refine_text"), actual_stream_key=(7,),
                                      archive_path=Path(temporary) / "second.zip")
            torch.testing.assert_close(first["pixels"], second["pixels"], rtol=0, atol=0)
            self.assertEqual(first["captions"], second["captions"])
            self.assertEqual(first["raw"], second["raw"])
            self.assertEqual(first["work"]["emission_calls"], 3)
            self.assertGreater(first["wall_ns"], 0)
            stopped = resident_episode(model, observation, policy_name="tuned_static", static_plan=(),
                                       actual_stream_key=(7,), archive_path=Path(temporary) / "stop.zip")
            self.assertEqual(stopped["path"], ())
            self.assertEqual(stopped["work"]["emission_calls"], 1)
        adaptive, initial = fixed_intervention(model, observation, path=("refine_semantic", "couple"),
                                               actual_stream_key=("development", 608, 17, "clean"))
        clamped, same_initial = fixed_intervention(model, observation, path=("refine_semantic", "couple"),
                                                   actual_stream_key=("development", 608, 17, "clean"),
                                                   shared_mode="clamped_initial")
        torch.testing.assert_close(initial.pixels, same_initial.pixels, rtol=0, atol=0)
        torch.testing.assert_close(initial.tokens, same_initial.tokens, rtol=0, atol=0)
        torch.testing.assert_close(clamped.state.h, initial.state.h, rtol=0, atol=0)
        self.assertFalse(torch.equal(adaptive.state.h, clamped.state.h))
        data = {"features": public_features(model, initial)[:, None],
                "root_pixels": initial.pixels.to(torch.uint8), "root_tokens": initial.tokens}
        rebuilt = root_frame(data)
        torch.testing.assert_close(public_features(model, rebuilt), data["features"][:, 0], rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
