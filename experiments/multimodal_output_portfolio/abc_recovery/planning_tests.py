"""Synthetic fitting and real sampler checks, without evaluation source access."""

from collections import Counter
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from ..v6.data import Observation
from ..v7.model import SlotPortfolio
from .control import Feedback, PLANS, PROFILES
from .critic import ActionCritic, FiniteHorizonCritic
from .emission import output_digests
from .planning import mpc_action_values, mpc_actions
from .route import fit_route, load_route, save_route
from .runtime import initialize, public_digest, public_features, public_frame, transition


class PlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def setUp(self):
        with torch.random.fork_rng(devices=[]):
            torch.random.set_rng_state(torch.Generator().manual_seed(51).get_state())
            self.model = SlotPortfolio().eval().requires_grad_(False)
        pixels = torch.full((2, 1, 28, 56), .5)
        tokens = torch.tensor([1, 9, 12, 11, 13, 11, 2, 0]).repeat(2, 1)
        observation = Observation(pixels, torch.ones_like(pixels), tokens)
        self.run = initialize(self.model, observation, generator=torch.Generator().manual_seed(82))
        self.frame = public_frame(self.run)
        heads = [ActionCritic(673, 2., horizon, 100 + horizon, 8).eval().requires_grad_(False) for horizon in (1, 2)]
        self.feedback = Feedback(FiniteHorizonCritic(*heads), dict(PROFILES["feedback"]))

    def test_planning_replays_its_own_stream_and_counts_actual_sampler_work(self):
        streams, drafts = [], []
        def tracked(model, run, action, *, generator):
            streams.append(generator.initial_seed())
            child = transition(model, run, action, generator=generator)
            drafts.append(output_digests(child.pixels, child.tokens))
            return child
        original = public_digest(self.frame)
        global_rng = torch.random.get_rng_state().clone()
        work_a, work_b = Counter(), Counter()
        with patch("experiments.multimodal_output_portfolio.abc_recovery.planning.transition", side_effect=tracked):
            first = mpc_action_values(self.model, self.frame, self.feedback, 11, work=work_a)
            second = mpc_action_values(self.model, self.frame, self.feedback, 11, work=work_b)
            mpc_action_values(self.model, self.frame, self.feedback, 12)
        self.assertTrue(torch.equal(first, second))
        self.assertEqual((streams[:16], drafts[:16], work_a), (streams[16:32], drafts[16:32], work_b))
        self.assertEqual(len(set(streams[:16])), 16)
        self.assertNotEqual(streams[:16], streams[32:])
        self.assertNotEqual(drafts[4:16], drafts[36:])
        self.assertTrue(torch.equal(global_rng, torch.random.get_rng_state()))
        self.assertEqual(public_digest(self.frame), original)
        self.assertEqual({key: work_a[key] for key in ("state_transition_calls", "emission_calls", "public_feature_calls", "critic_calls", "simulation_examples")},
                         {"state_transition_calls": 16, "emission_calls": 12, "public_feature_calls": 17, "critic_calls": 17, "simulation_examples": 32})
        self.assertEqual(work_a["planner_emission_calls"], 12)
        self.assertEqual(work_a["sampled_bernoulli_variables"], 12 * 2 * 28 * 56)
        self.assertTrue(torch.isfinite(first).all() and (first > 0).all())

    def test_mpc_averages_moments_before_choice_not_logs_or_sample_minimum(self):
        # Semantic: values 1,9,1,9, arithmetic mean 5 but geometric mean 3.
        # Image: constant 4. Only arithmetic moment aggregation prefers image.
        one = self.feedback.critic.one_step_model
        two = self.feedback.critic.two_step_model
        samples = [1., 9., 1., 9.] + [4.] * 4 + [20.] * 8
        answers = [torch.full((2, 5), value) for value in samples]
        with patch.object(one, "predict", side_effect=answers), patch.object(two, "predict", return_value=torch.full((2, 5), 10.)):
            values = mpc_action_values(self.model, self.frame, self.feedback, 49)
        expected = torch.tensor([10., 5 * math.exp(.004), 4 * math.exp(.004), 20 * math.exp(.004), 20 * math.exp(.004)]).repeat(2, 1)
        torch.testing.assert_close(values, expected)
        self.assertEqual(values.argmin(1).tolist(), [2, 2])

    def test_last_step_uses_only_current_q1_and_no_planning_simulations(self):
        child = transition(self.model, self.run, "refine_image", generator=torch.Generator().manual_seed(991))
        frame = public_frame(child)
        expected = self.feedback.critic.one_step_model.predict(public_features(self.model, frame)).argmin(1)
        work = Counter()
        with patch("experiments.multimodal_output_portfolio.abc_recovery.planning.transition", side_effect=AssertionError("H1 must not simulate")):
            actual = mpc_actions(self.model, frame, self.feedback, 11, work=work)
        self.assertTrue(torch.equal(actual, expected))
        self.assertEqual((work["critic_calls"], work["public_feature_calls"], work["simulation_examples"], work["emission_calls"]), (1, 1, 0, 0))

    def test_private_future_labels_and_unregistered_profiles_cannot_enter_api(self):
        for kwargs in ({"target": object()}, {"future_generator": torch.Generator()}, {"actual_child_tree": object()}):
            with self.assertRaises(TypeError):
                mpc_actions(self.model, self.frame, self.feedback, 11, **kwargs)
        with self.assertRaises(ValueError):
            mpc_actions(self.model, self.run, self.feedback, 11)
        with self.assertRaises(ValueError):
            mpc_actions(self.model, replace(self.frame, state=replace(self.frame.state, source_digest="owner-only")), self.feedback, 11)
        different = Feedback(self.feedback.critic, dict(PROFILES["draft_masked_feedback"]), "draft_masked_feedback")
        with self.assertRaises(ValueError):
            mpc_actions(self.model, self.frame, different, 11)


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def fixture(self):
        features = torch.zeros(16, 5, 673)
        features[:, 0, 0] = torch.linspace(-1, 1, 16)
        features[:, 0, -1], features[:, 1:, -1] = 1., .5
        utility = .1 * features[:, 0, :1] + torch.linspace(-.3, .5, 21)[None, :]
        data = {"role": "forecast_fit", "plans": PLANS, "features": features,
                "metrics": {"primary": {"utility": utility}}}
        config = {"hidden_dim": 8, "steps_per_horizon": 200, "batch_size": 16, "learning_rate": .02}
        return data, config

    def test_actual_moment_fit_decreases_error_is_positive_reproducible_and_saved(self):
        data, config = self.fixture()
        before = torch.random.get_rng_state().clone()
        model = fit_route(data, 71, config)
        duplicate = fit_route(data, 71, config)
        self.assertTrue(torch.equal(before, torch.random.get_rng_state()))
        report = model.fit_report
        self.assertLess(report["final_full_mse"], report["initial_full_mse"] * .01)
        predictions = model.predict(data["features"][:, 0])
        self.assertTrue(torch.isfinite(predictions).all() and (predictions > 0).all())
        for key, value in model.state_dict().items():
            self.assertTrue(torch.equal(value, duplicate.state_dict()[key]))
        self.assertEqual(model.choose(data["features"][:, 0]).tolist(), [20] * 16)
        self.assertAlmostEqual(report["target_max"], math.exp(.8), places=5)
        self.assertAlmostEqual(report["target_min"], math.exp(-2 * (.6 - .004)), places=5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.pt"
            save_route(model, path)
            loaded = load_route(path)
            self.assertTrue(torch.equal(predictions, loaded.predict(data["features"][:, 0])))
            self.assertEqual(report, loaded.fit_report)
            with self.assertRaises(FileExistsError):
                save_route(model, path)

    def test_route_requires_fit_role_and_uses_initial_features_only(self):
        data, config = self.fixture()
        config["steps_per_horizon"] = 2
        with self.assertRaises(ValueError):
            fit_route(dict(data, role="development"), 7, config)
        changed = dict(data, features=data["features"].clone())
        changed["features"][:, 1:] = float("nan")
        first, second = fit_route(data, 7, config), fit_route(changed, 7, config)
        self.assertTrue(torch.equal(first.predict(data["features"][:, 0]), second.predict(data["features"][:, 0])))
        with self.assertRaises(TypeError):
            first.choose(data["features"][:, 0], future_features=data["features"][:, 1:])
        with self.assertRaises(ValueError):
            first.choose(data["features"][:, 1])


if __name__ == "__main__":
    unittest.main()
