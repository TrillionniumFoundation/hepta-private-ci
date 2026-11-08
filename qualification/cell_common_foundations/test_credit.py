"""Independent numerical and invariant checks for the credit reference."""

import json
import math
import sys
import unittest
from unittest import mock
import numpy as np

try:
    from .credit import (
        Model,
        Rule,
        METHODS,
        make_model,
        make_rule,
        forward,
        gradient,
        finite_difference,
        compare_gradients,
        flatten,
        propose,
        intervene_messages,
        causal_probe,
        copy_episode,
        credit_attempt_spec,
        run_credit_attempt,
        run_credit_panel,
    )
except ImportError:
    from credit import (
        Model,
        Rule,
        METHODS,
        make_model,
        make_rule,
        forward,
        gradient,
        finite_difference,
        compare_gradients,
        flatten,
        propose,
        intervene_messages,
        causal_probe,
        copy_episode,
        credit_attempt_spec,
        run_credit_attempt,
        run_credit_panel,
    )


try:
    from .protocol import AttemptSpec, compare_profiles, summarize_attempts
except ImportError:
    from protocol import AttemptSpec, compare_profiles, summarize_attempts

credit_module = sys.modules[gradient.__module__]


class CreditTests(unittest.TestCase):
    def setUp(self):
        self.model = make_model(101)
        self.rule = make_rule(self.model)
        self.episode = copy_episode(np.random.default_rng(42), 8)

    def calculate(self, method, rule=None):
        x, y, feedback, message = self.episode
        return gradient(self.model, x, y, feedback, method, rule or self.rule, message)

    def test_bptt_matches_central_difference_all_layers(self):
        x, y, feedback, messages = self.episode
        exact = self.calculate("bptt")["gradients"]
        numerical = finite_difference(self.model, x, y, feedback, messages)
        for name in exact:
            np.testing.assert_allclose(
                exact[name], numerical[name], rtol=3e-5, atol=3e-10
            )

    def test_dense_feedback_bptt_matches_independent_objective(self):
        x, y, feedback, messages = self.episode
        feedback = np.full(len(x), 1 / len(x))
        exact = gradient(self.model, x, y, feedback, "bptt", self.rule, messages)[
            "gradients"
        ]
        numerical = finite_difference(self.model, x, y, feedback, messages)
        np.testing.assert_allclose(
            flatten(exact), flatten(numerical), rtol=3e-5, atol=3e-10
        )

    def test_full_chunk_equals_bptt_and_short_chunk_loses_early_input_path(self):
        model = Model([[0.2]], [[0.8]], [0.05], [[0.5]], (0,))
        x = np.zeros((8, 1))
        x[0] = 0.5
        target = np.full((8, 1), 0.4)
        feedback = np.zeros(8)
        feedback[-1] = 1
        exact = gradient(model, x, target, feedback, "bptt")
        full = gradient(
            model, x, target, feedback, "tbptt", make_rule(model, truncation=8)
        )
        short = gradient(
            model, x, target, feedback, "tbptt", make_rule(model, truncation=2)
        )
        np.testing.assert_array_equal(
            flatten(exact["gradients"]), flatten(full["gradients"])
        )
        self.assertGreater(abs(exact["gradients"]["input"][0, 0]), 1e-6)
        self.assertEqual(short["gradients"]["input"][0, 0], 0)

    def test_single_unit_local_derivative_matches_oracle_without_projection(self):
        model = Model([[0.15]], [[0.25]], [0.1], [[0.4]], (0,))
        x = np.array([[0.2], [-0.1], [0.3]])
        y = np.full((3, 1), 0.3)
        feedback = np.array([0.0, 0.0, 1.0])
        oracle = gradient(model, x, y, feedback, "bptt")
        local = gradient(model, x, y, feedback, "type_specific")
        self.assertEqual(local["eligibility_projection_count"], 0)
        np.testing.assert_allclose(
            flatten(local["gradients"]), flatten(oracle["gradients"]), atol=1e-14
        )

    def test_cross_unit_local_rule_is_not_mislabeled_exact(self):
        local = self.calculate("type_specific")
        oracle = self.calculate("bptt")
        comparison = compare_gradients(local["gradients"], oracle["gradients"])
        self.assertGreater(comparison["relative_l2_error"], 0.05)
        self.assertLessEqual(local["maximum_eligibility_l1"], 4 + 1e-12)
        self.assertGreater(local["eligibility_projection_count"], 0)

    def test_credit_graph_change_preserves_execution_but_changes_credit(self):
        alternate = Rule(
            self.rule.group_map,
            np.eye(7),
            self.rule.feedback_mask,
            diffusion_steps=self.rule.diffusion_steps,
        )
        original = self.calculate("diffusion")
        changed = self.calculate("diffusion", alternate)
        np.testing.assert_array_equal(original["outputs"], changed["outputs"])
        np.testing.assert_array_equal(original["states"], changed["states"])
        self.assertNotEqual(
            original["credit_transport_digest"], changed["credit_transport_digest"]
        )
        self.assertGreater(
            np.linalg.norm(
                flatten(original["gradients"]) - flatten(changed["gradients"])
            ),
            1e-8,
        )

    def test_shuffled_transport_keeps_stochastic_contract(self):
        result = self.calculate("shuffled_diffusion")
        original = self.calculate("diffusion")
        np.testing.assert_array_equal(result["outputs"], original["outputs"])
        self.assertNotEqual(
            result["credit_transport_digest"], original["credit_transport_digest"]
        )
        self.assertLessEqual(result["maximum_eligibility_l1"], 4 + 1e-12)

    def test_zero_modulator_has_no_update_and_null_cosine(self):
        x, _, feedback, messages = self.episode
        _, target = forward(self.model, x, messages)
        for method in METHODS:
            result = gradient(
                self.model, x, target, feedback, method, self.rule, messages
            )
            self.assertEqual(np.count_nonzero(flatten(result["gradients"])), 0)
            self.assertIsNone(
                compare_gradients(result["gradients"], result["gradients"])["cosine"]
            )
            candidate, receipt = propose(self.model, result["gradients"])
            self.assertEqual(self.model.digest, candidate.digest)
            self.assertTrue(receipt["no_update"])

    def test_no_feedback_location_means_zero_local_update(self):
        rule = Rule(self.rule.group_map, self.rule.credit_graph, np.zeros(7))
        for method in METHODS[2:]:
            result = self.calculate(method, rule)
            self.assertEqual(np.count_nonzero(flatten(result["gradients"])), 0)

    def test_sparse_feedback_and_diffusion_have_distinct_updates(self):
        rule = make_rule(self.model, sparse_feedback=True)
        local = self.calculate("type_specific", rule)
        diffuse = self.calculate("diffusion", rule)
        np.testing.assert_array_equal(local["outputs"], diffuse["outputs"])
        self.assertGreater(
            np.linalg.norm(flatten(local["gradients"]) - flatten(diffuse["gradients"])),
            1e-8,
        )

    def test_proposal_uses_actual_denominators_and_preserves_selected(self):
        before = self.model.digest
        gradients = {
            name: np.full_like(value, 100)
            for name, value in self.model.parameters().items()
        }
        candidate, receipt = propose(self.model, gradients)
        self.assertEqual(before, self.model.digest)
        self.assertNotEqual(before, candidate.digest)
        self.assertTrue(
            all(x <= 0.005 + 1e-12 for x in receipt["layer_relative_norms"].values())
        )
        self.assertLessEqual(receipt["global_relative_norm"], 0.0025 + 1e-12)
        self.assertFalse(receipt["native_adoption_qualified"])
        with self.assertRaises(ValueError):
            self.model.input[0, 0] = 1
        zero_bias = Model(
            self.model.input,
            self.model.recurrent,
            np.zeros(7),
            self.model.head,
            self.model.cell_types,
        )
        zero_candidate, _ = propose(zero_bias, gradients)
        np.testing.assert_array_equal(zero_candidate.bias, zero_bias.bias)

    def test_tiny_selected_parameters_and_gradients_respect_actual_trust_bounds(self):
        scale = 1e-200
        model = Model([[scale]], [[2 * scale]], [3 * scale], [[0.25]], (0,))
        gradients = {
            name: np.full_like(value, scale)
            for name, value in model.parameters().items()
        }
        selected_digest = model.digest
        candidate, receipt = propose(model, gradients, learning_rate=1.0)
        actual_scaled = []
        baseline_scaled = []
        for name, selected in model.parameters().items():
            # Independent well-scaled oracle, so this test cannot share the bug.
            change = (getattr(candidate, name) - selected) / scale
            baseline = selected / scale
            ratio = math.hypot(*change.ravel()) / math.hypot(*baseline.ravel())
            self.assertGreater(ratio, 0)
            self.assertLessEqual(ratio, 0.005 + 1e-12)
            self.assertAlmostEqual(
                receipt["layer_relative_norms"][name], ratio, places=14
            )
            actual_scaled.extend(change.ravel())
            baseline_scaled.extend(baseline.ravel())
        global_ratio = math.hypot(*actual_scaled) / math.hypot(*baseline_scaled)
        self.assertGreater(global_ratio, 0)
        self.assertLessEqual(global_ratio, 0.0025 + 1e-12)
        self.assertAlmostEqual(receipt["global_relative_norm"], global_ratio, places=14)
        self.assertFalse(receipt["no_update"])
        self.assertEqual(model.digest, selected_digest)

    def test_tiny_gradients_cannot_modify_a_zero_selected_baseline(self):
        model = Model([[0.0]], [[0.0]], [0.0], [[0.25]], (0,))
        gradients = {
            name: np.full_like(value, 1e-200)
            for name, value in model.parameters().items()
        }
        candidate, receipt = propose(model, gradients, learning_rate=1.0)
        np.testing.assert_array_equal(
            flatten(candidate.parameters()), flatten(model.parameters())
        )
        self.assertEqual(candidate.digest, model.digest)
        self.assertTrue(receipt["no_update"])
        self.assertEqual(receipt["global_relative_norm"], 0.0)

    def test_gradient_diagnostics_remain_defined_at_small_and_large_scales(self):
        for scale in (1e-200, 1e200):
            with self.subTest(scale=scale):
                reference = {
                    "input": np.array([[scale]]),
                    "recurrent": np.array([[2 * scale]]),
                    "bias": np.array([3 * scale]),
                }
                estimate = {name: values * 0.5 for name, values in reference.items()}
                result = compare_gradients(estimate, reference)
                self.assertAlmostEqual(
                    result["reference_l2"] / scale, math.sqrt(14), places=13
                )
                self.assertAlmostEqual(
                    result["estimate_l2"] / scale, math.sqrt(14) / 2, places=13
                )
                self.assertAlmostEqual(result["cosine"], 1.0, places=13)
                self.assertAlmostEqual(result["relative_l2_error"], 0.5, places=13)

    def test_unrepresentable_norm_is_rejected_without_a_zero_update_receipt(self):
        huge = {
            name: np.full_like(value, np.finfo(np.float64).max)
            for name, value in self.model.parameters().items()
        }
        with self.assertRaisesRegex(ArithmeticError, "not representable"):
            propose(self.model, huge, learning_rate=1.0)
        with self.assertRaisesRegex(ArithmeticError, "not representable"):
            compare_gradients(huge, huge)

    def test_actual_zero_layer_baseline_is_rechecked_after_candidate_construction(self):
        model = Model([[0.2]], [[0.4]], [0.0], [[0.25]], (0,))
        gradients = {
            name: np.zeros_like(value) for name, value in model.parameters().items()
        }
        real_model = credit_module.Model

        def injected_candidate_drift(**values):
            values["bias"] = np.asarray(values["bias"]) + 1e-200
            return real_model(**values)

        with mock.patch.object(
            credit_module, "Model", side_effect=injected_candidate_drift
        ):
            with self.assertRaisesRegex(ArithmeticError, "zero-norm baseline"):
                propose(model, gradients)

    def test_model_and_rule_defensively_copy_inputs(self):
        source = np.array([[0.1]])
        model = Model(source, [[0.3]], [0.05], [[0.4]], (0,))
        digest = model.digest
        source[0, 0] = 2
        self.assertEqual(model.digest, digest)
        graph = np.eye(7)
        rule = Rule(self.rule.group_map, graph, np.ones(7))
        old = rule.digest
        graph[0, 0] = 0
        self.assertEqual(rule.digest, old)

    def test_interventions_recompute_forward_and_updates(self):
        x, y, feedback, message = self.episode
        before = message.copy()
        probe = causal_probe(self.model, x, y, feedback, message, 1, "bptt", self.rule)
        np.testing.assert_array_equal(message, before)
        for row in probe["interventions"]:
            self.assertGreater(row["final_output_difference_l2"], 1e-7)
            self.assertGreater(row["gradient_difference_l2"], 1e-7)
            self.assertGreater(row["candidate_difference_l2"], 1e-9)
        delayed = intervene_messages(message, 1, "delay", delay=99)
        np.testing.assert_array_equal(delayed, np.zeros_like(message))
        masked = intervene_messages(message, 1, "mask")
        np.testing.assert_array_equal(masked, delayed)

    def test_invalid_contracts_fail_closed(self):
        with self.assertRaises(ValueError):
            Rule(np.ones((7, 2)), np.eye(7), np.ones(7))
        with self.assertRaises(ValueError):
            Rule(self.rule.group_map, np.ones((7, 7)), np.ones(7))
        with self.assertRaises(ValueError):
            Rule(self.rule.group_map, np.eye(7), np.ones(7), eligibility_l1_bound=5)
        with self.assertRaises(ValueError):
            Model([[np.nan]], [[1]], [0.1], [[0.1]], (0,))
        with self.assertRaises(ValueError):
            self.calculate("unrecognized")
        with self.assertRaises(ValueError):
            propose(
                self.model,
                self.calculate("bptt")["gradients"],
                global_relative_bound=0.01,
            )
        x, y, feedback, message = self.episode
        with self.assertRaises(ValueError):
            gradient(self.model, x, y, np.zeros_like(feedback), messages=message)
        with self.assertRaises(ValueError):
            intervene_messages(message, 1, "replace", replacement=[1])

    def test_independent_seed_panel_has_complete_denominator(self):
        result = run_credit_panel(seeds=(3, 5), updates=2, horizon=6)
        self.assertEqual(len(result["rows"]), 2 * 2 * len(METHODS))
        self.assertEqual(len(result["gradient_diagnostics"]), len(result["rows"]))
        self.assertEqual(len(result["causal_interventions"]), 2 * len(METHODS))
        self.assertEqual(
            len({row["initial_model_digest"] for row in result["rows"]}), 2
        )
        self.assertTrue(all(len(row["train_losses"]) == 2 for row in result["rows"]))
        self.assertTrue(
            all(row["physical_energy_joules"] is None for row in result["rows"])
        )
        self.assertEqual(result["efficacy_claim"], "withheld")
        self.assertEqual(result["completed_training_runs"], 24)
        self.assertEqual(result["failed_training_runs"], 0)
        self.assertEqual(result["completed_optimizer_updates"], 48)
        roster = [
            AttemptSpec(
                **{k: spec[k] for k in ("attempt_id", "family", "method", "seed")}
            )
            for spec in result["roster"]
        ]
        summary = summarize_attempts(roster, result["attempts"])
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["planned_attempts"], 24)
        for row in result["rows"]:
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["completed_training_observations"], 12)
            self.assertEqual(row["comparison_profile"]["training_observations"], 12)
        json.dumps(result, allow_nan=False)

    def test_panel_inputs_rejected_before_any_attempt(self):
        cases = [
            {"seeds": (True, 2)},
            {"seeds": (-1, 2)},
            {"seeds": (2, 2)},
            {"seeds": (1.0, 2)},
            {"seeds": (2,)},
            {"seeds": "12"},
            {"updates": 0},
            {"updates": 2.5},
            {"updates": True},
            {"horizon": 1},
            {"horizon": 0},
            {"horizon": -1},
            {"horizon": 2.5},
            {"horizon": True},
            {"horizon": 4097},
        ]
        with mock.patch.object(credit_module, "run_credit_attempt") as execute:
            for invalid in cases:
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    run_credit_panel(**invalid)
            execute.assert_not_called()
        for horizon in (0, 1, True, 2.5):
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                copy_episode(None, horizon)

    def test_preregistered_single_attempt_profile_and_observations_match(self):
        planned = credit_attempt_spec(
            7, "type_specific", "sparse", updates=2, horizon=5
        )
        with mock.patch.object(credit_module, "gradient") as compute:
            same = credit_attempt_spec(
                7, "type_specific", "sparse", updates=2, horizon=5
            )
            compute.assert_not_called()
        self.assertEqual(planned, same)
        self.assertEqual(planned["budget"]["tuning_trials"], 0)
        self.assertEqual(planned["budget"]["fixed_configurations"], 1)
        left = run_credit_attempt(7, "type_specific", "sparse", updates=2, horizon=5)
        right = run_credit_attempt(7, "diffusion", "sparse", updates=2, horizon=5)
        self.assertEqual(left["attempt_id"], planned["attempt_id"])
        self.assertEqual(left["status"], "completed")
        self.assertEqual(left["completed_updates"], 2)
        self.assertEqual(left["completed_training_observations"], 10)
        self.assertEqual(
            left["source_identity_at_start"], left["source_identity_at_end"]
        )
        self.assertTrue(
            compare_profiles(left["comparison_profile"], right["comparison_profile"])[
                "matched"
            ]
        )
        self.assertEqual(
            left["training_observation_digest"], right["training_observation_digest"]
        )
        self.assertFalse(left["comparison_profile"]["ndu_enabled"])
        self.assertEqual(left["comparison_profile"]["tuning_trials"], 0)
        self.assertEqual(left["comparison_profile"]["fixed_configurations"], 1)
        self.assertEqual(
            left["comparison_profile"]["initial_model_digest"],
            right["comparison_profile"]["initial_model_digest"],
        )
        self.assertEqual(
            left["comparison_profile"]["source_digest"],
            left["source_identity_at_start"]["digest"],
        )
        self.assertLess(
            left["result"]["common_map_l1"], left["result"]["mean_group_map_l1"]
        )
        self.assertFalse(left["result"]["three_factor_optimality_claim"])

    def test_proposal_failure_retains_consumed_observations_and_completed_updates(self):
        real_propose = credit_module.propose
        calls = 0

        def fail_third(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise ArithmeticError("injected proposal failure")
            return real_propose(*args, **kwargs)

        with mock.patch.object(credit_module, "propose", side_effect=fail_third):
            record = run_credit_attempt(9, "bptt", updates=4, horizon=5)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["failure_stage"], "training")
        self.assertIn("injected proposal failure", record["reason"])
        self.assertEqual(record["completed_updates"], 2)
        self.assertEqual(record["training_gradient_calls_completed"], 3)
        self.assertEqual(record["completed_training_observations"], 15)
        self.assertEqual(record["budget"]["training_observations"], 20)
        self.assertEqual(record["comparison_profile"]["optimizer_updates"], 2)
        self.assertEqual(len(record["result"]["train_losses"]), 3)
        self.assertEqual(len(record["result"]["update_receipts"]), 2)
        self.assertEqual(
            record["result"]["final_model_digest"],
            record["result"]["update_receipts"][-1]["candidate_digest"],
        )
        self.assertIsNone(record["result"]["mean_eval_loss_change"])
        self.assertGreater(record["result"]["train_wall_seconds"], 0)
        json.dumps(record, allow_nan=False)

    def test_incomplete_gradient_observation_count_is_explicit_lower_bound(self):
        real_gradient = credit_module.gradient
        calls = 0

        def fail_fourth(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise FloatingPointError("injected gradient failure")
            return real_gradient(*args, **kwargs)

        with mock.patch.object(credit_module, "gradient", side_effect=fail_fourth):
            record = run_credit_attempt(9, "bptt", updates=3, horizon=5)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["completed_updates"], 1)
        self.assertEqual(record["training_gradient_calls_started"], 2)
        self.assertEqual(record["training_gradient_calls_completed"], 1)
        self.assertEqual(record["completed_training_observations"], 5)
        self.assertEqual(
            record["training_observation_coverage"],
            "lower_bound_incomplete_gradient_call",
        )

    def test_failed_method_remains_in_roster_and_later_attempts_execute(self):
        real_propose = credit_module.propose
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("first attempt fails")
            return real_propose(*args, **kwargs)

        with mock.patch.object(credit_module, "propose", side_effect=fail_once):
            result = run_credit_panel(seeds=(2, 4), updates=1, horizon=3)
        self.assertEqual(len(result["roster"]), 24)
        self.assertEqual(len(result["attempts"]), 24)
        self.assertEqual(len(result["rows"]), 24)
        self.assertEqual(result["failed_training_runs"], 1)
        self.assertEqual(result["completed_training_runs"], 23)
        self.assertEqual(result["completed_optimizer_updates"], 23)
        self.assertEqual(result["rows"][0]["status"], "failed")
        self.assertEqual(result["rows"][-1]["status"], "completed")
        self.assertIn("first attempt fails", result["rows"][0]["reason"])
        roster = [
            AttemptSpec(
                **{k: spec[k] for k in ("attempt_id", "family", "method", "seed")}
            )
            for spec in result["roster"]
        ]
        summary = summarize_attempts(roster, result["attempts"])
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["counts"]["failed"], 1)

    def test_control_flow_interruptions_are_not_converted_to_failures(self):
        for interruption in (KeyboardInterrupt, SystemExit):
            with self.subTest(interruption=interruption.__name__):
                with mock.patch.object(
                    credit_module, "gradient", side_effect=interruption("stop")
                ):
                    with self.assertRaises(interruption):
                        run_credit_attempt(1, "bptt", updates=1, horizon=3)

    def test_mid_attempt_source_change_refuses_completion_after_preserving_work(self):
        original = credit_module._IMPORTED_SOURCE
        altered = {"digest": "changed", "files": {}}
        with mock.patch.object(
            credit_module, "source_inventory", side_effect=[original, altered]
        ):
            record = run_credit_attempt(12, "bptt", updates=1, horizon=3)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["failure_stage"], "final_source_identity")
        self.assertEqual(record["completed_updates"], 1)
        self.assertEqual(record["completed_initial_evaluation_episodes"], 12)
        self.assertEqual(record["completed_final_evaluation_episodes"], 12)
        self.assertEqual(record["source_identity_at_end"], altered)
        self.assertIn("source files changed", record["reason"])


if __name__ == "__main__":
    unittest.main()
