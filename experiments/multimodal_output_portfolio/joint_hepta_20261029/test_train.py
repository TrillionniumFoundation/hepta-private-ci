"""Comparison integrity and actual-file NDU-only learning integration checks."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch

from experiments.multimodal_output_portfolio.unified_20261028.profile import certainty_equivalent
from .learning import actor_score_loss
from .mechanism_data import batch
from .media import utility
from .model import JointGenerator
from .runtime import execute, make_profile
from .train import paired_comparison


def comparison_result(offset, seal_cost):
    rows = [{"source": source, "draw": draw, "return": 0.1 * source - 0.2 * draw + offset,
             "net_with_audit_close": 0.1 * source - 0.2 * draw + offset - seal_cost}
            for source in range(3) for draw in range(2)]
    return {"rows": rows,
            "population_ce_with_audit": certainty_equivalent([r["net_with_audit_close"] for r in rows], 2)}


class PairedComparisonTests(unittest.TestCase):
    def test_complete_pairs_preserve_primary_scope_and_audit_sensitivity(self):
        left, right = comparison_result(0.1, 0.2), comparison_result(0.0, 0.01)
        right["rows"].reverse()
        result = paired_comparison(left, right, seed=91, replicates=30)
        self.assertAlmostEqual(result["ce_difference_registered_complete_serving_cost"], 0.1, places=12)
        self.assertAlmostEqual(result["ce_difference_including_final_audit_seal_sensitivity"], -0.09, places=12)
        self.assertTrue(all(abs(value - 0.1) < 1e-12 for value in result["source_bootstrap_95"]))
        self.assertTrue(result["excludes_training_seed_uncertainty"])

    def test_missing_and_repeated_draws_cannot_inflate_paired_evidence(self):
        left, right = comparison_result(0.1, 0.0), comparison_result(0.0, 0.0)
        missing = deepcopy(right)
        missing["rows"].pop()
        repeated = deepcopy(right)
        repeated["rows"].append(deepcopy(repeated["rows"][0]))
        for invalid in (missing, repeated):
            with self.assertRaisesRegex(ValueError, "incomplete or repeated"):
                paired_comparison(left, invalid, seed=91, replicates=10)


class ActualScoreLearningTests(unittest.TestCase):
    def test_readback_ndu_score_alone_reaches_generation_without_critic_or_supervision(self):
        torch.set_num_threads(1)
        torch.manual_seed(739)
        model = JointGenerator(width=8)
        profile = make_profile()
        episodes = []
        with tempfile.TemporaryDirectory() as temporary:
            for draw, identity in enumerate((5, 19)):
                public, target = batch([identity], "unit-score-only")
                episode = execute(
                    model, public, lambda output: utility(output, target).item(),
                    Path(temporary) / f"draw-{draw}", seed=107 + draw * 1009,
                    context_id=f"unit-score.{identity}", source_id=f"source.{identity}",
                    profile=profile, prefix=("shared", "verify"), strategy="dynamic",
                )
                self.assertEqual(episode.record["outcome"]["terminal_kind"], "delivered")
                self.assertTrue(episode.record["contract_validated"])
                self.assertAlmostEqual(
                    episode.net_return,
                    episode.record["outcome"]["delivered_utility"] - episode.record["actual_cost"],
                    places=12,
                )
                episodes.append(episode)
        # No supervised_loss or critic loss enters this graph or assertion.
        loss, stats = actor_score_loss(
            torch.stack([episode.log_probability for episode in episodes]),
            [episode.net_return for episode in episodes], independent_episodes=True,
        )
        named = list(model.named_parameters())
        gradients = torch.autograd.grad(loss, [value for _, value in named], allow_unused=True)
        measured = {name: gradient for (name, _), gradient in zip(named, gradients)}
        families = ("image_encoder.", "audio_encoder.", "video_encoder.", "token_encoder.",
                    "encoder_fusion.", "core.", "adapters.", "actor.", "emissions.image.",
                    "emissions.audio.", "emissions.video.", "emissions.text.")
        for family in families:
            values = [gradient for name, gradient in measured.items()
                      if name.startswith(family) and gradient is not None]
            self.assertTrue(values, family)
            self.assertTrue(all(bool(torch.isfinite(value).all()) for value in values), family)
            self.assertGreater(sum(float(value.abs().sum()) for value in values), 0.0, family)
        self.assertTrue(all(gradient is None for name, gradient in measured.items()
                            if name.startswith(("critic.", "delivery_critic."))))
        self.assertFalse(stats["supervised_loss_included"])


if __name__ == "__main__":
    unittest.main()
