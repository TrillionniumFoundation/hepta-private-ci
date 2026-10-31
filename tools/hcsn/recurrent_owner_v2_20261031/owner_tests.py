"""State/gradient law is inherited; these tests qualify incremental ownership."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import unittest

import numpy as np

from ..task_value_factorial_20261030.cells import augmented_features, initial, physical
from ..task_value_factorial_20261030.execution import sample_interval, sampled_features
from .owner import CellOwner, canonical_bytes


class IncrementalOwnerTests(unittest.TestCase):
    def setUp(self):
        self.parameters = np.array([.1, -.2, .3, -.4, .2, -.1, .3, -.2, .1, .5, -.4])

    def test_full_history_and_incremental_queries_agree_across_resets(self):
        random = np.random.default_rng(80421)
        for family in ("ordinary", "analytic"):
            owner, history = CellOwner(family, self.parameters), []
            for step in range(40):
                driver, duration = float(random.uniform(-1, 1)), float(random.uniform(.0001, 3.))
                record = dict(history=history, driver=driver, horizon=duration)
                before = owner.snapshot()
                features, sequence = owner.query(driver, duration)
                np.testing.assert_allclose(features, augmented_features(family, self.parameters, [record])[0], rtol=0, atol=3e-13)
                self.assertEqual(sequence, step)
                self.assertEqual(before, owner.snapshot())
                reset = step % 9 == 8
                owner.advance(step+1, driver, duration, reset)
                history.append(dict(driver=driver, duration=duration, reset=reset))

    def test_sampled_path_and_checkpoint_continue_with_identical_rng(self):
        seed, random = 80422, np.random.default_rng(80422)
        index = int(random.choice(5, p=initial(physical(self.parameters, 0.))))
        owner = CellOwner("analytic", self.parameters, "sampled", seed)
        for step in range(12):
            driver, duration, reset = (-.4 if step%2 else .7), .3+step*.2, step%4 == 3
            before = owner.snapshot()
            features, _ = owner.query(driver, duration)
            np.testing.assert_allclose(features, sampled_features(self.parameters, index, driver, duration), rtol=0, atol=2e-14)
            self.assertEqual(before, owner.snapshot())
            index, expected = sample_interval(self.parameters, index, driver, duration, reset, random)
            actual = owner.advance(step+1, driver, duration, reset)
            self.assertEqual(actual["sampled_index"], index)
            self.assertEqual(actual["jumps"], expected["jumps"])
            self.assertEqual(actual["event_count"], expected["count"])
            restored = CellOwner("analytic", self.parameters, "sampled", 100)
            restored.restore(owner.snapshot())
            self.assertEqual(restored.snapshot(), owner.snapshot())
            owner = restored

    def test_identity_corruption_and_invalid_intervals_leave_state_untouched(self):
        for mode in ("distribution", "sampled"):
            owner = CellOwner("analytic", self.parameters, mode, 5)
            owner.advance(1, .2, 1.)
            expected = owner.snapshot()
            for args in ((1, .2, 1.), (3, .2, 1.), (2, float("nan"), 1.), (2, .2, -1.)):
                with self.assertRaises(ValueError):
                    owner.advance(*args)
                self.assertEqual(expected, owner.snapshot())
            bad = copy.deepcopy(expected)
            bad["record"]["elapsed"] += 1
            with self.assertRaises(ValueError):
                owner.restore(bad)
            self.assertEqual(expected, owner.snapshot())
            wrong_model = CellOwner("analytic", self.parameters+.01, mode, 5)
            with self.assertRaises(ValueError):
                wrong_model.restore(expected)
            bad = copy.deepcopy(expected)
            bad["record"]["sampled_index"] = 8
            bad["sha256"] = hashlib.sha256(canonical_bytes(bad["record"])).hexdigest()
            with self.assertRaises(ValueError):
                owner.restore(bad)
            self.assertEqual(expected, owner.snapshot())

    def test_concurrent_duplicate_is_consumed_once(self):
        owner = CellOwner("analytic", self.parameters)
        def attempt(_):
            try:
                return owner.advance(1, .4, .5)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            attempts = list(pool.map(attempt, range(12)))
        self.assertEqual(sum(result is not None for result in attempts), 1)
        reference = CellOwner("analytic", self.parameters)
        reference.advance(1, .4, .5)
        self.assertEqual(owner.snapshot(), reference.snapshot())


if __name__ == "__main__":
    unittest.main()
