"""Actual finite differences, independent input propagation and accounting."""

import unittest
import numpy as np

from cell_field_common_objective_v8 import build_long_reference, prepare_proposals
from cell_field_response_v7 import loss2_terminal_maps
from cell_field_terminal_v8 import METHODS, WEIGHTS, make_terminal_proposal
from test_cell_field_response_v7 import controlled_example, observed


def plan(state, train, panels, method, remaining=32):
    return make_terminal_proposal(state, train, panels[:4], panels[4:], method=method, remaining=remaining)


class TerminalProposalTests(unittest.TestCase):
    def test_true_zero_tail_and_central_half_step_action_differences(self):
        for mode in ("linear", "gated"):
            for clip in (5., .001):
                state, train, panels, _ = controlled_example(mode, clip)
                before = state.digest()
                result = plan(state, train, panels, "full_adjoint_remaining")
                actual = state.clone()
                for k in range(32):
                    actual.advance(*train, intervention=np.zeros(state.parameter_count))
                    np.testing.assert_array_equal(actual.vector(), result["reference_states"][k+1])
                np.testing.assert_array_equal(observed(actual.head, panels), result["reference_terminal_panels"])
                direction = np.random.default_rng(329).normal(size=state.parameter_count)
                for epsilon in (1e-4, 5e-5):
                    terminal = []
                    for sign in (1, -1):
                        actual = state.clone()
                        for k in range(32):
                            action = sign*epsilon*direction if k == 0 else np.zeros(state.parameter_count)
                            actual.advance(*train, intervention=.02*action)
                        terminal.append(observed(actual.head, panels))
                    np.testing.assert_allclose(result["first_action_map"] @ direction,
                        (terminal[0]-terminal[1])/(2*epsilon), rtol=5e-5, atol=4e-9)
                self.assertEqual(state.digest(), before)

    def test_terminal_field_matches_full_and_arbitrary_initial_perturbation(self):
        for mode in ("linear", "gated"):
            state, train, panels, _ = controlled_example(mode)
            full = plan(state, train, panels, "full_adjoint_remaining")
            field = plan(state, train, panels, "terminal_field8_remaining")
            np.testing.assert_array_equal(full["first_action_map"], field["first_action_map"])
            np.testing.assert_array_equal(full["action"], field["action"])
            self.assertEqual(field["initial_field_observation"].shape, (8, 3*state.parameter_count))
            rng, p = np.random.default_rng(239), state.parameter_count
            scales = np.r_[np.ones(p), np.maximum(np.abs(state.vector()[p:2*p]), 1e-9),
                           np.maximum(state.vector()[2*p:], 1e-20)]
            perturbation, action = rng.normal(size=3*p)*scales, rng.normal(size=p)
            reference = build_long_reference(state, train, panels)
            current = perturbation.copy()
            for k, derivative in enumerate(reference.transitions):
                current = derivative.jvp(current)
                if k == 0:
                    current[:p] += .02*action
            expected = reference.gradients[-1] @ current[:p]
            np.testing.assert_allclose(field["initial_field_observation"] @ perturbation
                +field["first_action_map"] @ action, expected, rtol=1e-11, atol=1e-11)

    def test_loss2_transport_parity_and_immediate_h1_feedthrough(self):
        for mode in ("linear", "gated"):
            state, train, panels, _ = controlled_example(mode)
            response = build_long_reference(state, train, panels)
            reduced = plan(state, train, panels, "loss2_remaining")
            np.testing.assert_allclose(reduced["first_action_map"], loss2_terminal_maps(response)[0], atol=1e-13)
            outputs = [plan(state, train, panels, method, remaining=1) for method in METHODS]
            for value in outputs[1:]:
                np.testing.assert_array_equal(value["first_action_map"], outputs[0]["first_action_map"])
                np.testing.assert_array_equal(value["action"], outputs[0]["action"])

    def test_free_prefix_first_action_equivalence_and_actual_query_counts(self):
        state, train, panels, _ = controlled_example("gated")
        original = prepare_proposals(build_long_reference(state, train, panels))
        full = plan(state, train, panels, "full_adjoint_remaining")
        np.testing.assert_allclose(full["action"], original["plans"]["full32_one_action"]["actions"][0], rtol=1e-13, atol=1e-14)
        np.testing.assert_allclose(full["action"], original["plans"]["full32_eight_actions"]["actions"][0], rtol=1e-13, atol=1e-14)
        for method in METHODS:
            result = plan(state, train, panels, method)
            h = 1 if method == "myopic_h1" else 32
            record = result["record"]
            self.assertEqual(record["reference_optimizer_updates"], h)
            self.assertEqual(record["planning_panel_head_evaluations"], 8*h if method == "loss2_remaining" else 8)
            self.assertEqual(record["training_head_gradient_evaluations_from_fixed_calls"],
                2*h if method == "terminal_field8_remaining" else 2*h-1)
            self.assertLessEqual(record["projected_stationarity_linf"], 1e-12)
            self.assertLessEqual(np.max(np.abs(result["action"])), 4./np.sqrt(state.parameter_count))
            self.assertAlmostEqual(record["predicted_risk_change"], WEIGHTS @ result["first_action_map"] @ result["action"], places=14)

    def test_wrong_context_or_unregistered_terminal_rule_rejects(self):
        state, train, panels, _ = controlled_example("linear")
        before = state.digest()
        with self.assertRaises(ValueError):
            plan(state, (train[0]+1, train[1]), panels, "full_adjoint_remaining")
        with self.assertRaises(ValueError):
            plan(state, train, panels, "full_adjoint_remaining", remaining=33)
        with self.assertRaises(ValueError):
            make_terminal_proposal(state, train, panels[:4], panels[4:], method="loss2_remaining", remaining=8, effort_price=.02)
        self.assertEqual(state.digest(), before)


if __name__ == "__main__":
    unittest.main()
