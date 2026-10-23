import unittest
from unittest.mock import patch

import numpy as np

from data import caption, dataset, decoded_metrics, outcome_table, parse_caption, templates
from model import JointModel
import data


def reference_reward(observations):
    text, image, _, distances = observations
    target = np.arange(12)[:, None, None]
    correct_text = text[None, :, None] == target
    correct_image = image[None, None, :] == target
    quality = np.maximum(0.0, 1.0 - 4 * distances.T[:, None, :])
    return (0.3 * correct_text + 0.3 * correct_image
            + 0.3 * (correct_text & correct_image) + 0.1 * quality
            - 0.35 * (text[:, None] != image[None, :])[None, :, :])


def reference_metrics(observations, p, q, labels):
    text, image, _, distances = observations
    target = np.asarray(labels)
    pt = p[np.arange(len(p)), target]
    qi = np.sum(q * (image[None, :] == target[:, None]), axis=1)
    agreement = (text[:, None] == image[None, :]).astype(float)
    greedy_text, greedy_image = text[p.argmax(axis=1)], image[q.argmax(axis=1)]
    return {"joint_success": pt * qi,
            "greedy_joint_success": ((greedy_text == target) & (greedy_image == target)).astype(float),
            "consistency": np.einsum("ni,ij,nj->n", p, agreement, q),
            "pixel_mse": np.sum(q * distances.T[target], axis=1)}


class DataTests(unittest.TestCase):
    def test_source_groups_and_input_bytes_are_disjoint(self):
        # Do not open the sealed test split during development.
        a, b = dataset("train", 1), dataset("validation", 1)
        self.assertFalse(set(a["groups"]) & set(b["groups"]))
        self.assertFalse(set(a["input_hashes"]) & set(b["input_hashes"]))
        self.assertEqual(set(a["labels"]), set(range(12)))
        self.assertEqual(parse_caption(caption(7)), 7)

    def test_observer_uses_actual_pixels(self):
        model = JointModel(202, 12, 192)
        model.fit_decoder(templates())
        p = np.eye(12)
        before = decoded_metrics(model, p, p, np.arange(12))
        reward_before = outcome_table(model)[np.arange(12), np.arange(12), np.arange(12)]
        model.params["decoder"][:] = 0
        model.params["decoder_bias"][:] = 0
        after = decoded_metrics(model, p, p, np.arange(12))
        reward_after = outcome_table(model)[np.arange(12), np.arange(12), np.arange(12)]
        self.assertGreater(before["joint_success"].mean(), after["joint_success"].mean() + 0.5)
        self.assertGreater(reward_before.mean(), reward_after.mean() + 0.3)


class DecodedObserverTests(unittest.TestCase):
    """Hand tensors only; no scene dataset or decoder training."""

    def setUp(self):
        self.model = JointModel(202, 12, 192, hidden=4, seed=1701)
        rng = np.random.default_rng(2108)
        self.model.params["decoder"] = np.where(data.templates() > 0, 8.0, -8.0) + rng.normal(0, .2, (12, 192))
        self.p, self.q = (rng.dirichlet(np.ones(12), 7) for _ in range(2))
        self.labels = np.array([0, 3, 7, 11, 0, 5, 2])

    def test_single_semantic_helpers_and_legacy_wrappers_are_bitwise_equal(self):
        observations = data.decoded_observations(self.model)
        expected_reward = reference_reward(observations)
        expected_metrics = reference_metrics(observations, self.p, self.q, self.labels)
        observer = data.prepare_decoded_observer(self.model)
        for actual in (data.outcome_table(self.model), observer.reward):
            np.testing.assert_array_equal(actual, expected_reward)
        for actual in (data.decoded_metrics(self.model, self.p, self.q, self.labels),
                       data.metrics_from_observations(observer.observations, self.p, self.q, self.labels)):
            self.assertEqual(set(actual), set(expected_metrics))
            for key, expected in expected_metrics.items():
                np.testing.assert_array_equal(actual[key], expected)

    def test_metrics_only_wrapper_observes_once_without_unused_reward(self):
        with patch.object(data, "outcome_from_observations", side_effect=AssertionError("unused reward")), \
             patch.object(data, "decoded_observations", wraps=data.decoded_observations) as observe:
            data.decoded_metrics(self.model, self.p, self.q, self.labels)
        self.assertEqual(observe.call_count, 1)

    def test_local_snapshot_is_immutable_and_changed_decoder_is_freshly_observed(self):
        original = data.prepare_decoded_observer(self.model)
        before = original.reward.copy()
        for array in (*original.observations, original.reward):
            self.assertFalse(array.flags.writeable)
            with self.assertRaises(ValueError):
                array.flat[0] = 0
        self.model.params["decoder"][0, :] += 3
        with patch.object(data, "decoded_observations", wraps=data.decoded_observations) as observe:
            changed = data.prepare_decoded_observer(self.model)
            wrapper = data.outcome_table(self.model)
        self.assertEqual(observe.call_count, 2)
        np.testing.assert_array_equal(original.reward, before)
        np.testing.assert_array_equal(changed.reward, wrapper)
        self.assertFalse(np.array_equal(changed.reward, original.reward))

    def test_corrupt_decoder_has_independently_observed_exact_semantics(self):
        normal = data.prepare_decoded_observer(self.model)
        corrupted = self.model.clone()
        corrupted.params["decoder"] = np.roll(corrupted.params["decoder"], 1, axis=0)
        with patch.object(corrupted, "decode_images", wraps=corrupted.decode_images) as decode:
            observed = data.prepare_decoded_observer(corrupted)
        self.assertEqual(decode.call_count, 1)
        np.testing.assert_array_equal(observed.reward, data.outcome_table(corrupted))
        self.assertFalse(np.array_equal(normal.reward, observed.reward))


if __name__ == "__main__":
    unittest.main()
