"""Forecast fitting boundaries, calibrated support and checkpoint verification."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import torch

from .control import ControllerConfig, WorkBudget, choose
from .data import SourceCorpus, SourceSplit, make_batch
from .forecast import ForecastBundle, RidgeHead, _calibration_profiles, fit_forecast
from .neural import NeuralPortfolio, NeuralSnapshot
from .observer import Recognizer


class ForecastTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(71)
        count = 24
        self.source = SourceSplit(torch.randint(256, (count, 1, 28, 28), dtype=torch.uint8),
                                  torch.arange(count) % 10,
                                  tuple(f"fixture:{i}" for i in range(count)),
                                  tuple(f"pixel:{i}" for i in range(count)))
        self.corpus = SourceCorpus({"validation": self.source}, {"manifest_sha256": "fixture"})
        self.snapshot = NeuralSnapshot(NeuralPortfolio(hidden=16))
        self.observer = Recognizer().eval().requires_grad_(False)

    def test_ridge_learns_public_mapping_and_rejects_nonfinite_data(self):
        x = torch.tensor([[0., 0.], [0., 1.], [1., 0.], [1., 1.]])
        y = 2 * x[:, 0] - x[:, 1] + 0.4
        head = RidgeHead.fit(x, y, ridge=1e-6)
        self.assertTrue(torch.allclose(head(x).squeeze(1), y.double(), atol=1e-5))
        with self.assertRaises(ValueError):
            RidgeHead.fit(x * float("nan"), y)

    def test_offline_fit_partition_counts_backend_and_roundtrip(self):
        bundle, evidence = fit_forecast(self.snapshot, self.corpus, self.observer, 3,
                                        fit_pairs=4, calibration_pairs=4, dev_pairs=4, horizon=1)
        partitions = evidence["partitions"]
        groups = [set(partitions[name]["source_ids"]) for name in ("fit", "calibration", "dev")]
        self.assertEqual(sum(map(len, groups)), len(set.union(*groups)))
        self.assertEqual([partitions[n]["pair_offset"] for n in ("fit", "calibration", "dev")], [0, 4, 8])
        self.assertEqual(evidence["residual_scenarios"], 32)
        self.assertEqual(partitions["calibration"]["rollout_rows_by_initialization"], {"full": 20, "allocation": 12})
        self.assertFalse(any(row["active"] for row in evidence["conditional_profiles"].values()))
        self.assertEqual(evidence["offline_calls"], {
            "encode_batch_calls": 6, "encode_case_calls": 24,
            "transition_batch_calls": 22, "transition_case_calls": 88,
            "decode_batch_calls": 29, "decode_case_calls": 116,
            "observer_batch_calls": 29, "observer_case_calls": 116,
        })
        self.assertIn([], [row["sequence"] for row in evidence["fixed_sequence_candidates"]])
        best = max(evidence["fixed_sequence_candidates"], key=lambda row: row["selection_score"])
        self.assertEqual(bundle.static_sequence, tuple(best["sequence"]))
        self.assertTrue(all(abs(row["selection_score"] - (row["mean_external_utility"] - .002 * len(row["sequence"]))) < 1e-12
                            for row in evidence["fixed_sequence_candidates"]))
        batch = make_batch(self.corpus, "validation", 1, 99, offset=0)
        state = self.snapshot.encode(batch.observation, noise_seed=99)
        backend = bundle.backend(self.snapshot, "public-episode")
        values, probabilities = backend.predict(state)
        self.assertTrue(all(-1 <= v <= 1 for v in values))
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertEqual(set(vars(backend)), {"snapshot", "forecast", "context_id"})
        before = backend.state_key(state)
        result = choose(backend, state, WorkBudget(100, 2), ControllerConfig(horizon=1))
        self.assertTrue(result.complete)
        self.assertEqual(before, backend.state_key(state))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecast.pt"
            bundle.save(path)
            restored = ForecastBundle.load(path)
            self.assertEqual(restored.fingerprint, bundle.fingerprint)
            self.assertEqual(restored.backend(self.snapshot, "public-episode").predict(state), (values, probabilities))
            record = torch.load(path, weights_only=True)
            record["residuals"][0] += .01
            torch.save(record, path)
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                ForecastBundle.load(path)

    def test_duplicate_source_pixels_and_wrong_snapshot_rejected(self):
        bad_hashes = list(self.source.pixel_hashes)
        bad_hashes[8] = bad_hashes[0]
        corpus = SourceCorpus({"validation": replace(self.source, pixel_hashes=tuple(bad_hashes))},
                              self.corpus.manifest)
        with self.assertRaisesRegex(ValueError, "leakage"):
            fit_forecast(self.snapshot, corpus, self.observer, 3, 4, 4, 4, 1)
        utility, actions = RidgeHead(64, 1), RidgeHead(64, 4)
        bundle = ForecastBundle(utility, actions, torch.zeros(2), "foreign-snapshot", ())
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            bundle.backend(self.snapshot, "episode")
        bundle.utility_head.weight[0, 0] = 1
        with self.assertRaisesRegex(RuntimeError, "changed"):
            bundle.verify_integrity()

    def test_conditional_support_counts_groups_and_balances_their_mass(self):
        groups = torch.arange(40).repeat(3)
        means = torch.full((120,), -.5, dtype=torch.float64)
        means[80:] = .5
        means[40:50] = .5
        utilities = means + torch.linspace(-.2, .2, 120, dtype=torch.float64)
        profiles, evidence = _calibration_profiles(means, utilities, groups, 0)
        self.assertEqual(set(profiles), {"low", "high"})
        for name, mask in (("low", means < 0), ("high", means >= 0)):
            mass = torch.zeros(40, dtype=torch.float64).scatter_add_(0, groups[mask], profiles[name]["probabilities"])
            self.assertTrue(torch.allclose(mass, torch.full_like(mass, 1 / 40)))
            self.assertGreaterEqual(evidence[name]["empirical_calibration_90pct_coverage"], .89)
        sparse, evidence = _calibration_profiles(means, utilities, groups % 10, 0)
        self.assertEqual(sparse, {})
        self.assertEqual(evidence["low"]["distinct_source_pairs"], 10)
        self.assertGreater(evidence["low"]["rows"], 30)

    def test_opaque_controlled_snapshot_uses_same_backend_protocol(self):
        from .plan_training import ControlledSnapshot, PlanHead

        snapshot = ControlledSnapshot(self.snapshot, PlanHead(16))
        bundle, evidence = fit_forecast(snapshot, self.corpus, self.observer, 3, 4, 4, 4, 1)
        batch = make_batch(self.corpus, "validation", 1, 91, offset=0)
        state = snapshot.encode(batch.observation)
        backend = bundle.backend(snapshot, "opaque-episode")
        self.assertEqual(backend.identity(state), backend.identity(backend.transition(state, "couple")))
        self.assertTrue(choose(backend, state, WorkBudget(100, 2), ControllerConfig(horizon=1)).complete)
        self.assertEqual(evidence["offline_initial_plan_work_units"], 48)
        allocation = snapshot.encode(batch.observation, content_control=False)
        self.assertEqual(allocation.plan_index, -1)
        result = choose(backend, allocation, WorkBudget(100, 2), ControllerConfig(policy="allocation_only", horizon=1))
        self.assertIn(result.action, (None, "refine_image", "refine_text"))
        self.assertTrue(result.complete)


if __name__ == "__main__":
    unittest.main()
