import copy
import unittest
import numpy as np

try:
    from .learning_clocks import (
        LearningClock,
        MODES,
        PERIODS,
        clock_specs,
        run_clock_attempt,
    )
    from .credit import make_model, propose, LAYERS
    from .protocol import canonical_digest
except ImportError:
    from learning_clocks import (
        LearningClock,
        MODES,
        PERIODS,
        clock_specs,
        run_clock_attempt,
    )
    from credit import make_model, propose, LAYERS
    from protocol import canonical_digest


class LearningClockTests(unittest.TestCase):
    def test_pending_rows_restore_and_release_exact_average(self):
        model = make_model(19)
        clock = LearningClock(model, "lineage")
        g = {k: np.ones_like(v) for k, v in model.parameters().items()}
        clock.advance(1, g, model.digest)
        model2, restored = LearningClock.restore(clock.checkpoint(model))
        for tick in range(2, 9):
            a, ar = clock.advance(tick, g, model.digest)
            b, br = restored.advance(tick, g, model2.digest)
            self.assertEqual(ar, br)
            for k in LAYERS:
                np.testing.assert_array_equal(a[k], b[k])
        self.assertEqual(ar["buffered_samples"][0], 8)
        np.testing.assert_array_equal(a["input"][0], 1)

    def test_invalid_or_duplicate_tick_preserves_state(self):
        model = make_model(19)
        clock = LearningClock(model, "lineage")
        g = {k: np.zeros_like(v) for k, v in model.parameters().items()}
        clock.advance(1, g, model.digest)
        before = clock.checkpoint(model)
        for sequence in (1, 3, True):
            with self.assertRaises(ValueError):
                clock.advance(sequence, g, model.digest)
            self.assertEqual(clock.checkpoint(model), before)
        g["bias"][0] = np.nan
        with self.assertRaises(ValueError):
            clock.advance(2, g, model.digest)
        self.assertEqual(clock.checkpoint(model), before)

    def test_corrupt_checkpoint_and_inconsistent_pending_rejected(self):
        c = LearningClock(make_model(1), "lineage").checkpoint(make_model(1))
        broken = copy.deepcopy(c)
        broken["payload"]["tick"] = 7
        with self.assertRaises(ValueError):
            LearningClock.restore(broken)
        broken["digest"] = canonical_digest(broken["payload"])
        broken["payload"]["pending"]["bias"][0] = 0.1
        broken["digest"] = canonical_digest(broken["payload"])
        with self.assertRaises(ValueError):
            LearningClock.restore(broken)

    def test_rehashed_schedule_drift_is_rejected_in_every_mode(self):
        model = make_model(19)
        gradients = {k: np.ones_like(v) for k, v in model.parameters().items()}
        for mode in MODES:
            clock = LearningClock(model, mode, (2, 3, 5, 7, 11, 13, 17))
            for tick in range(1, 6):
                clock.advance(tick, gradients, model.digest)
            for field in ("counts", "group_updates", "cursor"):
                with self.subTest(mode=mode, field=field):
                    checkpoint = copy.deepcopy(clock.checkpoint(model))
                    payload = checkpoint["payload"]
                    if field == "cursor":
                        payload[field] = (payload[field] + 1) % 7
                    elif field == "group_updates":
                        payload[field][0] -= 1
                    else:
                        payload[field][0] += 1
                        payload["first_source"][0] = model.digest
                    checkpoint["digest"] = canonical_digest(payload)
                    before = copy.deepcopy(checkpoint)
                    with self.assertRaisesRegex(ValueError, "schedule"):
                        LearningClock.restore(checkpoint)
                    self.assertEqual(checkpoint, before)

    def test_rehashed_checkpoint_cannot_erase_not_yet_released_gradient(self):
        model = make_model(19)
        clock = LearningClock(model, "lineage")
        gradients = {k: np.full_like(v, 8) for k, v in model.parameters().items()}
        clock.advance(1, gradients, model.digest)
        checkpoint = copy.deepcopy(clock.checkpoint(model))
        payload = checkpoint["payload"]
        payload["counts"][0] = 0
        payload["group_updates"][0] = 1
        payload["first_source"][0] = None
        for layer in LAYERS:
            payload["pending"][layer][0] = np.zeros_like(
                np.asarray(payload["pending"][layer])[0]
            ).tolist()
        checkpoint["digest"] = canonical_digest(payload)
        with self.assertRaisesRegex(ValueError, "schedule"):
            LearningClock.restore(checkpoint)
        gradients = {k: np.ones_like(v) for k, v in model.parameters().items()}
        for tick in range(2, 9):
            released, _ = clock.advance(tick, gradients, model.digest)
        np.testing.assert_array_equal(released["input"][0], [1.875, 1.875])

    def test_all_modes_custom_periods_preserve_checkpoint_continuation(self):
        for mode in MODES:
            for periods in (
                PERIODS,
                (2, 3, 5, 7, 11, 13, 17),
                (1,) * 7,
                (4096,) * 7,
            ):
                with self.subTest(mode=mode, periods=periods):
                    model = make_model(19)
                    clock = LearningClock(model, mode, periods)
                    restored_model, restored = LearningClock.restore(
                        clock.checkpoint(model)
                    )
                    for tick in range(1, 34):
                        gradients = {
                            k: np.full_like(v, (-1) ** tick * tick / 100)
                            for k, v in model.parameters().items()
                        }
                        released, receipt = clock.advance(tick, gradients, model.digest)
                        recovered, recovered_receipt = restored.advance(
                            tick, gradients, restored_model.digest
                        )
                        self.assertEqual(receipt, recovered_receipt)
                        for layer in LAYERS:
                            np.testing.assert_array_equal(
                                released[layer], recovered[layer]
                            )
                        model, update = propose(model, released)
                        restored_model, recovered_update = propose(
                            restored_model, recovered
                        )
                        self.assertEqual(update, recovered_update)
                        self.assertEqual(
                            clock.checkpoint(model), restored.checkpoint(restored_model)
                        )
                        if tick in (1, 5, 16, 32):
                            restored_model, restored = LearningClock.restore(
                                restored.checkpoint(restored_model)
                            )

    def test_budget_control_pairs_data_and_group_update_counts(self):
        results = {s["method"]: run_clock_attempt(s) for s in clock_specs((11,))}
        a, b = results["lineage"], results["budget_round_robin"]
        self.assertEqual(a["group_update_slots"], b["group_update_slots"])
        self.assertEqual(a["data_digest"], b["data_digest"])
        self.assertNotEqual(a["group_updates"], b["group_updates"])
        self.assertNotEqual(a["initial_model_digest"], a["final_model_digest"])
        self.assertGreater(
            results["uniform_all"]["group_update_slots"], a["group_update_slots"]
        )


if __name__ == "__main__":
    unittest.main()
