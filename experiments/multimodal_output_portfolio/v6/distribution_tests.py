"""Conditional forecast law, risk limit and frozen-artifact regressions."""

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from .control import ControllerConfig, WorkBudget, choose, entropic_value
from .data import Observation, SourceCorpus, SourceSplit, Target, make_batch
from .distribution import ConditionalForecastBundle, public_features
from .distribution_fit import _score_rows, _selected_diagnostics, _source_scores, endpoint_plan, grouped_error_scale
from .forecast import ForecastArtifact, ForecastBundle, RidgeHead, fit_forecast
from .neural import NeuralPortfolio, NeuralSnapshot
from .observer import Recognizer
from .plan_training import ControlledSnapshot, PlanHead


class PublicSnapshot:
    fingerprint = "a" * 64

    def verify_integrity(self):
        return self.fingerprint

    def observation_identity(self, state):
        return "one-public-input"

    def state_key(self, state):
        return repr(state)

    def state_features(self, state):
        return torch.tensor([state[:2]], dtype=torch.float64)

    def step(self, state, action):
        if action == "refine_image":
            return (.35, .05, action)
        if action == "refine_text":
            return (.45, .45, action)
        return (-.5, .02, action)


class ConditionalDistributionTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.snapshot = PublicSnapshot()
        self.observation = Observation(torch.zeros(1, 1, 28, 56), torch.ones(1, 1, 28, 56),
                                       torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]))
        mean, scale, router = RidgeHead(8, 1), RidgeHead(8, 1), RidgeHead(8, 4)
        mean.weight[0, 0], scale.weight[1, 0] = 1, 1
        self.bundle = ConditionalForecastBundle(mean, scale, router, torch.tensor([-1., 1.]),
                                                self.snapshot.fingerprint, ())
        self.backend = self.bundle.backend(self.snapshot, "case", self.observation)

    def test_actual_post_action_scale_changes_risk_ranking_and_gamma_zero_limit(self):
        state = (-.5, .02, "initial")
        reference = ControllerConfig(policy="risk_neutral_mpc", horizon=1, cost_penalty=.002)
        neutral = choose(self.backend, state, WorkBudget(64, 4, initial_work=4.25), reference)
        zero = choose(self.backend, state, WorkBudget(64, 4, initial_work=4.25),
                      replace(reference, policy="risk_aware_recursive", gamma=0))
        self.assertEqual(neutral, zero)
        self.assertEqual(neutral.action, "refine_text")
        self.assertEqual(neutral.search_calls, {"prediction": 5, "transition": 4})
        self.assertEqual(neutral.search_work, 6.5)
        for gamma in (1e-8, 1e-12):
            near = choose(self.backend, state, WorkBudget(64, 4, initial_work=4.25),
                          replace(reference, policy="risk_aware_recursive", gamma=gamma))
            self.assertEqual(near.action, neutral.action)
            self.assertAlmostEqual(near.value, neutral.value, places=8)
            self.assertEqual(near.search_calls, neutral.search_calls)
        risk = choose(self.backend, state, WorkBudget(64, 4, initial_work=4.25),
                      replace(reference, policy="risk_aware_recursive", gamma=2))
        self.assertEqual(risk.action, "refine_image")
        self.assertEqual(risk.search_calls, neutral.search_calls)
        self.assertEqual(risk.search_work, neutral.search_work)
        small, probabilities = self.backend.predict((.35, .05, "same-mean"))
        large, same_probabilities = self.backend.predict((.35, .2, "same-mean"))
        self.assertEqual(probabilities, same_probabilities)
        self.assertAlmostEqual(entropic_value(small, probabilities, 0), entropic_value(large, probabilities, 0))
        self.assertGreater(entropic_value(small, probabilities, 2), entropic_value(large, probabilities, 2))

    def test_public_conditioning_uses_mask_hints_pixels_and_rejects_target_or_drift(self):
        before = public_features(self.observation)
        mask, tokens = self.observation.mask.clone(), self.observation.text_tokens.clone()
        mask[..., :28], tokens[:, 3] = 0, 19
        missing = Observation(self.observation.pixels, mask, tokens)
        after = public_features(missing)
        self.assertEqual(before.tolist(), [[1., 1., 0., 0., 0., 0.]])
        self.assertEqual(after.tolist(), [[0., 1., 1., 0., 0., 0.]])
        with self.assertRaises(TypeError):
            public_features(Target(self.observation.pixels, tokens, torch.tensor([[3, 7]])))
        with self.assertRaises(TypeError):
            self.bundle.backend(self.snapshot, "case")
        self.backend.public_summary = tuple(after[0].tolist())
        with self.assertRaisesRegex(RuntimeError, "conditioning changed"):
            self.backend.predict((.35, .05, "initial"))

    def test_checkpoint_file_profile_and_parameter_binding_preserve_legacy_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecast.pt"
            self.bundle.save(path)
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            loaded = ForecastArtifact.load(path, expected_file_sha256=expected)
            state = (.45, .45, "same-state")
            self.assertEqual(loaded.backend(self.snapshot, "case", self.observation).predict(state),
                             self.backend.predict(state))
            record = torch.load(path, weights_only=True)
            record["heads"]["scale_head"]["weight"][1, 0] += .01
            torch.save(record, path)
            with self.assertRaisesRegex(ValueError, "file SHA"):
                ForecastArtifact.load(path, expected_file_sha256=expected)
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                ForecastArtifact.load(path)
            legacy = ForecastBundle(RidgeHead(2, 1), RidgeHead(2, 4), torch.tensor([-.1, .1]),
                                     self.snapshot.fingerprint, ())
            legacy.save(path)
            self.assertIsInstance(ForecastArtifact.load(path), ForecastBundle)
            self.assertEqual(ForecastArtifact.load(path).fingerprint, legacy.fingerprint)


class ConditionalFittingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(611)

    def test_cross_fit_withholds_every_route_of_each_original_pair(self):
        groups = torch.arange(8).repeat(5)
        features = torch.stack((groups.double(), torch.arange(40).double() % 5), 1)
        utilities = torch.sin(groups.double()) + torch.cos(features[:, 1]) * .1
        utilities.clamp_(-1, 1)
        original_fit, seen = RidgeHead.fit, []

        def observing_fit(x, y, ridge=4.):
            seen.append(set(x[:, 0].tolist()))
            return original_fit(x, y, ridge)

        with patch("experiments.multimodal_output_portfolio.v6.distribution_fit.RidgeHead.fit", side_effect=observing_fit):
            _, folds, errors = grouped_error_scale(features, utilities, groups)
        self.assertEqual(len(seen), 5)
        for actual, record in zip(seen, folds):
            self.assertEqual(actual, set(record["training_source_pairs"]))
            self.assertFalse(actual.intersection(record["held_source_pairs"]))
            self.assertEqual(record["held_rows"], 5 * len(record["held_source_pairs"]))
        self.assertGreater(float(errors.mean()), .01)
        self.assertEqual(endpoint_plan(64, 3, 17), endpoint_plan(64, 3, 17))
        self.assertEqual({item["source_pair"] for item in endpoint_plan(64, 3, 17)}, set(range(64)))

    def test_empirical_crps_and_group_scores_do_not_inflate_source_count(self):
        mean, scale, router = RidgeHead(8, 1), RidgeHead(8, 1), RidgeHead(8, 4)
        mean.weight[-1, 0], scale.weight[-1, 0] = .5, .5
        bundle = ConditionalForecastBundle(mean, scale, router, torch.tensor([-1., 1.]), "a" * 64, ())
        scores = _score_rows(bundle, torch.zeros(3, 8), torch.tensor([.5, .5, 1.], dtype=torch.float64))
        self.assertTrue(torch.allclose(scores["crps"], torch.tensor([.25, .25, .25], dtype=torch.float64)))
        grouped = _source_scores(scores, torch.tensor([0, 0, 1]))
        self.assertEqual((grouped["source_pairs"], grouped["rows"]), (2, 3))
        self.assertEqual(grouped["pair_mean"]["mean_absolute_error"], .25)

    def test_forecast_selection_stays_within_each_public_view_and_initialization(self):
        groups, strata = [], []
        for group in range(2):
            for view in ("clean", "missing"):
                for initialization in ("full", "allocation"):
                    groups.extend([group, group])
                    strata.extend([(view, initialization, "initial", 0), (view, initialization, "refine_text", 1)])
        scores = {"forecast_mean": torch.tensor([.35, .45] * 8),
                  "forecast_ce_gamma2": torch.tensor([.34, .27] * 8),
                  "crps": torch.tensor([.1, .4] * 8)}
        result = _selected_diagnostics(scores, torch.tensor(groups), strata, .002)
        for label, action in (("risk_neutral_mean", "refine_text"), ("risk_aware_gamma2", "initial")):
            self.assertEqual((result[label]["source_pairs"], result[label]["rows"]), (2, 8))
            selected = result[label]["selected_endpoints"]
            self.assertEqual(len({(r["source_pair"], r["view"], r["initialization"]) for r in selected}), 8)
            self.assertTrue(all(row["terminal_action"] == action for row in selected))

    def test_full_offline_fit_calibrates_once_per_disjoint_pair_and_supports_opaque_states(self):
        source = SourceSplit(torch.randint(256, (32, 1, 28, 28), dtype=torch.uint8), torch.arange(32) % 10,
                             tuple(f"source:{i}" for i in range(32)), tuple(f"pixels:{i}" for i in range(32)))
        corpus = SourceCorpus({"validation": source}, {"manifest_sha256": "fixture"})
        snapshot = ControlledSnapshot(NeuralSnapshot(NeuralPortfolio(hidden=16)), PlanHead(16))
        observer = Recognizer().eval().requires_grad_(False)
        bundle, evidence = fit_forecast(snapshot, corpus, observer, 17, 8, 4, 4, 1,
                                        distribution="heteroskedastic_terminal_v1")
        ids = [set(evidence["partitions"][name]["source_ids"]) for name in ("fit", "calibration", "dev")]
        self.assertEqual(sum(map(len, ids)), len(set.union(*ids)))
        self.assertEqual([evidence["partitions"][name]["rollout_rows"] for name in
                          ("fit", "calibration", "dev")], [384, 192, 192])
        self.assertEqual(len(bundle.residuals), 4)
        self.assertEqual(bundle.residuals.tolist(), evidence["calibration_support"])
        self.assertEqual(evidence["calibration_probabilities"], [.25] * 4)
        self.assertEqual(evidence["dev_presampled_endpoints"]["source_pairs"], 4)
        self.assertEqual(evidence["dev_all_registered_endpoints"]["source_pairs"], 4)
        for selected in evidence["dev_forecast_selected_endpoints"].values():
            self.assertEqual((selected["source_pairs"], selected["rows"]), (4, 48))
            self.assertTrue(all(row["terminal_action"] in ("initial", "refine_image", "refine_text")
                                for row in selected["selected_endpoints"] if row["initialization"] == "allocation"))
        self.assertEqual(evidence["offline_calls"]["public_summary_case_calls"], 96)
        self.assertEqual(evidence["offline_initial_plan_work_units"], 384)
        self.assertIn([], [candidate["sequence"] for candidate in evidence["fixed_sequence_candidates"]])
        batch = make_batch(corpus, "validation", 1, 101, offset=0)
        state = snapshot.encode(batch.observation, content_control=False)
        backend = bundle.backend(snapshot, "opaque", batch.observation)
        values, probabilities = backend.predict(state)
        self.assertTrue(all(-1 <= value <= 1 for value in values))
        self.assertAlmostEqual(sum(probabilities), 1.)
        decision = choose(backend, state, WorkBudget(64, 4, initial_work=3.25),
                          ControllerConfig(policy="allocation_only", horizon=1))
        self.assertIn(decision.action, (None, "refine_image", "refine_text"))
        bad = list(source.pixel_hashes)
        bad[16] = bad[0]
        with self.assertRaisesRegex(ValueError, "leakage"):
            fit_forecast(snapshot, SourceCorpus({"validation": replace(source, pixel_hashes=tuple(bad))}, corpus.manifest),
                         observer, 17, 8, 4, 4, 1, distribution="heteroskedastic_terminal_v1")


if __name__ == "__main__":
    unittest.main()
