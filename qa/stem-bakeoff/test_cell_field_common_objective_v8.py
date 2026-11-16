"""Long-window derivatives, common-cost nesting and actual complete-state replay."""

import unittest

import numpy as np

from cell_field_common_objective_v8 import (BRANCHES, WEIGHTS, build_long_reference,
    long_future_field, prepare_proposals, rollout32)
from test_cell_field_response_v7 import controlled_example, observed


class CommonObjectiveTests(unittest.TestCase):
    def test_h32_complete_state_and_action_jvp_match_actual_half_step_differences(self):
        for mode in ("linear", "gated"):
            for clip in (5., .001):
                state, train, panels, _ = controlled_example(mode, clip)
                reference = build_long_reference(state, train, panels)
                p, vector, rng = state.parameter_count, state.vector(), np.random.default_rng(804)
                scales = np.r_[np.full(p, .1), np.maximum(np.abs(vector[p:2*p]), 1e-12),
                    np.maximum(vector[2*p:], 1e-24)]
                initial = rng.normal(size=3*p)*scales
                actions = rng.normal(size=(32, p)); actions[8:] = 0.
                tangent = initial.copy()
                for k, derivative in enumerate(reference.transitions):
                    tangent = derivative.jvp(tangent)
                    tangent[:p] += .02*actions[k]
                expected = reference.gradients[-1]@tangent[:p]
                for epsilon in (1e-5, 5e-6):
                    outcomes = []
                    for sign in (1, -1):
                        actual = state.clone()
                        actual.set_vector(vector+sign*epsilon*initial)
                        for action in actions:
                            actual.advance(*train, intervention=sign*epsilon*.02*action)
                        outcomes.append(observed(actual.head, panels))
                    finite = (outcomes[0]-outcomes[1])/(2*epsilon)
                    np.testing.assert_allclose(expected, finite, rtol=8e-5, atol=3e-8)

    def test_field_matches_independent_forward_jvp_and_full_spectrum(self):
        for mode in ("linear", "gated"):
            state, train, panels, _ = controlled_example(mode)
            reference = build_long_reference(state, train, panels)
            field = long_future_field(reference)
            p, rng = state.parameter_count, np.random.default_rng(811)
            initial = rng.normal(size=3*p)*np.r_[np.ones(p), np.full(p, .01), np.full(p, 1e-5)]
            actions = rng.normal(size=(32, p))*.1
            tangent, outputs = initial.copy(), [reference.gradients[0]@initial[:p]]
            for k, derivative in enumerate(reference.transitions):
                tangent = derivative.jvp(tangent); tangent[:p] += .02*actions[k]
                outputs.append(reference.gradients[k+1]@tangent[:p])
            np.testing.assert_allclose(field.forecast(actions, initial)["losses"], outputs, rtol=2e-10, atol=2e-10)
            full, reduced = reference.terminal_sequence_maps(), field.terminal_maps()
            np.testing.assert_allclose(reduced, full, rtol=2e-11, atol=2e-13)
            matrices = [value.transpose(1, 0, 2).reshape(8, -1) for value in (full, reduced)]
            np.testing.assert_allclose(np.linalg.svd(matrices[0], compute_uv=False),
                np.linalg.svd(matrices[1], compute_uv=False), rtol=2e-10, atol=2e-13)
            self.assertEqual([len(x) for x in field.observations], list(range(264, 7, -8)))
            self.assertGreater(len(field.observations[0]), 3*p)

    def test_common_terminal_actions_are_nested_but_myopic_objective_is_distinct(self):
        for mode in ("linear", "gated"):
            state, train, panels, _ = controlled_example(mode)
            reference = build_long_reference(state, train, panels)
            prepared = prepare_proposals(reference)
            plans, maps, p = prepared["plans"], prepared["maps"], state.parameter_count
            self.assertEqual(tuple(plans), BRANCHES)
            for name, plan in plans.items():
                n = plan["record"]["free_action_steps"]
                np.testing.assert_array_equal(plan["actions"][n:], np.zeros((32-n, p)))
                self.assertLessEqual(np.max(np.abs(plan["actions"])), 4/np.sqrt(p))
                self.assertLessEqual(plan["record"]["box_quadratic_stationarity"], 1e-12)
            one, eight = plans["full32_one_action"], plans["full32_eight_actions"]
            self.assertLessEqual(eight["record"]["tangent_proposal_objective"],
                one["record"]["tangent_proposal_objective"]+1e-13)
            np.testing.assert_allclose(eight["actions"], plans["field32_eight_actions"]["actions"], atol=2e-11, rtol=2e-11)
            self.assertGreater(np.linalg.norm(one["actions"]-plans["myopic_h1_zero_tail"]["actions"]), 1e-6)
            self.assertEqual(plans["myopic_h1_zero_tail"]["record"]["proposal_endpoint"], 1)
            np.testing.assert_array_equal(maps["loss2"][-1], maps["full"][-1])
            self.assertGreater(np.linalg.norm(maps["loss2"][:8]-maps["full"][:8]), 1e-7)

    def test_actual_h32_replay_keeps_violations_and_complete_optimizer_metadata(self):
        for mode in ("linear", "gated"):
            state, train, panels, _ = controlled_example(mode)
            before = state.digest()
            reference = build_long_reference(state, train, panels)
            actions = prepare_proposals(reference)["plans"]["full32_eight_actions"]["actions"]
            result = rollout32(state, train, panels, actions, np.zeros(4))
            actual, hashes, receipts = state.clone(), [state.digest()], []
            for action in actions:
                receipts.append(actual.advance(*train, intervention=.02*action))
                hashes.append(actual.digest())
            self.assertEqual(result["record"]["state_sha256"], hashes)
            self.assertEqual(result["record"]["receipts"], receipts)
            self.assertEqual(result["states"][-1]._metadata(), actual._metadata())
            np.testing.assert_array_equal(result["states"][-1].vector(), actual.vector())
            self.assertEqual(result["record"]["old_violating_steps"], 32)
            self.assertEqual(result["record"]["completed_steps"], 32)
            self.assertFalse(result["record"]["safe_execution_candidate"])
            self.assertAlmostEqual(result["record"]["actual_common_objective"],
                WEIGHTS@observed(actual.head, panels)+.5*.02*.03*np.square(actions).sum(), places=13)
            self.assertEqual(state.digest(), before)
            zero = rollout32(state, train, panels, np.zeros_like(actions), reference.observations[0, 4:])
            np.testing.assert_array_equal(np.stack([s.vector() for s in zero["states"]]), reference.states)
            np.testing.assert_array_equal(zero["losses"], reference.observations)

    def test_wrong_context_or_out_of_box_branch_is_rejected_without_advancing(self):
        state, train, panels, _ = controlled_example("linear")
        before = state.digest()
        with self.assertRaisesRegex(ValueError, "bound context"):
            build_long_reference(state, (train[0]+.1, train[1]), panels)
        actions = np.zeros((32, state.parameter_count)); actions[0, 0] = 1.
        with self.assertRaisesRegex(ValueError, "same-box"):
            rollout32(state, train, panels, actions, np.ones(4))
        self.assertEqual(state.digest(), before)


if __name__ == "__main__":
    unittest.main()
