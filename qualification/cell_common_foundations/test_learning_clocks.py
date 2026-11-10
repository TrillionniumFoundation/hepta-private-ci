import copy
import unittest
import numpy as np

try:
    from .learning_clocks import LearningClock, clock_specs, run_clock_attempt
    from .credit import make_model, LAYERS
    from .protocol import canonical_digest
except ImportError:
    from learning_clocks import LearningClock, clock_specs, run_clock_attempt
    from credit import make_model, LAYERS
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
