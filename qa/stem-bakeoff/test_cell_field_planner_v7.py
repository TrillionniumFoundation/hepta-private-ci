"""Actual Adam replay and the distinction between proposal and accepted plan."""

import unittest
from unittest.mock import patch

import numpy as np

from cell_field_planner_v7 import actual_terminal, make_plan
from cell_field_qp_v7 import objective_weights
from test_cell_field_response_v5 import example
from test_cell_field_response_v7 import controlled_example, observed


def fixture(mode):
    state, train, _ = example(mode)
    rng = np.random.default_rng(428)
    panels = tuple((train[0]+.02*rng.normal(size=train[0].shape), train[1]) for _ in range(8))
    return state, train, panels, observed(state.head, panels)[4:]


class ActualPanelPlannerTests(unittest.TestCase):
    def test_exact_full_step_keeps_both_head_box_endpoints_despite_subtraction_roundoff(self):
        for mode, value in (("linear", -.26262343090758195), ("gated", -.5390902246634411)):
            state, train, panels, anchors = fixture(mode)
            bound = 4/np.sqrt(state.parameter_count)
            self.assertGreater(value+(bound-value), bound)
            shape = (8, state.parameter_count)
            responses = [{"actions": np.full(shape, value), "record": {"status": "qualified"}},
                {"actions": np.full(shape, bound), "record": {"status": "qualified"}},
                {"actions": None, "record": {"status": "unresolved"}}]
            losses = [np.r_[np.full(4, v), anchors-.01] for v in (2., 1.)]
            with patch("cell_field_planner_v7.solve_terminal", side_effect=responses), \
                    patch("cell_field_planner_v7.actual_terminal", side_effect=losses):
                plan = make_plan(state, train, panels, anchors, method="full", horizon=8, relinearizations=2)
            np.testing.assert_array_equal(plan["actions"], np.full(shape, bound))
            self.assertTrue(np.all(np.abs(plan["actions"]) <= bound))
            self.assertEqual(plan["record"]["selected_fraction"], 1.)

    def test_actual_terminal_matches_full_state_advance_with_nonzero_nominal(self):
        for mode in ("linear", "gated"):
            state, train, panels, actions = controlled_example(mode)
            origin = state.digest()
            actual = state.clone()
            for action in actions:
                actual.advance(*train, intervention=.02*action)
            np.testing.assert_array_equal(actual_terminal(state, train, panels, actions, .02),
                observed(actual.head, panels))
            self.assertEqual(state.digest(), origin)

    def test_h1_panel_feedthrough_makes_all_three_planners_identical(self):
        for mode in ("linear", "gated"):
            state, train, panels, anchors = fixture(mode)
            origin = state.digest()
            plans = [make_plan(state, train, panels, anchors, method=method, horizon=1,
                old_weight=.25, current_dispersion=.5, relinearizations=2)
                for method in ("full", "loss2", "future_field")]
            for plan in plans:
                self.assertEqual(plan["record"]["status"], "qualified", plan["record"])
                np.testing.assert_allclose(plan["actions"], plans[0]["actions"], rtol=1e-12, atol=1e-13)
                np.testing.assert_allclose(plan["maps"], plans[0]["maps"], rtol=1e-12, atol=1e-14)
            self.assertEqual(state.digest(), origin)

    def test_h8_field_full_parity_actual_nominal_replay_and_monotone_merit(self):
        for mode in ("linear", "gated"):
            state, train, panels, anchors = fixture(mode)
            origin = state.digest()
            options = dict(horizon=8, old_weight=.25, current_dispersion=.5, relinearizations=2)
            full = make_plan(state, train, panels, anchors, method="full", **options)
            field = make_plan(state, train, panels, anchors, method="future_field", **options)
            for plan in (full, field):
                record = plan["record"]
                self.assertEqual(record["status"], "qualified", record)
                accepted = [row["trials"][-1]["merit"] for row in record["rounds"] if row["accepted"]]
                self.assertTrue(all(b < a-1e-12 for a, b in zip(accepted, accepted[1:])))
                terminal = actual_terminal(state, train, panels, plan["actions"], .02)
                merit = (objective_weights(terminal, .25, .5)[0]
                    +.5*.02*.03*np.square(plan["actions"]).sum()
                    +10.*np.maximum(terminal[4:]-anchors, 0.).sum())
                self.assertAlmostEqual(record["terminal_actual_merit"], merit, places=13)
                self.assertLessEqual(float(np.abs(plan["actions"]).max()), 4./np.sqrt(state.parameter_count))
                actual = state.clone()
                for k in range(9):
                    np.testing.assert_array_equal(plan["reference_states"][k], actual.vector())
                    np.testing.assert_array_equal(plan["reference_observations"][k], observed(actual.head, panels))
                    if k < 8:
                        actual.advance(*train, intervention=.02*plan["nominal_reference_actions"][k])
                self.assertEqual(record["actual_rollout_optimizer_steps"],
                    8*sum(len(row["trials"]) for row in record["rounds"]))
            np.testing.assert_allclose(field["actions"], full["actions"], rtol=1e-10, atol=1e-12)
            np.testing.assert_allclose(field["maps"], full["maps"], rtol=1e-10, atol=1e-13)
            self.assertEqual(field["record"]["rounds"][0]["field_dimensions"], list(range(72, 7, -8)))
            self.assertEqual(state.digest(), origin)

    def test_partial_merit_step_is_not_relabelled_as_inner_qp_optimum(self):
        state, train, panels, anchors = fixture("linear")
        shape = (8, state.parameter_count)
        responses = [{"actions": np.zeros(shape), "record": {"status": "qualified"}},
            {"actions": np.full(shape, .2), "record": {"status": "qualified"}},
            {"actions": None, "record": {"status": "unresolved"}}]
        losses = [np.r_[np.full(4, x), anchors-.01] for x in (1., 1.2, .9)]
        with patch("cell_field_planner_v7.solve_terminal", side_effect=responses), \
                patch("cell_field_planner_v7.actual_terminal", side_effect=losses):
            plan = make_plan(state, train, panels, anchors, method="full", horizon=8,
                relinearizations=2)
        record = plan["record"]
        self.assertEqual(record["status"], "qualified")
        self.assertEqual((record["selected_proposal_iteration"], record["selected_fraction"]), (1, .5))
        self.assertFalse(record["selected_actions_equal_inner_solution"])
        self.assertTrue(record["requires_nonlinear_path_verification"])
        np.testing.assert_array_equal(plan["actions"], np.full(shape, .1))
        self.assertEqual(record["rounds"][-1]["qp"]["status"], "unresolved")
        self.assertEqual(record["actual_rollout_evaluations"], 3)
        self.assertEqual(record["actual_rollout_optimizer_steps"], 24)


if __name__ == "__main__":
    unittest.main()
