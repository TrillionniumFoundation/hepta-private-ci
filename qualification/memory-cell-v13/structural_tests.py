"""Independent state, capacity, sparse invocation, and train-boundary checks."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from adapter import Adapter
import experiment
from structural import SparseExperts, balanced_partition, inherit_subset, parameter_count, widen


class StructuralTests(unittest.TestCase):
    def setUp(self):
        self.X = np.random.default_rng(91).normal(size=(24, 7))
        self.y = np.repeat(np.arange(6), 4)
        self.parent = Adapter(7, 6, 2, 87, encoder_hash="synthetic-boundary-test", source_version="v1")
        self.parent.train(self.X, self.y, steps=7, batch_size=5, data_id="train", source_version="v1")

    def test_subset_preserves_adam_rng_sampler_and_selected_logits(self):
        before = self.parent.state_hash()
        labels = [5, 1, 3]
        child = inherit_subset(self.parent, labels)
        self.assertEqual(child.config["num_classes"], len(labels))
        for group in ("params", "m", "v"):
            for key in ("A", "B"):
                np.testing.assert_array_equal(getattr(child, group)[key], getattr(self.parent, group)[key])
            for key in ("W", "b"):
                expected = getattr(self.parent, group)[key][..., labels]
                np.testing.assert_array_equal(getattr(child, group)[key], expected)
        self.assertEqual(child.rng.bit_generator.state, self.parent.rng.bit_generator.state)
        self.assertEqual(child.step, self.parent.step)
        self.assertEqual(child.optimizer, self.parent.optimizer)
        for key in child.sampler:
            np.testing.assert_equal(child.sampler[key], self.parent.sampler[key])
        probabilities = self.parent.predict_proba(self.X)[:, labels]
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        np.testing.assert_allclose(child.predict_proba(self.X), probabilities, rtol=1e-14, atol=1e-15)
        child.params["A"][0, 0] += 1
        child.m["B"][0, 0] += 1
        child.sampler["order"][0] = 123
        self.assertEqual(self.parent.state_hash(), before)

    def test_widen_preserves_function_and_matches_aggregate_child_capacity(self):
        expanded = widen(self.parent, 3)
        children = [inherit_subset(self.parent, part) for part in ([0, 1], [2, 3], [4, 5])]
        self.assertEqual(parameter_count(expanded), sum(parameter_count(child) for child in children))
        np.testing.assert_allclose(expanded.features(self.X), self.parent.features(self.X), rtol=1e-14, atol=1e-15)
        np.testing.assert_allclose(expanded.predict_proba(self.X), self.parent.predict_proba(self.X), rtol=1e-14, atol=1e-15)
        rank = self.parent.config["rank"]
        for group in ("params", "m", "v"):
            np.testing.assert_array_equal(getattr(expanded, group)["A"][:, :rank], getattr(self.parent, group)["A"])
            np.testing.assert_array_equal(getattr(expanded, group)["B"][:rank], getattr(self.parent, group)["B"])
            np.testing.assert_array_equal(getattr(expanded, group)["B"][rank:], 0)
        self.assertEqual(expanded.rng.bit_generator.state, self.parent.rng.bit_generator.state)
        self.assertEqual(expanded.step, self.parent.step)
        for key in expanded.sampler:
            np.testing.assert_equal(expanded.sampler[key], self.parent.sampler[key])
        expanded.train(self.X, self.y, steps=1, data_id="train", source_version="v1")
        self.assertTrue(np.any(expanded.params["B"][rank:] != 0))

    def test_sparse_router_invokes_only_selected_rows_and_experts(self):
        model = SparseExperts(self.parent, [[0, 1], [2, 3], [4, 5]], top_k=2)
        model.router = np.zeros((8, 3))
        model.router[0] = [3, 2, 0]
        model.router[1] = [0, 2, 3]
        inputs = np.eye(7)[:2]
        calls = {}
        def recorder(group):
            def predict(X):
                calls[group] = X.copy()
                return np.full((len(X), 2), 0.5)
            return predict
        for group, expert in enumerate(model.experts):
            expert.predict_proba = recorder(group)
        probabilities = model.predict_proba(inputs)
        np.testing.assert_array_equal(calls[0], inputs[:1])
        np.testing.assert_array_equal(calls[1], inputs)
        np.testing.assert_array_equal(calls[2], inputs[1:])
        self.assertEqual(model.stats, dict(requests=2, expert_example_invocations=4, batch_calls=3))
        np.testing.assert_array_equal(probabilities[0, [4, 5]], 0)
        np.testing.assert_array_equal(probabilities[1, [0, 1]], 0)
        np.testing.assert_allclose(probabilities.sum(axis=1), 1)

    def test_partition_covers_training_classes_without_mutating_inputs(self):
        X, y = self.X.copy(), self.y.copy()
        with mock.patch("builtins.open", side_effect=AssertionError("partition attempted external read")):
            partition = balanced_partition(X, y, groups=3)
        self.assertEqual(sorted(sum(partition, [])), list(range(6)))
        self.assertEqual([len(group) for group in partition], [2, 2, 2])
        np.testing.assert_array_equal(X, self.X)
        np.testing.assert_array_equal(y, self.y)
        self.assertEqual(partition, balanced_partition(X, y, groups=3))

    def test_experiment_partition_receives_only_train_matrix(self):
        rng = np.random.default_rng(47)
        X = rng.normal(size=(24, 384)).astype(np.float32)
        y = np.repeat(np.arange(12), 2)
        rows = [dict(text=f"synthetic training {i}", label=int(label), split="train") for i, label in enumerate(y)]
        datasets = {"train": (X, y, rows), "calibration": (np.full((2, 384), 999), np.zeros(2), [{}, {}]), "test": (np.full((2, 384), -999), np.zeros(2), [{}, {}])}
        protocol = {"training": dict(rank=2, initial_steps=1, batch_size=4, learning_rate=0.01), "structure": dict(groups=3, top_k=2, expert_steps=1, continue_and_widen_steps=3)}
        manifest = dict(source_version="synthetic-source", encoder_hash="synthetic-encoder")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(experiment, "balanced_partition", wraps=balanced_partition) as partition, mock.patch.object(experiment, "evaluate", return_value={"correct": 0, "evaluated": 0}):
            experiment.single_and_structure(73, Path(temporary), datasets, manifest, protocol)
        self.assertEqual(partition.call_count, 1)
        np.testing.assert_array_equal(partition.call_args.args[0], X)
        np.testing.assert_array_equal(partition.call_args.args[1], y)

    def test_invalid_sparse_routes_and_partitions_are_rejected(self):
        for top_k in (0, -1, 4):
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                SparseExperts(self.parent, [[0, 1], [2, 3], [4, 5]], top_k=top_k)
        for partition in ([[], list(range(6))], [[0, 1], [1, 2, 3, 4, 5]], [[0, 1], [2, 3, 4]]):
            with self.subTest(partition=partition), self.assertRaises(ValueError):
                SparseExperts(self.parent, partition, top_k=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
