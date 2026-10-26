"""Real certified paths survive fixed dispatch; failed work remains observable."""

import unittest
from unittest.mock import patch

import numpy as np

from cell_field_repair_v7 import repair_sequence as legacy
from cell_field_safety_portfolio_v8 import repair_sequence
from test_cell_field_policy_v7 import fixture


class FixedPortfolioTests(unittest.TestCase):
    def test_first_certificate_avoids_second_search_and_returns_exact_old_result(self):
        state, train, panels, anchors, _ = fixture()
        intended = np.zeros((8, state.parameter_count))
        expected = legacy(state, train, panels, intended, anchors)
        with patch("cell_field_safety_portfolio_v8.joint", side_effect=AssertionError("unnecessary second search")):
            result = repair_sequence(state, train, panels, intended, anchors)
        self.assertTrue(result["record"]["certified"])
        np.testing.assert_array_equal(result["actions"], expected["actions"])
        self.assertEqual(result["receipts"], expected["receipts"])
        self.assertEqual(result["state"].digest(), expected["state"].digest())
        self.assertEqual(len(result["record"]["attempts"]), 1)

    def test_rejected_first_search_restarts_at_exact_origin_and_preserves_paid_work(self):
        state, train, panels, anchors, _ = fixture("gated")
        intended = np.zeros((8, state.parameter_count))
        before = state.digest()
        first = legacy(state, train, panels, intended, anchors)
        first["record"].update(certified=False, status="rejected", certified_optimizer_steps=0,
            reason="mechanical fixture: first search deliberately withholds its certificate")
        first.update(state=state.clone(), states=[state.clone()], actions=np.zeros((0, state.parameter_count)),
            receipts=[], old_losses=anchors[None])
        with patch("cell_field_safety_portfolio_v8.single_ray", return_value=first):
            result = repair_sequence(state, train, panels, intended, anchors)
        self.assertTrue(result["record"]["certified"], result["record"])
        self.assertEqual(result["record"]["selected_filter"], "joint_actual_old_v8")
        self.assertEqual(result["record"]["attempts"][0]["record"], first["record"])
        self.assertEqual(result["record"]["verified_optimizer_steps"],
            sum(a["record"]["verified_optimizer_steps"] for a in result["record"]["attempts"]))
        actual = state.clone()
        for action, receipt, expected in zip(result["actions"], result["receipts"], result["states"][1:], strict=True):
            self.assertEqual(actual.advance(*train, intervention=.02*action), receipt)
            self.assertEqual(actual.digest(), expected.digest())
        self.assertEqual(state.digest(), before)

    def test_both_failed_prefixes_are_discarded_and_charged(self):
        state, train, panels, anchors, _ = fixture()
        intended = np.zeros((1, state.parameter_count))
        result = legacy(state, train, panels, intended, anchors, horizon=1)
        result["record"].update(certified=False, status="rejected", certified_optimizer_steps=0)
        result.update(state=state.clone(), states=[state.clone()], actions=np.zeros((0, state.parameter_count)),
            receipts=[], old_losses=anchors[None])
        with patch("cell_field_safety_portfolio_v8.single_ray", return_value=result), \
                patch("cell_field_safety_portfolio_v8.joint", return_value=result):
            output = repair_sequence(state, train, panels, intended, anchors, horizon=1)
        self.assertFalse(output["record"]["certified"])
        self.assertEqual(output["record"]["discarded_safe_prefix_steps"], 2)
        self.assertEqual(output["state"].digest(), state.digest())
        self.assertEqual(output["actions"].shape, (0, state.parameter_count))


if __name__ == "__main__":
    unittest.main()
