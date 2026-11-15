import unittest

import torch

from execution_meter import WorkLedger
from group_critic import fit_critic, row_features
from paired_execution import PHASES


def rows(split, prefix, count=12):
    return [dict(features=[float(i % 2), i / count], stop_success=bool(i % 2),
                 continue_success=not bool(i % 2), source_group=prefix + str(i),
                 split=split, observed_at_ns=9) for i in range(count)]


class CriticTests(unittest.TestCase):
    def fit(self, **kwargs):
        return fit_critic(rows("validation_fit", "fit"),
                          rows("validation_calibration", "cal"), cutoff_ns=10, **kwargs)

    def test_real_training_is_deterministic_and_frozen(self):
        critic, again = self.fit(steps=100), self.fit(steps=100)
        self.assertEqual(critic.params_sha256, again.params_sha256)
        self.assertNotEqual(critic.params_sha256, critic.metadata["initial_params_sha256"])
        self.assertGreater(critic.metadata["training_cpu_ns"], 0)
        before = critic.params_sha256
        critic.predict([0., .2])
        critic.assert_frozen()
        self.assertEqual(critic.params_sha256, before)
        self.assertTrue(all(not p.requires_grad for p in critic.model.parameters()))

    def test_bounds_are_exact_empirical_residual_expansions(self):
        critic = self.fit()
        p = critic.predict([0., .2])
        a, b = critic.metadata["empirical_max_absolute_residual"]
        self.assertEqual(p["stop_upper"], min(1., p["stop_probability"] + a))
        self.assertEqual(p["continue_lower"], max(0., p["continue_probability"] - b))
        self.assertFalse(critic.metadata["future_support_guaranteed"])
        metadata = critic.metadata
        metadata["empirical_max_absolute_residual"][0] = -1
        self.assertGreaterEqual(critic.metadata["empirical_max_absolute_residual"][0], 0)

    def test_rejects_overlap_future_and_nonvalidation(self):
        train = rows("validation_fit", "same")
        calibration = rows("validation_calibration", "same")
        with self.assertRaises(ValueError):
            fit_critic(train, calibration, cutoff_ns=10)
        for change in ({"split": "test"}, {"observed_at_ns": 11},
                       {"stop_success": 1}, {"features": [float("nan")]}):
            invalid = rows("validation_fit", "fit")
            invalid[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                fit_critic(invalid, rows("validation_calibration", "cal"), cutoff_ns=10)

    def test_weight_mutation_or_training_mode_is_refused(self):
        critic = self.fit()
        critic.model.train()
        with self.assertRaises(ValueError):
            critic.predict([0., .2])
        critic.model.eval()
        with torch.no_grad():
            critic.model.bias.add_(1.)
        with self.assertRaises(ValueError):
            critic.predict([0., .2])

    def test_observable_features_and_prediction_fit_strict_meter(self):
        critic = self.fit()
        policy = dict(schema="hepta.execution-meter-policy.v1", mode="strict",
                      wall_time_ns=10**10, max_process_rss_bytes=None,
                      rapl_zone=None, rapl_max_power_watts=None)
        ledger = WorkLedger(policy, dict.fromkeys(PHASES, 100000))
        with ledger.scope("search", "value"):
            features = row_features(torch.ones(1, 8), torch.tensor([[1., 2., 3.]]), 1, 4)
            self.assertEqual(len(features), 6)
            critic.predict([0., .2])
        with ledger.scope("train", "value"):
            self.fit(steps=2)
        with self.assertRaises(ValueError):
            row_features(torch.ones(2, 8), torch.ones(2, 3), 1, 4)
        self.assertEqual(ledger.report()["unknown_operators"], {})
        with self.assertRaises(ValueError):
            critic.predict([0.])


if __name__ == "__main__":
    unittest.main()
