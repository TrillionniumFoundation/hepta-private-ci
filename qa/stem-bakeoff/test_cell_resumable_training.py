"""Synthetic trajectory parity with the unchanged one-shot Adam trainer."""

import hashlib
import unittest
from unittest import mock

import numpy as np

from cell_learning_models import NumpyCellHead
from cell_microbatch_training import FrozenTrainingBank, MicrobatchCellTrainer
from cell_resumable_training import ResumableMicrobatchAdam


def fixture(mode="residual", *, cells=5, microbatch=2, steps=5):
    rng = np.random.default_rng(19)
    x = rng.normal(size=(6, 7))
    bank = FrozenTrainingBank.build({"task": x}, {"task": [f"source-{i}" for i in range(6)]}, "a"*64)
    heads = [NumpyCellHead(7, 2, mode, rank=4, seed=100+i) for i in range(cells)]
    for head in heads:
        head.feature_identity = bank.feature_identity
    ids, tasks = [f"cell-{i}" for i in range(cells)], ["task"]*cells
    labels = np.tile(np.arange(6)%2, (cells, 1))
    sources = [hashlib.sha256(f"source-record-{i}".encode()).hexdigest() for i in range(6)]
    args = (heads, ids, tasks, bank, labels)
    options = dict(source_record_digests=sources, steps=steps, microbatch=microbatch)
    return args, options


class ResumableTrainingTests(unittest.TestCase):
    def test_every_step_matches_frozen_trainer_all_modes(self):
        for mode in ("linear", "gated", "residual"):
            with self.subTest(mode=mode):
                args, options = fixture(mode)
                heads, ids, tasks, bank, labels = args
                old = MicrobatchCellTrainer(heads, ids, tasks, bank, microbatch=2)
                old.train(labels, feature_identity=bank.feature_identity, generation=1,
                    steps=5, trace_steps=tuple(range(1, 6)))
                fresh = ResumableMicrobatchAdam(*args, **options)
                for cursor in range(fresh.total_block_steps):
                    group, step = divmod(cursor, 5)
                    fresh.advance(1, expected_plan_sha256=fresh.plan_sha256)
                    _, arrays = fresh.snapshot()
                    begin, end = group*2, min(group*2+2, len(heads))
                    for name in old.parameters():
                        np.testing.assert_array_equal(arrays["p_"+name][begin:end], old.trajectory[step+1][name][begin:end])
                report = fresh.progress()
                self.assertTrue(report["complete"])
                for name in ("initial_loss", "final_loss", "maximum_unclipped_gradient_norm"):
                    self.assertEqual(report[name], old.report[name])
                for name in old._m:
                    np.testing.assert_array_equal(arrays["m_"+name], old._m[name])
                    np.testing.assert_array_equal(arrays["v_"+name], old._v[name])
                self.assertEqual(report["private_optimizer_updates"], 25)

    def test_pause_schedule_preserves_chain_and_inputs(self):
        args, options = fixture()
        full, split = (ResumableMicrobatchAdam(*args, **options) for _ in range(2))
        full.advance(expected_plan_sha256=full.plan_sha256)
        for amount in (1, 3, 1, 6, 4):
            split.advance(amount, expected_plan_sha256=split.plan_sha256)
        self.assertEqual(full.progress(), split.progress())
        for key, value in full.snapshot()[1].items():
            np.testing.assert_array_equal(value, split.snapshot()[1][key])
            self.assertFalse(value.flags.writeable)
        self.assertEqual(full.plan, split.plan)

    def test_binding_includes_labels_source_records_and_cell_order(self):
        args, options = fixture()
        base = ResumableMicrobatchAdam(*args, **options)
        changed = list(args)
        changed[-1] = 1-args[-1]
        labels = ResumableMicrobatchAdam(*changed, **options)
        altered = dict(options, source_record_digests=["f"*64, *options["source_record_digests"][1:]])
        sources = ResumableMicrobatchAdam(*args, **altered)
        changed = list(args)
        changed[1] = list(reversed(changed[1]))
        order = ResumableMicrobatchAdam(*changed, **options)
        self.assertEqual(len({r.input_sha256 for r in (base, labels, sources, order)}), 4)
        with self.assertRaises(ValueError):
            base.advance(expected_plan_sha256=labels.plan_sha256)
        self.assertEqual(base.progress()["private_optimizer_updates"], 0)

    def test_invalid_budget_labels_and_steps_do_not_train(self):
        args, options = fixture()
        for changed in (dict(options, steps=0), dict(options, learning_rate=float("nan")),
                        dict(options, source_record_digests=["source"]*6), dict(options, max_tensor_bytes=4096)):
            with self.subTest(options=changed), self.assertRaises(ValueError):
                ResumableMicrobatchAdam(*args, **changed)
        fresh = ResumableMicrobatchAdam(*args, **options)
        with self.assertRaises(ValueError):
            fresh.advance(fresh.total_block_steps+1, expected_plan_sha256=fresh.plan_sha256)

    def test_failed_update_is_terminal(self):
        args, options = fixture()
        fresh = ResumableMicrobatchAdam(*args, **options)
        with mock.patch("cell_resumable_training.loss_gradients", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                fresh.advance(1, expected_plan_sha256=fresh.plan_sha256)
        with self.assertRaises(ValueError):
            fresh.snapshot()
        with self.assertRaises(ValueError):
            fresh.advance(expected_plan_sha256=fresh.plan_sha256)

    def test_base_exception_after_partial_parameter_update_is_terminal(self):
        for interruption in (KeyboardInterrupt, SystemExit):
            with self.subTest(interruption=interruption.__name__):
                args, options = fixture()
                fresh = ResumableMicrobatchAdam(*args, **options)
                before = fresh._core._params["W"].copy()
                class InterruptedMoment(np.ndarray):
                    def __getitem__(self, key):
                        raise interruption("injected after W update, before b update")
                fresh._core._m["b"] = fresh._core._m["b"].view(InterruptedMoment)
                with self.assertRaises(interruption):
                    fresh.advance(1, expected_plan_sha256=fresh.plan_sha256)
                self.assertFalse(np.array_equal(before, fresh._core._params["W"]))
                self.assertEqual(fresh.progress()["cursor"], 0)
                self.assertTrue(fresh.progress()["partial_failed_step_work_unknown"])
                with self.assertRaises(ValueError): fresh.snapshot()
                with self.assertRaises(ValueError):
                    fresh.advance(expected_plan_sha256=fresh.plan_sha256)


if __name__ == "__main__":
    unittest.main()
