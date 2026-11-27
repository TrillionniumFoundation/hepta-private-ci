"""Causal specification and paired-counterfactual checks, without training."""

import unittest

import numpy as np

from qualification.hcsn.content_tasks import (
    CONDITIONS, IGNORE_TARGET, NOISE, QUERY, SILENCE, WRITE,
    make_content_batch, oracle_targets,
)


class ContentTaskTests(unittest.TestCase):
    def test_all_conditions_match_independent_prefix_interpreter(self):
        for seed in range(3):
            for condition in CONDITIONS:
                with self.subTest(seed=seed, condition=condition):
                    batch = make_content_batch(seed, 7, keys=7, values=9, queries=4,
                                               delay_steps=11, condition=condition)
                    np.testing.assert_array_equal(batch.targets, oracle_targets(batch.x, keys=7, values=9))
                    np.testing.assert_array_equal(batch.query_mask, batch.targets != IGNORE_TARGET)
                    np.testing.assert_array_equal(batch.query_mask.sum(1), np.full(7, 4))
                    self.assertFalse(batch.x[batch.query_mask, 11:].any())

    def test_query_swap_changes_only_query_order_and_permuted_targets(self):
        base = make_content_batch(43, 12)
        swap = make_content_batch(43, 12, condition="query_swap")
        start = int(np.flatnonzero(base.query_mask[0])[0])
        np.testing.assert_array_equal(base.x[:, :start], swap.x[:, :start])
        np.testing.assert_array_equal(swap.x[:, start:], np.roll(base.x[:, start:], 1, axis=1))
        np.testing.assert_array_equal(swap.targets[:, start:], np.roll(base.targets[:, start:], 1, axis=1))
        np.testing.assert_array_equal(base.dt, swap.dt)
        self.assertFalse(np.array_equal(base.x, swap.x))

    def test_overwrite_changes_exactly_one_answer_per_world(self):
        base = make_content_batch(71, 23, values=3)
        updated = make_content_batch(71, 23, values=3, condition="overwrite")
        np.testing.assert_array_equal((base.targets != updated.targets).sum(1), np.ones(23))
        np.testing.assert_array_equal((base.x != updated.x).any(-1).sum(1), np.ones(23))
        np.testing.assert_array_equal(base.x[:, -4:], updated.x[:, -4:])
        np.testing.assert_array_equal(base.dt, updated.dt)
        np.testing.assert_array_equal(updated.targets, oracle_targets(updated.x, keys=8, values=3))

    def test_interference_and_silence_have_equal_physical_horizon(self):
        silent = make_content_batch(7, 9, condition="silence", delay_steps=128)
        noisy = make_content_batch(7, 9, condition="interference", delay_steps=128)
        np.testing.assert_array_equal(silent.targets, noisy.targets)
        np.testing.assert_array_equal(silent.dt, noisy.dt)
        np.testing.assert_array_equal(silent.dt.sum(1), noisy.dt.sum(1))
        self.assertGreater(int(noisy.x[..., WRITE].sum()), int(silent.x[..., WRITE].sum()))
        self.assertGreater(int(noisy.x[..., NOISE].sum()), 0)
        self.assertFalse(np.array_equal(silent.x, noisy.x))
        np.testing.assert_array_equal(noisy.targets, oracle_targets(noisy.x, keys=8, values=16))

    def test_unknown_is_unwritten_key_and_never_a_payload(self):
        base = make_content_batch(8, 15)
        unknown = make_content_batch(8, 15, condition="unknown")
        np.testing.assert_array_equal(base.x[:, :-1], unknown.x[:, :-1])
        np.testing.assert_array_equal(unknown.targets[:, -1], np.full(15, 16))
        for row in unknown.x:
            requested = int(row[-1, 4:12].argmax())
            writes = row[row[:, WRITE] == 1]
            self.assertFalse(writes[:, 4 + requested].any())
        self.assertEqual(unknown.input_contract["classes"], 17)

    def test_input_boundary_excludes_supervision_and_is_reproducible(self):
        first, second = make_content_batch(101, 5), make_content_batch(101, 5)
        for name in ("x", "dt", "targets", "query_mask"):
            np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
        self.assertEqual(set(first.model_inputs()), {"x", "dt"})
        self.assertFalse(np.shares_memory(first.x, first.targets))
        self.assertFalse(np.shares_memory(first.x, first.query_mask))
        first.targets[:] = 123456
        np.testing.assert_array_equal(first.x, second.x)
        np.testing.assert_array_equal(first.dt, second.dt)

    def test_future_write_cannot_change_earlier_query_or_noise_overwrite(self):
        # Unknown, write zero, read zero, write two, conflicting noise, read two.
        events = [(QUERY, 1, None), (WRITE, 1, 0), (QUERY, 1, None),
                  (WRITE, 1, 2), (NOISE, 1, 1), (QUERY, 1, None), (QUERY, 0, None)]
        x = np.zeros((1, len(events), 4 + 2 + 3), np.float32)
        for i, (kind, key, value) in enumerate(events):
            x[0, i, kind] = x[0, i, 4 + key] = 1
            if value is not None:
                x[0, i, 6 + value] = 1
        expected = [[3, IGNORE_TARGET, 0, IGNORE_TARGET, IGNORE_TARGET, 2, 3]]
        np.testing.assert_array_equal(oracle_targets(x, keys=2, values=3), expected)
        for length in range(1, len(events) + 1):
            np.testing.assert_array_equal(oracle_targets(x[:, :length], keys=2, values=3),
                                          np.asarray(expected)[:, :length])
        changed = x.copy()
        changed[0, 3, 6:] = [0, 1, 0]
        altered = oracle_targets(changed, keys=2, values=3)
        np.testing.assert_array_equal(altered[:, :3], np.asarray(expected)[:, :3])
        self.assertEqual(altered[0, 5], 1)

    def test_rejects_invalid_task_and_malformed_event_fields(self):
        for kwargs in ({"keys": 3}, {"queries": 1}, {"queries": 7}, {"values": 1},
                       {"delay_steps": -1}, {"dt": 0}, {"dt": float("nan")},
                       {"dt": float("inf")}, {"dt": True}, {"keys": True},
                       {"condition": "fake"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                make_content_batch(0, 2, **kwargs)
        batch = make_content_batch(0, 2)
        for position, value in [((0, -1, 12), 1), ((0, 0, 0), 0),
                                ((0, 0, 4), float("nan")), ((0, -1, QUERY), .5)]:
            bad = batch.x.copy()
            bad[position] = value
            with self.subTest(position=position), self.assertRaises(ValueError):
                oracle_targets(bad, keys=8, values=16)

    def test_zero_delay_and_smallest_contract(self):
        batch = make_content_batch(0, 1, keys=4, values=2, queries=2, delay_steps=0)
        self.assertEqual(batch.x.shape, (1, 5, 10))
        np.testing.assert_array_equal(batch.targets, oracle_targets(batch.x, keys=4, values=2))
        np.testing.assert_array_equal(batch.x[..., SILENCE].sum(1), [1])


if __name__ == "__main__":
    unittest.main()
