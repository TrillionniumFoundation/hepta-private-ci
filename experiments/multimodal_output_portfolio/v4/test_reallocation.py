"""Replay one actual finite research generation's changing modality allocations."""
import unittest
from portfolio import Config, State, execute


class FeedbackReallocationTests(unittest.TestCase):
    def test_within_one_episode_switches_modality_after_observation(self):
        # Costly new-Cell activations cannot be amortized by fractional weights.
        cfg = Config(horizon=3, risk_aversion=0, activation_cost=1,
                     cost_shadow_price=0.02)
        receipt = execute(State((0, 0, 0, 0), 12), cfg, seed=0)
        realized = [row["allocation"] for row in receipt["records"]
                    if any(row["allocation"])]
        self.assertEqual(realized, [(0, 0, 1, 1), (0, 1, 0, 0), (1, 0, 0, 0)])
        self.assertEqual([row["observed_shock"] for row in receipt["records"]
                          if "observed_shock" in row], [2, 2, 1])
        self.assertEqual(set(receipt["outputs"]), {"text", "audio", "image", "video"})
        self.assertLessEqual(receipt["spent"], 12)


if __name__ == "__main__":
    unittest.main()
