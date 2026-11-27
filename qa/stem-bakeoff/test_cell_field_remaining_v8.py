"""Actual commit-one replay, complete metadata guards and paid-error atomicity."""

import copy
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_remaining_v8 import execute_remaining, validate_one_step
from cell_field_safety_portfolio_v8 import repair_sequence
from cell_field_terminal_v8 import METHODS, make_terminal_proposal
from test_cell_field_policy_v7 import fixture


def run(state, train, panels, anchors, method="myopic_h1"):
    return execute_remaining(state, train, panels, panels, anchors, method,
        controller_protocol_sha256="b"*64, controller_source_sha256="c"*64)


class RemainingControllerTests(unittest.TestCase):
    def test_all_methods_actual32_replay_and_full_field_same_actions(self):
        state, train, panels, anchors, _ = fixture("gated")
        before, results = state.digest(), {}
        for method in METHODS:
            result = run(state, train, panels, anchors, method)
            results[method] = result
            self.assertEqual(result["record"]["status"], "completed", result["record"])
            self.assertEqual(result["record"]["completed_steps"], 32)
            self.assertEqual(result["record"]["contract"]["original_old_anchors"], anchors.tolist())
            self.assertEqual(result["record"]["contract"]["optimizer_origin_bindings"], state.bindings)
            replay = state.clone()
            for k, action in enumerate(result["actions"]):
                self.assertEqual(replay.advance(*train, intervention=.02*action), result["receipts"][k])
                self.assertEqual(replay.digest(), result["states"][k+1].digest())
                self.assertTrue(np.all(result["old_losses"][k+1] <= anchors))
                self.assertEqual(result["plans"][k]["record"]["proposal_horizon"],
                    1 if method == "myopic_h1" else 32-k)
            self.assertEqual(replay.digest(), result["state"].digest())
            middle = make_terminal_proposal(result["states"][17], train, panels, panels,
                method=method, remaining=15)
            np.testing.assert_array_equal(middle["action"], result["plans"][17]["action"])
        full, field = (results[name] for name in ("full_adjoint_remaining", "terminal_field8_remaining"))
        np.testing.assert_array_equal(full["actions"], field["actions"])
        self.assertEqual(full["state"].digest(), field["state"].digest())
        self.assertEqual(state.digest(), before)

    def test_changed_receipt_rng_anchor_or_vector_cannot_cross_adoption_boundary(self):
        state, train, panels, anchors, _ = fixture()
        valid = repair_sequence(state, train, panels, np.zeros((1, state.parameter_count)), anchors, horizon=1)
        self.assertTrue(valid["record"]["certified"])
        validate_one_step(state, valid, train, panels, anchors)
        for mutation in ("rng", "anchor", "clock", "action", "state", "marks"):
            bad = copy.deepcopy(valid)
            if mutation == "rng":
                bad["states"][1].rng.random()
            elif mutation == "anchor":
                bad["record"]["original_old_anchors"][0] += 1e-7
            elif mutation == "clock":
                bad["states"][1].step_count += 1
            elif mutation == "action":
                bad["actions"][0, 0] += 1e-7
            elif mutation == "state":
                vector = bad["states"][1].vector()
                vector[state.parameter_count] += 1e-7
                bad["states"][1].set_vector(vector)
            else:
                bad["receipts"][0]["marks"][0] = 1
            with self.assertRaises(ValueError, msg=mutation):
                validate_one_step(state, bad, train, panels, anchors)

    def test_rejection_keeps_prefix_and_actual_error_does_not_adopt_later_certificate(self):
        for actual_error in (False, True):
            state, train, panels, anchors, _ = fixture()
            before, calls = state.digest(), []
            def injected(*args, **kwargs):
                result = repair_sequence(*args, **kwargs)
                calls.append(result)
                if len(calls) == 2:
                    if actual_error:
                        result["record"]["attempts"][0]["record"]["step_records"][0]["error"] = {
                            "type": "RuntimeError", "message": "injected paid attempt failure"}
                    else:
                        result["record"].update(status="rejected", certified=False)
                return result
            with patch("cell_field_remaining_v8.repair_sequence", side_effect=injected):
                result = run(state, train, panels, anchors)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["record"]["completed_steps"], 1)
            self.assertEqual(result["state"].digest(), calls[0]["state"].digest())
            self.assertEqual(result["record"]["status"], "not_executed_unresolved" if actual_error else "not_executed_rejected")
            self.assertIsNone(result["record"]["common_J32"])
            self.assertEqual(result["record"]["steps"][1]["committed_steps"], 0)
            self.assertEqual(result["record"]["steps"][1]["repair"], calls[1]["record"])
            self.assertEqual(state.digest(), before)

    def test_changed_original_anchor_or_provenance_rejected_before_control(self):
        state, train, panels, anchors, _ = fixture()
        with self.assertRaisesRegex(ValueError, "original complete warmup"):
            run(state, train, panels, anchors+1e-8)
        with self.assertRaises(ValueError):
            execute_remaining(state, train, panels, panels, anchors, "myopic_h1",
                controller_protocol_sha256="b"*64, controller_source_sha256="not-a-pin")


if __name__ == "__main__":
    unittest.main()
