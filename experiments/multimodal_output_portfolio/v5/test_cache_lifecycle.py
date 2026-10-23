"""Fail-closed per-controller Bellman cache and immutable-profile regressions.

Only finite synthetic reference behavior is covered. Python cache residency
must not be confused with measured CPU/GPU inference or promotion authority.
"""
import gc
import unittest
import weakref
from fractions import Fraction

from joint_portfolio import JointController, Profile, PublicState, STOP


class BellmanCacheLifecycleTests(unittest.TestCase):
    @staticmethod
    def terminal_state():
        return PublicState((2, 2, 2, 2), Fraction(49, 50), 4)

    def test_completed_controller_is_not_retained_by_global_lru(self):
        """Class-method lru_cache used to keep finished controllers alive."""
        controller = JointController(Profile(horizon=1))
        state = self.terminal_state()
        chosen, value = controller.solve(state)
        self.assertEqual(chosen, STOP)
        self.assertIsInstance(value, float)
        weak_controller = weakref.ref(controller)
        del controller
        gc.collect()
        self.assertIsNone(
            weak_controller(),
            "completed controller/profile retained by a process-global cache",
        )

    def test_profile_cannot_be_replaced_after_bellman_value_is_cached(self):
        controller = JointController(Profile(horizon=1, gamma=0))
        state = self.terminal_state()
        before = controller.solve(state)
        with self.assertRaises(AttributeError):
            controller.cfg = Profile(horizon=1, gamma=4)
        self.assertEqual(controller.solve(state), before)
        self.assertEqual(controller.cfg.gamma, 0)

    def test_independent_profiles_never_share_state_values(self):
        state = self.terminal_state()
        risk_neutral = JointController(Profile(horizon=1, gamma=0))
        risk_averse = JointController(Profile(horizon=1, gamma=2))
        expected = risk_neutral.solve(state)[1]
        self.assertEqual(risk_averse.value_expansions, 0)
        cautious = risk_averse.solve(state)[1]
        self.assertNotEqual(expected, cautious)
        self.assertEqual(risk_neutral.value_expansions, 1)
        self.assertEqual(risk_averse.value_expansions, 1)

    def test_cache_entries_and_expansions_share_a_hard_upper_bound(self):
        cfg = Profile(horizon=1)
        for upper in (1, 3, 16):
            with self.subTest(upper=upper):
                controller = JointController(cfg, max_expansions=upper)
                self.assertEqual(controller._solve_cached.cache_info().maxsize, upper)
                state = self.terminal_state()
                controller.solve(state)
                self.assertLessEqual(controller.value_expansions, upper)
                self.assertLessEqual(
                    controller._solve_cached.cache_info().currsize, upper
                )
        for invalid in (0, True, -1, 100001, float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    JointController(cfg, max_expansions=invalid)

    def test_unknown_profile_rejected_before_allocating_cache(self):
        with self.assertRaisesRegex(ValueError, "immutable NDU profile"):
            JointController(None)
        with self.assertRaisesRegex(ValueError, "immutable NDU profile"):
            JointController({"gamma": 1})


if __name__ == "__main__":
    unittest.main()
