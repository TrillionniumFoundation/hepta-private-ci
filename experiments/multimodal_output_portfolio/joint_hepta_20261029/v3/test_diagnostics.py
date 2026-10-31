"""Negative controls for paired risk diagnostics and actual media readback."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from ..mechanism_data import batch
from ..model import JointGenerator as BaseGenerator, tensor_digest
from .diagnostics import (certainty_equivalent, critic_calibration, evaluate_prefix,
                          fit_validate_critics, paired_ce_difference, summarize_prefix, verify_information,
                          _fork, _rng_digest)


class RiskDiagnosticsTests(unittest.TestCase):
    def test_paired_difference_is_not_risk_of_difference(self):
        left, right = [0., 1.], [1., 0.]
        result = paired_ce_difference(left, right, bootstrap=40)
        self.assertAlmostEqual(result["ce_delta"], 0., places=12)
        self.assertLess(certainty_equivalent(np.asarray(left) - right), -.5)
        self.assertEqual(result["bootstrap_unit"], "future_draw_within_frozen_prefix")

    def test_source_uniform_population_is_not_row_uniform_or_mean_conditional_ce(self):
        result = paired_ce_difference([0., 0., 1.], [0., 0., 0.],
                                     source_ids=["a", "a", "b"], bootstrap=40)
        self.assertAlmostEqual(result["ce_left"], certainty_equivalent([0., 1.]), places=12)
        self.assertNotAlmostEqual(result["ce_left"], certainty_equivalent([0., 0., 1.]), places=4)
        self.assertNotAlmostEqual(result["ce_left"], .5, places=4)
        self.assertEqual(result["independent_units"], 2)

    def test_proper_moment_critic_detects_naive_log_return_regression(self):
        true_log_moment = -2 * certainty_equivalent([0., 1.])
        correct = [{"suffix_return": value, "predicted_suffix_log_moment": true_log_moment}
                   for value in [0., 1.]]
        wrong = [{"suffix_return": value, "predicted_suffix_log_moment": -1.} for value in [0., 1.]]
        calibrated, naive = critic_calibration(correct), critic_calibration(wrong)
        self.assertAlmostEqual(calibrated["ce_error"], 0., places=12)
        self.assertGreater(naive["ce_error"], .1)
        self.assertLess(calibrated["proper_moment_loss"], naive["proper_moment_loss"])

    def test_ranking_retains_bad_critic_choice_and_rejects_unpaired_records(self):
        rows = []
        for arm, reward, prediction in (("stop", .3, -1.2), ("shared", .4, -.4)):
            for draw in range(3):
                rows.append({"arm": arm, "draw": draw, "frozen_prefix_sha256": "prefix",
                    "future_randomness_sha256": f"noise-{draw}", "complete_return": reward,
                    "suffix_return": reward, "predicted_suffix_log_moment": prediction,
                    "utility": reward + .1, "complete_cost": .1, "suffix_cost": .1, "failure": None})
        result = summarize_prefix(rows, bootstrap=0)
        self.assertEqual(result["critic_ranking"]["predicted_best_action"], "stop")
        self.assertEqual(result["critic_ranking"]["empirical_best_action"], "shared")
        self.assertAlmostEqual(result["critic_ranking"]["empirical_ce_gap_of_predicted_choice"], .1)
        self.assertFalse(result["research_effect_qualified"])
        malformed = deepcopy(rows)
        malformed[-1]["future_randomness_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "paired future randomness"):
            summarize_prefix(malformed, bootstrap=0)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            summarize_prefix(rows + rows[:1], bootstrap=0)

    def test_reject_nonfinite_observations_without_clipping(self):
        with self.assertRaises(ValueError):
            certainty_equivalent([0., float("nan")])
        with self.assertRaises(ValueError):
            paired_ce_difference([0.], [0., 1.])


class PublicVerificationTests(unittest.TestCase):
    def test_feedback_can_change_when_content_does_not_and_repeat_is_not_new_information(self):
        torch.manual_seed(25)
        model = BaseGenerator(width=8, mode="ordinary").eval()
        public, _ = batch([7], "diagnostics-test-only")
        state = model.encode(public)
        before = tensor_digest(state.tensors())
        result = verify_information(model, state, public, 1.)
        self.assertFalse(result["first_content_changed"])
        self.assertTrue(result["first_feedback_changed"])
        self.assertGreater(result["fixed_clock_actor_probability_l1"], 0.)
        self.assertFalse(result["repeated_content_changed"])
        self.assertFalse(result["repeated_feedback_changed"])
        self.assertEqual(tensor_digest(state.tensors()), before)

    def test_future_rng_forks_are_independent_and_do_not_mutate_prefix(self):
        @dataclass(frozen=True)
        class Tape:
            actor_rng: object
            emission_rng: object
        snapshot = Tape(torch.Generator().manual_seed(2), torch.Generator().manual_seed(3))
        original = _rng_digest(snapshot)
        first, paired, independent = _fork(snapshot, 11), _fork(snapshot, 11), _fork(snapshot, 12)
        self.assertEqual(_rng_digest(first), _rng_digest(paired))
        self.assertNotEqual(_rng_digest(first), _rng_digest(independent))
        torch.rand(3, generator=first.actor_rng)
        self.assertEqual(_rng_digest(snapshot), original)
        self.assertNotEqual(_rng_digest(first), _rng_digest(paired))


class ActualReadbackTests(unittest.TestCase):
    def test_actual_v3_branches_keep_raw_readbacks_and_targets_out_of_generation(self):
        from ..media import read_bundle, utility
        from .model import JointGenerator
        torch.set_num_threads(1)
        torch.manual_seed(41)
        model = JointGenerator(width=8, mode="ordinary").eval()
        public, target = batch([13], "diagnostics-integration-only")
        changed = {key: value.clone() for key, value in target.items()}
        changed["image"] = 1 - changed["image"]
        changed["text"][:, 0] = (changed["text"][:, 0] + 1) % 63
        original_hash = tensor_digest(model.state_dict())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            options = dict(source_id="test-source", prefix=("shared",), draws=2, seed=93,
                           continuation="stop", bootstrap=0, actions=("stop", "shared", "verify"))
            first = evaluate_prefix(model, public, lambda sample: utility(sample, target).item(), root / "first", **options)
            second = evaluate_prefix(model, public, lambda sample: utility(sample, changed).item(), root / "second", **options)
            self.assertEqual([r["readback"]["readback_sha256"] for r in first["rows"]],
                             [r["readback"]["readback_sha256"] for r in second["rows"]])
            self.assertNotEqual([r["utility"] for r in first["rows"]], [r["utility"] for r in second["rows"]])
            for row in first["rows"]:
                path = Path(row["trajectory_file"]).parent
                readback, _ = read_bundle(path / "outputs")
                with np.load(path / "READBACK.npz", allow_pickle=False) as stored:
                    for modality in readback:
                        np.testing.assert_array_equal(stored["state/" + modality], readback[modality].numpy())
                receipt = json.loads((path / "READBACK_SCORE.json").read_text())
                self.assertEqual(receipt["payload_sha256"], hashlib.sha256((path / "READBACK.npz").read_bytes()).hexdigest())
                self.assertAlmostEqual(row["utility"], float(utility(readback, target)), places=12)
                self.assertAlmostEqual(row["complete_return"], row["utility"] - row["complete_cost"], places=12)
                self.assertAlmostEqual(row["suffix_return"], row["utility"] - row["suffix_cost"], places=12)
                self.assertIsNone(row["failure"])
            self.assertEqual(first["summary"]["draws_per_arm"], 2)
            self.assertFalse(first["research_effect_qualified"])
            self.assertEqual(tensor_digest(model.state_dict()), original_hash)

    def test_critic_fit_uses_disjoint_sources_and_preserves_actor_and_generator(self):
        from ..media import utility
        from .model import JointGenerator
        torch.set_num_threads(1)
        torch.manual_seed(52)
        model = JointGenerator(width=8, mode="ordinary").eval()
        frozen = {name: value.detach().clone() for name, value in model.state_dict().items()
                  if not name.startswith(("critic.", "delivery_critic."))}
        delivery_before = tensor_digest(model.delivery_critic.state_dict())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cohorts = {"training": [], "validation": []}
            for role in cohorts:
                for source in range(2):
                    public, target = batch([source], f"diagnostics-fit-test-{role}")
                    cohorts[role].append(evaluate_prefix(model, public,
                        lambda sample, labels=target: utility(sample, labels).item(), root / f"{role}-{source}",
                        source_id=f"{role}-{source}", draws=2, seed=97 + source, continuation="stop",
                        bootstrap=0, actions=("stop", "shared")))
            with self.assertRaisesRegex(ValueError, "overlaps"):
                fit_validate_critics(model, cohorts["training"], cohorts["training"], root / "overlap")
            result = fit_validate_critics(model, cohorts["training"], cohorts["validation"], root / "fit",
                                         updates=12, learning_rate=.01)
            self.assertTrue(result["generator_and_actor_unchanged"])
            self.assertFalse(result["validation_used_for_selection"])
            self.assertFalse(result["policy_improvement_established"])
            self.assertLess(result["after"]["training"]["delivery_critic"]["proper_moment_loss"],
                            result["before"]["training"]["delivery_critic"]["proper_moment_loss"])
            self.assertNotEqual(tensor_digest(model.delivery_critic.state_dict()), delivery_before)
            for name, value in frozen.items():
                torch.testing.assert_close(model.state_dict()[name], value, rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
