"""Scalar trajectories, private-state isolation and pre-update resource guards."""

import unittest
from unittest.mock import patch

import numpy as np

from cell_learning_models import NumpyCellHead
from cell_microbatch_training import FrozenTrainingBank, MicrobatchCellTrainer
import cell_microbatch_training as implementation

IDENTITY = "a" * 64


class MicrobatchTrainingTests(unittest.TestCase):
    def fixture(self, mode="gated", microbatch=2, **options):
        rng = np.random.default_rng(43)
        matrices = {"a": rng.normal(size=(7, 6)), "b": rng.normal(size=(7, 6))}
        bank = FrozenTrainingBank.build(matrices, {task: [f"{task}-{i}" for i in range(7)] for task in matrices}, IDENTITY)
        heads = [NumpyCellHead(6, 2, mode, rank=2, seed=17+i) for i in range(3)]
        for head in heads: head.feature_identity = IDENTITY
        tasks = ["a", "b", "a"]
        labels = np.array([[0, 0, 1, 0, 1, 1, 0], [1, 1, 1, 0, 0, 0, 1], [1, 0, 0, 1, 0, 1, 1]])
        trainer = MicrobatchCellTrainer(heads, ["x", "y", "z"], tasks, bank, microbatch=microbatch, **options)
        return heads, tasks, labels, bank, trainer

    def train(self, trainer, labels, **options):
        return trainer.train(labels, feature_identity=IDENTITY, generation=1, **options)

    def test_every_mode_matches_real_scalar_private_optimizer_trajectories(self):
        for mode in ("linear", "gated", "residual"):
            with self.subTest(mode=mode):
                heads, tasks, labels, bank, trainer = self.fixture(mode)
                before = [head.digest() for head in heads]
                report = self.train(trainer, labels, steps=5, trace_steps=(1, 2, 5))
                for step, state in trainer.trajectory.items():
                    for i, task in enumerate(tasks):
                        scalar = NumpyCellHead(6, 2, mode, rank=2, seed=17+i)
                        expected = scalar.train(bank.raw_rows(task), labels[i], steps=step)
                        for name in scalar.params:
                            np.testing.assert_allclose(state[name][i], scalar.params[name], atol=1e-11, rtol=1e-11)
                        if step == 5:
                            self.assertAlmostEqual(report["final_loss"][i], expected["final_loss"], places=12)
                self.assertEqual([head.digest() for head in heads], before)
                self.assertEqual(report["private_optimizer_updates"], 15)
                self.assertEqual(report["example_updates"], 105)
                self.assertEqual(report["encoder_forwards"], 0)
                self.assertEqual(len(set(report["trained_parameter_digests"])), 3)

    def test_one_cell_label_parameter_and_clipping_changes_cannot_affect_other_cells(self):
        heads, tasks, labels, bank, _ = self.fixture()
        heads[0].params["W"] *= 10000
        first = MicrobatchCellTrainer(heads, ["x", "y", "z"], tasks, bank, microbatch=2)
        self.train(first, labels, steps=7, l2=.2)
        heads[0].params["W"] += 100
        changed = labels.copy(); changed[0] = 1-changed[0]
        second = MicrobatchCellTrainer(heads, ["x", "y", "z"], tasks, bank, microbatch=2)
        self.train(second, changed, steps=7, l2=.2)
        self.assertGreater(first.report["maximum_unclipped_gradient_norm"][0], 5)
        for name in first._params:
            np.testing.assert_array_equal(first._params[name][1:], second._params[name][1:])
            np.testing.assert_array_equal(first._m[name][1:], second._m[name][1:])
            np.testing.assert_array_equal(first._v[name][1:], second._v[name][1:])

    def test_identity_parameter_memory_and_trace_caps_reject_before_private_updates(self):
        heads, tasks, labels, bank, trainer = self.fixture(max_tensor_bytes=65536)
        before = [trainer.state_digest(i) for i in range(3)]
        for options in ({"feature_identity": "b"*64, "generation": 1}, {"feature_identity": IDENTITY, "generation": 2},
                        {"feature_identity": IDENTITY, "generation": True}, {"feature_identity": IDENTITY, "generation": 1.0}):
            with self.assertRaisesRegex(ValueError, "stale"):
                trainer.train(labels, **options)
        with self.assertRaisesRegex(ValueError, "parameter cap"):
            MicrobatchCellTrainer(heads, ["x", "y", "z"], tasks, bank, max_parameters=1)
        with self.assertRaisesRegex(ValueError, "memory bound"):
            MicrobatchCellTrainer(heads, ["x", "y", "z"], tasks, bank, max_tensor_bytes=4096)
        with self.assertRaisesRegex(ValueError, "trajectory"):
            self.train(trainer, labels, steps=100, trace_steps=tuple(range(1, 101)))
        self.assertEqual(trainer.optimizer_steps, 0)
        self.assertEqual([trainer.state_digest(i) for i in range(3)], before)

    def test_shared_feature_sources_are_frozen_and_conflicts_rejected(self):
        x = np.arange(42, dtype=float).reshape(7, 6)+1
        sources = [str(i) for i in range(7)]
        bank = FrozenTrainingBank.build({"a": x, "b": x.copy()}, {"a": sources, "b": sources}, IDENTITY)
        self.assertEqual(len(bank.source_ids), 7)
        original = bank.raw_rows("a").copy()
        x[:] = 999
        np.testing.assert_array_equal(bank.raw_rows("a"), original)
        with self.assertRaises(ValueError): bank._normalized.setflags(write=True)
        with self.assertRaisesRegex(ValueError, "immutable bounded"):
            FrozenTrainingBank(bank.feature_identity, list(bank.task_ids), bank.source_ids,
                               bank._raw, bank._normalized, bank._indices)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            FrozenTrainingBank.build({"a": original, "b": original+1}, {"a": sources, "b": sources}, IDENTITY)
        with self.assertRaisesRegex(ValueError, "budget"):
            FrozenTrainingBank.build({"a": np.ones((32, 8))}, {"a": [str(i) for i in range(32)]},
                                     IDENTITY, max_tensor_bytes=4096)

    def test_partial_failed_private_update_is_terminal_and_cannot_publish(self):
        heads, _, labels, _, trainer = self.fixture()
        original, calls = implementation.loss_gradients, []
        before = [head.digest() for head in heads]
        def fail_second(*args):
            calls.append(1)
            if len(calls) == 2: raise ValueError("injected gradient failure")
            return original(*args)
        with patch.object(implementation, "loss_gradients", side_effect=fail_second), self.assertRaisesRegex(ValueError, "injected"):
            self.train(trainer, labels, steps=3)
        with self.assertRaisesRegex(ValueError, "one bounded"):
            self.train(trainer, labels, steps=3)
        with self.assertRaisesRegex(ValueError, "cannot be published"):
            trainer.parameters()
        self.assertEqual([head.digest() for head in heads], before)
        self.assertIsNone(trainer.report)


if __name__ == "__main__":
    unittest.main()
