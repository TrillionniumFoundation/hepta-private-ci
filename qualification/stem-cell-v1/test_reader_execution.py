import copy
import os
import unittest
from unittest.mock import patch

import torch
from torch import nn

from group_critic import fit_critic
from group_loop import parameter_digest
from group_reader import Reader
from reader_execution import execute_reader, observed_verifier_feedback


class StepFixture(nn.Module):
    """Procedural control fixture only; tests do not claim model efficacy."""

    def __init__(self, confidence=8.):
        super().__init__()
        self.input_dim, self.hidden_dim, self.max_hops = 8, 8, 8
        self.bias = nn.Parameter(torch.tensor([confidence, 0.]))
        self.seen_feedback = []

    def step(self, facts, query, state=None, feedback=None, mask=None):
        self.seen_feedback.append(None if feedback is None else feedback.detach().clone())
        previous = query.new_zeros(1, 8) if state is None else state
        return previous * .5 + .1, self.bias.unsqueeze(0) + query[:, :2] * 0


class CriticFixture:
    def __init__(self, stop=.1, continuation=.9):
        self.model = nn.Linear(6, 2).eval().requires_grad_(False)
        self.params_sha256 = parameter_digest(self.model)
        self.metadata = dict(cutoff_ns=1, empirical_max_absolute_residual=[0., 0.],
                             fixture_only=True)
        self.stop, self.continuation = stop, continuation

    def assert_frozen(self):
        if parameter_digest(self.model) != self.params_sha256:
            raise ValueError("changed critic")

    def predict(self, features):
        self.model(torch.tensor([features], dtype=torch.float32))
        return dict(stop_upper=self.stop, continue_lower=self.continuation,
                    stop_probability=self.stop, continue_probability=self.continuation)


class ReaderExecutionTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(3)
        torch.set_num_threads(1)
        self.public = dict(facts=torch.randn(1, 4, 8), query=torch.randn(1, 8),
                           mask=torch.ones(1, 4, dtype=torch.bool),
                           feature_sha256="a" * 64, source_sha256="b" * 64)
        self.bounds = dict(reader_source_groups=["train-reader"],
                           verifier_source_groups=["train-verifier"],
                           duration_upper_ns=1_000_000_000, formula_work_upper=1_000_000,
                           cost_per_formula_flop=0., cost_per_latency_ns=0.)

    def run_mode(self, mode, model=None, verifier=None, critic=None, **kwargs):
        model = model if model is not None else StepFixture().eval().requires_grad_(False)
        verifier = verifier if verifier is not None else StepFixture().eval().requires_grad_(False)
        return execute_reader(self.public, model, verifier, critic or CriticFixture(),
                              mode=mode, profile_bounds=self.bounds, **kwargs)

    def test_fixed_depth_retains_feedback_and_delays_model_agreement(self):
        model = StepFixture().eval().requires_grad_(False)
        result = self.run_mode("fixed", model=model)
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["calls"], 8)
        self.assertTrue(all(row["accepted"] for row in result["verifier_observations"]))
        self.assertIsNone(model.seen_feedback[0])
        self.assertEqual(model.seen_feedback[1].shape, (1, 4))
        self.assertGreater(model.seen_feedback[1][0, 0].item(), .9)
        self.assertEqual(result["artifact_digests_before"], result["artifact_digests_after"])
        self.assertEqual(result["work_observation"]["unknown_operators"], {})
        self.assertFalse(result["verifier_acceptance_is_semantic_truth"])

    def test_static_adaptive_disabled_and_reset_have_distinct_execution(self):
        self.assertEqual(self.run_mode("static")["steps"], 1)
        low_confidence = StepFixture(.1).eval().requires_grad_(False)
        adaptive = self.run_mode("adaptive", verifier=low_confidence, critic=CriticFixture(.9, .1))
        self.assertEqual(adaptive["steps"], 1)
        self.assertEqual(adaptive["status"], "utility_stop")
        disabled = self.run_mode("no_verifier")
        self.assertEqual(disabled["steps"], 3)
        self.assertTrue(all(not row["enabled"] for row in disabled["verifier_observations"]))
        recurrent, reset = self.run_mode("fixed"), self.run_mode("reset_state")
        self.assertNotEqual(recurrent["step_records"][-1]["state_sha256"],
                            reset["step_records"][-1]["state_sha256"])
        self.assertEqual(len({r["state_sha256"] for r in reset["step_records"]}), 1)

    def test_empty_evidence_never_gets_verifier_acceptance(self):
        self.public["mask"].zero_()
        result = self.run_mode("fixed")
        self.assertTrue(all(not r["accepted"] for r in result["verifier_observations"]))
        observed = observed_verifier_feedback(torch.tensor([[9., 0.]]), 0, False)
        self.assertTrue(observed["agreement"])
        self.assertFalse(observed["accepted"])
        self.assertEqual(observed["feedback"][0, 3].item(), 0.)

    def test_rejects_outcome_injection_overlap_unfrozen_and_alias(self):
        original = copy.copy(self.public)
        for key in ("label", "target", "case", "realized_outcome"):
            self.public = {**original, key: 1}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_mode("fixed")
        self.public = original
        self.bounds["verifier_source_groups"] = ["train-reader"]
        with self.assertRaises(ValueError):
            self.run_mode("fixed")
        self.bounds["verifier_source_groups"] = ["train-verifier"]
        with self.assertRaises(ValueError):
            self.run_mode("fixed", model=StepFixture())
        model = StepFixture().eval().requires_grad_(False)
        with self.assertRaises(ValueError):
            self.run_mode("fixed", model=model, verifier=model)

    def test_real_reader_and_fitted_critic_execute_under_strict_meter(self):
        def rows(split, prefix):
            return [dict(features=[i / 10.] * 6, stop_success=bool(i % 2),
                         continue_success=not bool(i % 2), source_group=prefix + str(i),
                         split=split) for i in range(10)]
        critic = fit_critic(rows("validation_fit", "f"), rows("validation_calibration", "c"),
                            cutoff_ns=1, steps=2)
        model = Reader(8, 16).eval().requires_grad_(False)
        verifier = Reader(8, 16).eval().requires_grad_(False)
        result = self.run_mode("adaptive", model=model, verifier=verifier, critic=critic)
        self.assertGreater(result["work_observation"]["phase_flops"]["search"], 0)
        self.assertEqual(result["work_observation"]["unknown_operators"], {})
        self.assertEqual(result["artifact_digests_before"], result["artifact_digests_after"])

    def test_native_callback_uses_prospective_bounds_and_binds_actual_context(self):
        decisions = []
        def native(request, binary, **kwargs):
            decisions.append(request)
            return dict(continue_computation=True, reason="fixture", child_cpu_ns=7,
                        child_wall_ns=11, native_executed=False, reference_match=True)
        verifier = StepFixture(.1).eval().requires_grad_(False)
        with patch("native_group_control.run_native_control", side_effect=native):
            result = self.run_mode("native_ndu", verifier=verifier, native_binary="fixture")
        self.assertEqual(result["steps"], 3)
        self.assertEqual(len(decisions), 2)
        self.assertEqual(result["native_child_cpu_ns"], 14)
        self.assertIsNone(result["end_to_end_formula_flops"])
        self.assertIsNone(result["native_child_formula_work"])
        self.assertTrue(result["native_wall_already_in_ledger"])
        for d in result["native_control_decisions"]:
            self.assertEqual(d["context"]["verifier_sha256"], result["verifier_sha256"])
            self.assertTrue(d["realized_support_bounds_satisfied"])
            self.assertNotIn("terminal_outcome_sha256", d["request"])
        self.assertNotEqual(result["native_control_decisions"][0]["bindings"]["context_sha256"],
                            result["native_control_decisions"][1]["bindings"]["context_sha256"])

    def test_native_declared_future_bound_is_checked_after_the_actual_segment(self):
        self.bounds["formula_work_upper"] = 1
        verifier = StepFixture(.1).eval().requires_grad_(False)
        with patch("native_group_control.run_native_control", return_value={
                "continue_computation": True, "reason": "fixture", "child_cpu_ns": 0}):
            result = self.run_mode("native_ndu", verifier=verifier, native_binary="fixture")
        self.assertEqual(result["steps"], 2)
        self.assertTrue(result["native_support_violated"])
        self.assertFalse(result["native_control_decisions"][0]["realized_support_bounds_satisfied"])

    def test_unknown_native_child_cost_is_never_coerced_to_zero(self):
        verifier = StepFixture(.1).eval().requires_grad_(False)
        with patch("native_group_control.run_native_control", return_value={
                "continue_computation": False, "reason": "native_control_failed",
                "child_cpu_ns": None, "child_wall_ns": 12, "native_attempted": True,
                "native_executed": False, "reference_match": False}):
            result = self.run_mode("native_ndu", verifier=verifier, native_binary="fixture")
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["status"], "utility_stop")
        self.assertIsNone(result["native_child_cpu_ns"])
        self.assertIsNone(result["request_costs"]["accounted_cpu_ns"])
        self.assertTrue(result["native_controller_failed_closed"])
        self.assertFalse(result["native_controller_execution_qualified"])
        plain = self.run_mode("static")
        self.assertEqual(plain["native_child_cpu_ns"], 0)

    @unittest.skipUnless(os.environ.get("HEPTA_NATIVE_CONTROL_BINARY"), "explicit native binary not supplied")
    def test_real_native_q32_binary_controls_a_live_recurrent_reader(self):
        verifier = StepFixture(.1).eval().requires_grad_(False)
        result = self.run_mode("native_ndu", verifier=verifier,
                               native_binary=os.environ["HEPTA_NATIVE_CONTROL_BINARY"])
        self.assertEqual(result["steps"], 3)
        self.assertTrue(all(d["native_executed"] and d["reference_match"]
                            for d in result["native_control_decisions"]))
        self.assertGreater(result["native_child_cpu_ns"], 0)
        self.assertFalse(result["native_production_owner_integrated"])


if __name__ == "__main__":
    unittest.main()
