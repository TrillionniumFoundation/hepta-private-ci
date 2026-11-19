"""Small real-tensor checks of feedback gradients, matched calls and boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import torch
from torch.nn import functional as F

from binding_continuation import continuation_plan
from group_loop import parameter_digest
from revision_execution import ARMS, execute_revision, rollout_revision
from revision_training import RevisionTrainingFailure, fit_revision_pair, transition_counts
from token_protocol import build_binding_cases
from token_reader import TokenReader
from token_reader_training import TokenBatch


class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        torch.manual_seed(17)
        self.cases = build_binding_cases("train", groups=2, seed=41)
        self.natural_cases = build_binding_cases("train", groups=2, seed=47)
        self.binding = self.data(self.cases)
        self.natural = self.data(self.natural_cases)
        self.core = TokenReader(8, 8, max_hops=3).eval().requires_grad_(False)
        self.core.training_source_groups = tuple(sorted(set(self.binding.source_groups + self.natural.source_groups)))
        self.verifier = TokenReader(8, 8, max_hops=3).eval().requires_grad_(False)
        self.verifier.training_source_groups = ("independent-verifier-source",)
        path = Path(self.temp.name) / "verifier.pt"
        torch.save(self.verifier.state_dict(), path)
        self.provenance = dict(file_path=str(path), file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            model_sha256=parameter_digest(self.verifier), training_source_groups=list(self.verifier.training_source_groups),
            synthetic_trained=False)
        self.plan = continuation_plan(self.natural_cases, self.cases, seed=19, updates=1, batch_size=4)

    @staticmethod
    def data(cases):
        size = len(cases)
        return TokenBatch(torch.randn(size, 4, 2, 8), torch.randn(size, 3, 8), torch.randn(size, 2, 8),
            torch.ones(size, 4, 2, dtype=torch.bool), torch.ones(size, 3, dtype=torch.bool),
            torch.ones(size, 2, dtype=torch.bool), torch.tensor([c.label for c in cases]),
            tuple(c.source_hash for c in cases))

    def test_feedback_has_real_nonzero_gradient_and_verifier_remains_frozen(self):
        model = copy.deepcopy(self.core).train().requires_grad_(True)
        trace = rollout_revision(model, self.verifier, self.binding.features(), mode="real")
        for state in trace["state_trace"]:
            state.retain_grad()
        F.cross_entropy(trace["logits_trace"][-1], self.binding.targets).backward()
        self.assertGreater(model.proposal.weight.grad[:, -4:].abs().sum().item(), 0)
        self.assertGreater(model.update_gate.weight.grad[:, -4:].abs().sum().item(), 0)
        self.assertTrue(all(state.grad is not None and state.grad.abs().sum().item() > 0 for state in trace["state_trace"]))
        self.assertTrue(all(p.grad is None for p in self.verifier.parameters()))
        self.assertTrue(all(not value.requires_grad for value in trace["feedback_trace"]))
        self.assertTrue(all(event["feedback"] is None for event in trace["events"][:8]))
        self.assertTrue(all(event["feedback"] is not None for event in trace["events"][8:]))

    def test_zero_control_matches_original_three_step_math_and_has_zero_channel_gradient(self):
        model = copy.deepcopy(self.core).train().requires_grad_(True)
        trace = rollout_revision(model, self.verifier, self.binding.features(), mode="zero")
        original = model(*self.binding.features(), steps=3)
        torch.testing.assert_close(trace["logits_trace"][-1], original, rtol=0, atol=0)
        F.cross_entropy(trace["logits_trace"][-1], self.binding.targets).backward()
        self.assertEqual(model.proposal.weight.grad[:, -4:].abs().sum().item(), 0)
        self.assertEqual(model.update_gate.weight.grad[:, -4:].abs().sum().item(), 0)
        self.assertEqual(trace["costs"]["calls"],
            dict(reader_prepare=1, reader_step=3, verifier_prepare=1, verifier_step=2))

    def test_six_arms_same_actual_calls_and_fusion_is_fixed_probability_mean(self):
        features = self.binding.take([0, 1]).features()
        external = torch.tensor([[[.9, .1, 0., 1.], [.2, .8, 1., 1.]],
                                 [[.1, .9, 1., 1.], [.8, .2, 0., 1.]]])
        rows = {arm: execute_revision(features, self.core, self.verifier, mode=arm,
            verifier_provenance=self.provenance, external_feedback=external if arm == "shuffle" else None)
            for arm in ARMS}
        for row in rows.values():
            self.assertEqual(row["cost"]["calls"], dict(reader_prepare=1, reader_step=3, verifier_prepare=1, verifier_step=2))
            self.assertEqual(row["initial_proposals"], rows["real"]["initial_proposals"])
            self.assertEqual(row["cost"]["physical_batch_size"], 2)
            self.assertEqual(row["cost"]["per_case_attribution"], "singleton_only")
            self.assertGreater(row["cost"]["cpu_ns"], 0)
            self.assertFalse(row["labels_read"])
            self.assertNotIn('"targets"', json.dumps(row))
        expected = (torch.tensor(rows["zero"]["probabilities"]) + torch.tensor(rows["verifier_only"]["probabilities"])) / 2
        torch.testing.assert_close(torch.tensor(rows["late_fusion"]["probabilities"]), expected, rtol=0, atol=0)
        self.assertEqual([e["feedback"] for e in rows["shuffle"]["events"][2:]], external.reshape(-1, 4).tolist())

    def test_cheap_arms_measure_only_their_executed_model(self):
        for mode, expected in (("cheap_fixed1", dict(reader_prepare=1, reader_step=1, verifier_prepare=0, verifier_step=0)),
                               ("cheap_verifier", dict(reader_prepare=0, reader_step=0, verifier_prepare=1, verifier_step=1))):
            row = execute_revision(self.binding.take([0]).features(), self.core, self.verifier,
                                   mode=mode, verifier_provenance=self.provenance)
            self.assertEqual(row["cost"]["calls"], expected)

    def test_in_batch_derangement_uses_actual_observations_without_extra_calls(self):
        features = self.binding.take([0, 1]).features()
        row = execute_revision(features, self.core, self.verifier, mode="shuffle",
            verifier_provenance=self.provenance, shuffle_indices=[1, 0], case_ids=["case-A", "case-B"])
        self.assertEqual(row["cost"]["calls"], dict(reader_prepare=1, reader_step=3, verifier_prepare=1, verifier_step=2))
        self.assertTrue(row["shuffle_uses_current_observations"])
        self.assertFalse(row["cost"]["external_shuffle_feedback_required"])
        for hop in (1, 2):
            events = row["events"][hop * 2:(hop + 1) * 2]
            self.assertEqual([e["feedback"] for e in events], row["verifier_observations"][hop - 1][::-1])
            self.assertEqual([e["feedback_donor_case_id"] for e in events], ["case-B", "case-A"])
        for invalid in ([0, 1], [1, 1], [True, False], [1]):
            with self.assertRaisesRegex(ValueError, "derangement"):
                execute_revision(features, self.core, self.verifier, mode="shuffle",
                    verifier_provenance=self.provenance, shuffle_indices=invalid)

    def test_saved_probability_tie_is_negative_even_when_logits_argmax_is_positive(self):
        for model in (self.core, self.verifier):
            with torch.no_grad():
                model.head[-1].weight.zero_()
                model.head[-1].bias.copy_(torch.tensor([0., 1e-8]))
        trace = rollout_revision(self.core, self.verifier, self.binding.take([0, 1]).features(), mode="real")
        self.assertEqual(trace["logits_trace"][0].argmax(-1).tolist(), [1, 1])
        self.assertEqual(trace["output_probabilities"][:, 1].tolist(), [.5, .5])
        self.assertEqual(trace["output_predictions"].tolist(), [0, 0])
        self.assertTrue(all(event["prediction"] == 0 for event in trace["events"]))
        self.assertTrue(all(obs[:, 2].tolist() == [1., 1.] for obs in trace["verifier_observations"]))

    def test_external_feedback_and_public_feature_boundaries_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "six public"):
            rollout_revision(self.core, self.verifier, (*self.binding.features(), self.binding.targets))
        with self.assertRaisesRegex(ValueError, "public feedback"):
            rollout_revision(self.core, self.verifier, self.binding.features(), mode="shuffle")
        corrupted = torch.ones(2, 8, 4)
        with self.assertRaisesRegex(ValueError, "public feedback"):
            rollout_revision(self.core, self.verifier, self.binding.features(), mode="shuffle", external_feedback=corrupted)
        changed = {**self.provenance, "file_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "digest"):
            execute_revision(self.binding.features(), self.core, self.verifier, verifier_provenance=changed)
        overlap = copy.deepcopy(self.verifier)
        overlap.training_source_groups = (self.binding.source_groups[0],)
        provenance = {**self.provenance, "training_source_groups": list(overlap.training_source_groups)}
        with self.assertRaisesRegex(ValueError, "independent verifier sources"):
            execute_revision(self.binding.features(), self.core, overlap, verifier_provenance=provenance)

    def test_nonfinite_verifier_is_rejected_even_in_zero_control(self):
        original = self.verifier.step_prepared

        def broken(*args, **kwargs):
            state, logits, facts, tokens = original(*args, **kwargs)
            return state, logits * float("nan"), facts, tokens

        with mock.patch.object(self.verifier, "step_prepared", side_effect=broken):
            with self.assertRaisesRegex(FloatingPointError, "verifier logits"):
                rollout_revision(self.core, self.verifier, self.binding.features(), mode="zero")

    def test_matched_training_consumes_identical_plan_and_trains_channel(self):
        initial_core, initial_verifier = parameter_digest(self.core), parameter_digest(self.verifier)
        models, receipt = fit_revision_pair(self.core, self.verifier, self.natural, self.binding, self.cases,
            plan=self.plan, verifier_provenance=self.provenance, natural_cases=self.natural_cases)
        self.assertEqual(receipt["status"], "completed")
        self.assertTrue(receipt["feedback_training_verified"])
        self.assertEqual(receipt["completed_logical_updates"], 1)
        self.assertEqual([row["stream"] for row in receipt["updates"]], ["natural", "binding"])
        for row in receipt["updates"]:
            real, zero = (row["arms"][arm] for arm in ("real", "zero"))
            self.assertEqual(real["case_ids"], zero["case_ids"])
            self.assertEqual(real["targets"], zero["targets"])
            self.assertEqual(real["forward_cost"]["calls"], zero["forward_cost"]["calls"])
            self.assertEqual(real["input_feature_sha256s"], zero["input_feature_sha256s"])
        self.assertEqual(parameter_digest(self.core), initial_core)
        self.assertEqual(parameter_digest(self.verifier), initial_verifier)
        for arm, model in models.items():
            summary = receipt["models"][arm]
            self.assertEqual(summary["completed_updates"], 2)
            self.assertEqual(summary["natural_exposures"], 4)
            self.assertEqual(summary["binding_exposures"], 4)
            self.assertEqual(summary["actual_calls"]["verifier_step"], 4)
            self.assertEqual(len(summary["feedback_nonzero_updates_by_column"]), 4)
            if arm == "zero":
                self.assertEqual(summary["feedback_nonzero_updates_by_column"], [0] * 4)
            self.assertTrue(all(not p.requires_grad for p in model.parameters()))
            self.assertEqual(summary["execution_parameter_sha256"], parameter_digest(model))

    def test_failed_zero_update_preserves_completed_real_receipt_and_attempt_cost(self):
        from revision_training import _update

        sink, calls = [], []

        def fail_second(*args, **kwargs):
            calls.append(kwargs["mode"])
            if len(calls) == 2:
                raise RuntimeError("injected zero interruption")
            return _update(*args, **kwargs)

        with mock.patch("revision_training._update", side_effect=fail_second):
            with self.assertRaises(RevisionTrainingFailure) as caught:
                fit_revision_pair(self.core, self.verifier, self.natural, self.binding, self.cases,
                    plan=self.plan, verifier_provenance=self.provenance, natural_cases=self.natural_cases,
                    failure_receipt_fn=sink.append)
        receipt = caught.exception.receipt
        self.assertEqual(sink, [receipt])
        self.assertEqual(receipt["attempted_arm"], "zero")
        self.assertEqual(receipt["models"]["real"]["completed_updates"], 1)
        self.assertEqual(receipt["models"]["zero"]["completed_updates"], 0)
        self.assertEqual(set(receipt["updates"][0]["arms"]), {"real"})
        self.assertGreater(receipt["cpu_ns"], 0)
        self.assertGreater(receipt["wall_ns"], 0)
        self.assertTrue(receipt["failed_attempt_time_included"])
        self.assertFalse(receipt["final_evaluation_authorized"])

    def test_transition_metrics_keep_correction_and_damage_denominators(self):
        self.assertEqual(transition_counts([0, 0, 1, 1], [1, 1, 1, 0], [1, 0, 1, 1]),
            dict(exposure_trials=4, initial_correct=3, initial_wrong=1,
                 wrong_to_correct=1, correct_to_wrong=2, net_corrections=-1, final_correct=2))


if __name__ == "__main__":
    unittest.main()
