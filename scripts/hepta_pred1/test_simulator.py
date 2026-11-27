"""Regression tests for causal histories and the evaluator-only Bayes oracle."""

import itertools
import unittest

import numpy as np

from .simulator import (
    PublicHistory,
    SensorEvent,
    bayes_belief,
    encode_history,
    coarsen_label,
    generate_dataset,
    joint_table,
    transition,
)


class SimulatorTests(unittest.TestCase):
    def test_future_readback_does_not_rewrite_features_or_belief(self):
        actions = (0, 1, 0, 2)
        observed = SensorEvent(0, 1, 0, 1)
        a = PublicHistory(actions, (observed, SensorEvent(2, 5, 1, 0)))
        b = PublicHistory(actions, (observed, SensorEvent(2, 5, 1, 1)))
        np.testing.assert_array_equal(encode_history(a, 3), encode_history(b, 3))
        np.testing.assert_array_equal(bayes_belief(a, 3), bayes_belief(b, 3))

    def test_delayed_bayes_filter_matches_full_path_enumeration(self):
        actions = (0, 1, 2, 0)
        events = (
            SensorEvent(0, 1, 0, 1),
            SensorEvent(1, 3, 1, 0),
            SensorEvent(3, 3, 1, 1),
        )
        history = PublicHistory(actions, events)
        enumerated = np.zeros(4)
        for path in itertools.product(range(4), repeat=4):
            probability = 0.25
            for t in range(1, 4):
                probability *= transition(actions[t])[path[t - 1], path[t]]
            for event in events:
                bit = (
                    path[event.measured_at] // 2
                    if event.sensor == 0
                    else path[event.measured_at] % 2
                )
                accuracy = 0.92 if event.sensor == 0 else 0.84
                probability *= accuracy if bit == event.value else 1 - accuracy
            enumerated[path[-1]] += probability
        enumerated /= enumerated.sum()
        np.testing.assert_allclose(bayes_belief(history, 3), enumerated, atol=1e-14)

    def test_action_and_horizon_change_normalized_distribution(self):
        table = joint_table()
        np.testing.assert_allclose(table.sum(axis=-1), 1)
        self.assertTrue((table >= 0).all())
        self.assertGreater(np.max(abs(table[:, 0] - table[:, 1])), 0.01)
        self.assertGreater(np.max(abs(table[0] - table[2])), 0.01)

    def test_dataset_replay_groups_and_observation_coarsening(self):
        train = generate_dataset(128, 71, "train", length=4)
        replay = generate_dataset(128, 71, "train", length=4)
        dev = generate_dataset(32, 71, "dev", length=4)
        self.assertEqual(train.fingerprint(), replay.fingerprint())
        self.assertFalse(set(train.groups) & set(dev.groups))
        self.assertTrue(
            train.allowed[np.arange(128), train.evaluator.sampled_training_class].all()
        )
        self.assertTrue((train.allowed.sum(axis=1) == 32).any())
        self.assertTrue((train.prefix_cost > 0).all())
        self.assertTrue(train.legal_actions.any(axis=1).all())
        query_actions = train.query[:, :4].argmax(axis=1)
        self.assertTrue(train.legal_actions[np.arange(128), query_actions].all())
        self.assertEqual(train.x.shape, (128, 4, 16))

    def test_evidence_clock_is_after_variable_history_and_preparation(self):
        for launch_at in (4, 21, 261):
            for seed in range(32):
                evidence = coarsen_label(
                    seed, np.random.default_rng(seed), "sim:test", launch_at
                )
                self.assertGreater(evidence.observed_at, launch_at)


if __name__ == "__main__":
    unittest.main()
