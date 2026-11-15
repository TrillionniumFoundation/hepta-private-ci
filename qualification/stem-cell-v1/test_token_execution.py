import copy
import os
import unittest
from unittest.mock import patch

import torch

from group_critic import fit_critic
from group_loop import parameter_digest
from token_execution import execute_token_reader
from token_reader import TokenReader


class TokenFixture(TokenReader):
    """Procedural recurrence fixture; it establishes no learned capability."""

    def __init__(self):
        super().__init__(8, 8)
        self.preparations, self.feedbacks = 0, []

    def prepare(self, *features):
        self.preparations += 1
        return super().prepare(*features)

    def step_prepared(self, prepared, state=None, feedback=None):
        self.feedbacks.append(None if feedback is None else feedback.clone())
        query = prepared["query"]
        state = query.new_zeros(1, 8) if state is None else state
        return state * .5 + .1, query[:, :2] * 0, None, None


class CriticFixture:
    def __init__(self):
        self.model = torch.nn.Linear(6, 2).eval().requires_grad_(False)
        self.params_sha256 = parameter_digest(self.model)
        self.metadata = dict(cutoff_ns=1, source_groups=dict(fit=["critic-fit"], calibration=["critic-calib"]))

    def assert_frozen(self):
        if parameter_digest(self.model) != self.params_sha256:
            raise ValueError("changed critic")

    def predict(self, features):
        self.model(torch.tensor([features]))
        return dict(stop_upper=.1, continue_lower=.9, stop_probability=.1, continue_probability=.9)


class TokenExecutionTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(13)
        self.public = dict(facts=torch.randn(1, 3, 4, 8), question=torch.randn(1, 5, 8),
            candidate=torch.randn(1, 2, 8), fact_mask=torch.ones(1, 3, 4, dtype=torch.bool),
            question_mask=torch.ones(1, 5, dtype=torch.bool), candidate_mask=torch.ones(1, 2, dtype=torch.bool),
            sentence_indices=torch.tensor([[0, 1, 2]]), feature_sha256="a" * 64, source_sha256="b" * 64)
        self.bounds = dict(reader_source_groups=["reader"], verifier_source_groups=["verifier"],
                           cost_per_formula_flop=0., cost_per_latency_ns=0.)

    def run_mode(self, mode, model=None, verifier=None, **kwargs):
        self.model = model if model is not None else TokenFixture().eval().requires_grad_(False)
        self.verifier = verifier if verifier is not None else TokenFixture().eval().requires_grad_(False)
        return execute_token_reader(self.public, self.model, self.verifier, mode=mode,
                                    profile_bounds=self.bounds, **kwargs)

    def test_fixed_recurrence_projects_once_and_keeps_observable_feedback(self):
        result = self.run_mode("fixed3", collect_critic_features=True)
        self.assertEqual(result["steps"], 3)
        self.assertEqual((self.model.preparations, self.verifier.preparations), (1, 1))
        self.assertIsNone(self.model.feedbacks[0])
        self.assertEqual(self.model.feedbacks[1].tolist(), [[.5, .5, 1., 1.]])
        self.assertEqual([len(r.get("critic_features", [])) for r in result["step_records"]], [6, 6, 0])
        self.assertEqual(result["artifact_digests_before"], result["artifact_digests_after"])
        self.assertGreaterEqual(result["request_costs"]["self_cpu_ns"], result["work_observation"]["cpu_ns"])
        self.assertFalse(result["verifier_acceptance_is_semantic_truth"])

    def test_fixed1_reset_and_disabled_verifier_are_distinct_actual_paths(self):
        self.assertEqual(self.run_mode("fixed1")["steps"], 1)
        recurrent = self.run_mode("fixed3")["step_records"]
        reset = self.run_mode("reset3")["step_records"]
        self.assertNotEqual(recurrent[-1]["state_sha256"], reset[-1]["state_sha256"])
        self.assertEqual(len({row["state_sha256"] for row in reset}), 1)
        result = self.run_mode("no_verifier")
        self.assertEqual(self.verifier.preparations, 0)
        self.assertEqual(self.model.feedbacks[1].tolist(), [[0., 0., 0., 0.]])
        self.assertEqual(result["request_costs"]["native_child_cpu_ns"], 0)

    def test_public_boundary_rejects_gold_nonfinite_and_source_overlap(self):
        original = copy.copy(self.public)
        for extra in ("label", "target", "evidence_sentence_indices"):
            self.public = {**original, extra: 1}
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.run_mode("fixed1")
        self.public = original
        self.public["facts"][0, 0, 0, 0] = float("nan")
        with self.assertRaises(ValueError):
            self.run_mode("fixed1")
        self.public["facts"][0, 0, 0, 0] = 0.
        self.bounds["verifier_source_groups"] = ["reader"]
        with self.assertRaises(ValueError):
            self.run_mode("fixed1")

    def test_real_token_reader_and_fitted_frozen_critic_have_complete_aten_coverage(self):
        def rows(split, prefix):
            return [dict(features=[i / 10.] * 6, stop_success=bool(i % 2),
                         continue_success=not bool(i % 2), split=split, source_group=prefix + str(i))
                    for i in range(4)]
        critic = fit_critic(rows("validation_fit", "f"), rows("validation_calibration", "c"), cutoff_ns=1, steps=2)
        model = TokenReader(8, 8).eval().requires_grad_(False)
        verifier = TokenReader(8, 8).eval().requires_grad_(False)
        result = self.run_mode("fixed3", model, verifier, critic=critic)
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["work_observation"]["unknown_operators"], {})
        self.assertGreater(result["work_observation"]["phase_flops"]["search"], 0)

    def test_native_precedes_next_proposal_and_measures_actual_segment(self):
        def decision(request, binary, **kwargs):
            return dict(continue_computation=True, child_cpu_ns=7, child_wall_ns=9,
                        native_executed=False, reference_match=True)
        with patch("native_group_control.run_native_control", side_effect=decision):
            result = self.run_mode("native_ndu", critic=CriticFixture(), native_binary="fixture")
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["request_costs"]["native_child_cpu_ns"], 14)
        self.assertIsNone(result["request_costs"]["complete_formula_flops"])
        decisions = result["native_control_decisions"]
        self.assertEqual([d["context"]["step"] for d in decisions], [1, 2])
        self.assertTrue(all(d["realized_support_bounds_satisfied"] for d in decisions))
        self.assertTrue(all("terminal_outcome_sha256" not in d["request"] for d in decisions))
        self.bounds["formula_work_upper"] = 1
        with patch("native_group_control.run_native_control", side_effect=decision):
            violated = self.run_mode("native_ndu", critic=CriticFixture(), native_binary="fixture")
        self.assertEqual(violated["steps"], 2)
        self.assertTrue(violated["native_support_violated"])

    def test_unknown_native_cpu_remains_unknown_and_overlap_rejects(self):
        with patch("native_group_control.run_native_control", return_value=dict(
                continue_computation=False, child_cpu_ns=None, child_wall_ns=9,
                native_executed=False, reference_match=False)):
            result = self.run_mode("native_ndu", critic=CriticFixture(), native_binary="fixture")
        self.assertIsNone(result["request_costs"]["accounted_cpu_ns"])
        self.assertTrue(result["native_controller_failed_closed"])
        critic = CriticFixture()
        critic.metadata["source_groups"]["fit"] = ["reader"]
        with self.assertRaises(ValueError):
            self.run_mode("native_ndu", critic=critic, native_binary="fixture")

    @unittest.skipUnless(os.environ.get("HEPTA_NATIVE_CONTROL_BINARY"), "explicit native binary required")
    def test_existing_q32_binary_controls_real_token_callbacks(self):
        model = TokenReader(8, 8).eval().requires_grad_(False)
        verifier = TokenReader(8, 8).eval().requires_grad_(False)
        result = self.run_mode("native_ndu", model, verifier, critic=CriticFixture(),
                               native_binary=os.environ["HEPTA_NATIVE_CONTROL_BINARY"])
        self.assertEqual(result["steps"], 3)
        self.assertTrue(result["native_controller_execution_qualified"])
        self.assertGreater(result["request_costs"]["native_child_cpu_ns"], 0)
        self.assertEqual(result["work_observation"]["unknown_operators"], {})


if __name__ == "__main__":
    unittest.main()
