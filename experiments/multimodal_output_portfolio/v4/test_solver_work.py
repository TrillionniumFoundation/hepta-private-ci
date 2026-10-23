"""Adversarial resource and cache-ownership regressions for finite v4 NDU.

These are source-level logical-work checks, not actual physical latency,
memory, power, native inference, or science validation.
"""
from __future__ import annotations

import gc
import math
import unittest
import weakref
from unittest.mock import patch

from portfolio import (
    Config, Controller, State, execute, MAX_EXACT_SOLVER_BRANCHES,
    MAX_EXACT_SOLVER_STATES,
)


class SolverWorkTests(unittest.TestCase):
    def test_controller_is_released_after_a_completed_solve(self):
        # The original module-level @lru_cache(maxsize=65536) on solve(self,...)
        # kept a strong reference to the completed Controller and its config.
        ctl = Controller(Config(horizon=2))
        ctl.solve(State((0, 0, 0, 0), 12))
        ref = weakref.ref(ctl)
        del ctl
        gc.collect()
        self.assertIsNone(ref())

    def test_cache_is_owned_by_one_controller(self):
        cfg = Config(horizon=2)
        state = State((0, 0, 0, 0), 12)
        first = Controller(cfg)
        first.solve(state)
        self.assertGreater(first.work_receipt()["expanded_states"], 1)
        second = Controller(cfg)
        self.assertEqual(second.work_receipt()["expanded_states"], 0)
        self.assertEqual(second.work_receipt()["cache_hits"], 0)
        self.assertEqual(first.solve(state), second.solve(state))

    def test_logical_work_bounds_and_repeated_query(self):
        cfg = Config(horizon=3)
        ctl = Controller(cfg)
        state = State((0, 0, 0, 0), 12)
        action, value = ctl.solve(state)
        self.assertEqual(len(action.units), 4)
        self.assertTrue(math.isfinite(value))
        before = ctl.work_receipt()
        self.assertGreater(before["expanded_states"], 1)
        self.assertGreater(before["evaluated_branches"], 0)
        self.assertEqual(before["evaluated_branches"] % 3, 0)
        self.assertEqual(before["expanded_states"], before["cached_states"])
        self.assertLessEqual(before["expanded_states"], MAX_EXACT_SOLVER_STATES)
        self.assertLessEqual(before["evaluated_branches"], MAX_EXACT_SOLVER_BRANCHES)
        ctl.solve(state)
        after = ctl.work_receipt()
        self.assertEqual(after["expanded_states"], before["expanded_states"])
        self.assertEqual(after["evaluated_branches"], before["evaluated_branches"])
        self.assertEqual(after["cache_hits"], before["cache_hits"] + 1)

    def test_state_work_cap_rejects_before_unbounded_expansion(self):
        with patch("portfolio.MAX_EXACT_SOLVER_STATES", 1):
            ctl = Controller(Config(horizon=2))
            with self.assertRaisesRegex(ValueError, "state budget exhausted"):
                ctl.solve(State((0, 0, 0, 0), 12))
            self.assertEqual(ctl.work_receipt()["expanded_states"], 1)

    def test_branch_work_cap_rejects_before_unbounded_expansion(self):
        with patch("portfolio.MAX_EXACT_SOLVER_BRANCHES", 1):
            ctl = Controller(Config(horizon=2))
            with self.assertRaisesRegex(ValueError, "branch budget exhausted"):
                ctl.solve(State((0, 0, 0, 0), 12))
            self.assertEqual(ctl.work_receipt()["evaluated_branches"], 0)

    def test_emission_and_solver_work_bound_into_new_trace(self):
        cfg = Config(horizon=3, risk_aversion=0,
                     activation_cost=1, cost_shadow_price=0.02)
        state = State((0, 0, 0, 0), 12)
        first = execute(state, cfg, seed=0)
        replay = execute(state, cfg, seed=0)
        self.assertEqual(first["trace_sha256"], replay["trace_sha256"])
        self.assertEqual(first["solver_work"], replay["solver_work"])
        self.assertEqual(first["spent"] + first["remaining_after_emission"], 12)
        self.assertEqual(set(first["outputs"]), {"text", "audio", "image", "video"})
        self.assertGreater(first["solver_work"]["expanded_states"], 0)
        self.assertEqual(first["solver_work"]["cached_states"],
                         first["solver_work"]["expanded_states"])
        self.assertLessEqual(first["solver_work"]["maximum_states"],
                             MAX_EXACT_SOLVER_STATES)
        self.assertLessEqual(first["solver_work"]["maximum_branches"],
                             MAX_EXACT_SOLVER_BRANCHES)


if __name__ == "__main__":
    unittest.main()
