"""Exercise recorded-flow AD/FD admission without granting scientific credit."""

import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork
from qualification.hcsn_differentiable.training_domain import TrainingDomainRecorder, read_trace
from qualification.hcsn_differentiable import training_domain_projected_gradients as audit


class ProjectedGradientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        torch.manual_seed(104729)
        cls.directory = tempfile.TemporaryDirectory()
        cls.trace = Path(cls.directory.name) / "post-update-trace.jsonl"
        model = ContinuousSpikingNetwork(
            2, content_dim=2, layer_count=1,
            grid=GridSpec(active_cells=6, phase_cells=3, quadrature_order=8))
        features = torch.tensor([[[.4, -.2], [.1, .6], [-.3, .2]]], dtype=torch.float64)
        dt = torch.tensor([[.08, .07, .08]], dtype=torch.float64)
        configuration = json.dumps({
            "model": model.configuration(), "seed": 104729, "optimizer": "Adam", "learning_rate": .002,
            "updates": 2, "initial_value": math.exp(.18),
            "loss": "mean((last_prediction-.25)^2)+.01*mean(all_predictions^2)",
        }, sort_keys=True).encode()
        recorder = TrainingDomainRecorder(
            cls.trace, data_sha256=hashlib.sha256(features.numpy().tobytes() + dt.numpy().tobytes()).hexdigest(),
            configuration_sha256=hashlib.sha256(configuration).hexdigest(), max_records=32)
        optimizer = torch.optim.Adam(model.parameters(), lr=.002)
        try:
            for update in range(3):
                state = model.initial_state(1, absolute_initial=math.exp(.18))
                output = model(features, dt, state=state, return_trace=True)
                recorder.capture(model, state, output, dt, episode_id=f"mechanism-{update}", update_index=update)
                if update < 2:
                    optimizer.zero_grad(set_to_none=True)
                    ((output.predictions[:, -1] - .25).square().mean()
                     + .01 * output.predictions.square().mean()).backward()
                    optimizer.step()
        finally:
            recorder.close()
        cls.visits = read_trace(cls.trace)[1]
        cls.truncated_trace = Path(cls.directory.name) / "truncated.jsonl"
        partial_recorder = TrainingDomainRecorder(
            cls.truncated_trace, data_sha256=hashlib.sha256(features.numpy().tobytes() + dt.numpy().tobytes()).hexdigest(),
            configuration_sha256=hashlib.sha256(configuration).hexdigest(), max_records=1)
        partial_recorder.capture(model, state, output, dt, episode_id="truncated", update_index=2)
        partial_recorder.close()

    @classmethod
    def tearDownClass(cls):
        cls.trace_bytes = cls.trace.read_bytes()
        cls.directory.cleanup()

    def test_post_update_flow_jacobians_cover_all_retained_outputs(self):
        report = audit.audit_projected_trace(self.trace, max_records=32)
        self.numerical_evidence = report
        self.assertEqual(report["status"], "passed_recorded_projected_gradients", report)
        self.assertTrue(report["complete_retained_coverage"])
        self.assertTrue(report["source_unchanged_during_audit"])
        self.assertEqual({row["update_index"] for row in report["visits"]}, {0, 1, 2})
        self.assertEqual(len({row["model_sha256"] for row in report["visits"]}), 3)
        self.assertEqual(sum(row["derivative_coordinates"] for row in report["visits"]), 675)
        self.assertTrue(any(abs(value) > 1e-7 for row in report["visits"] for values in row["ad"] for value in values))

    def test_detached_physics_gradient_is_detected(self):
        original = audit._flow_vector

        def disconnected(operator, prior, dt, values):
            return original(operator, prior, dt, values).detach() + sum(values) * 0.

        with patch.object(audit, "_flow_vector", disconnected):
            report = audit.audit_visit(self.visits[-1])
        self.assertEqual(report["status"], "HOLD")
        self.assertTrue(any(row["maximum_tolerance_ratio"] > 1 for row in report["parameters"]))

    def test_zero_duration_has_exact_zero_parameter_jacobian(self):
        visit = dict(self.visits[0], dt=[0.], expected_events=[0.])
        report = audit.audit_visit(visit)
        self.assertEqual(report["status"], "passed_projected_gradient_fixture")
        self.assertTrue(all(value == 0 for values in report["ad"] for value in values))
        self.assertTrue(all(value == 0 for values in report["fd_fine"] for value in values))
        self.assertTrue(all(value is None for row in report["parameters"] for value in row["ordinary_relative_errors"]))

    def test_misbound_recorded_event_counts_are_rejected(self):
        visit = dict(self.visits[-1], expected_events=[self.visits[-1]["expected_events"][0] + .125])
        with self.assertRaisesRegex(ValueError, "recorded event replay"):
            audit.audit_visit(visit)

    def test_truncated_recorder_does_not_qualify_whole_coverage(self):
        report = audit.audit_projected_trace(self.truncated_trace)
        self.assertEqual(report["status"], "HOLD")
        self.assertFalse(report["complete_retained_coverage"])
        self.assertEqual(report["trace_summary"]["dropped_records"], 2)

    def test_partial_and_expired_budget_cannot_qualify(self):
        partial = audit.audit_projected_trace(self.trace, max_records=1)
        self.assertEqual(partial["status"], "HOLD")
        self.assertFalse(partial["complete_retained_coverage"])
        expired = audit.audit_projected_trace(self.trace, max_wall_seconds=1e-12)
        self.assertEqual(expired["status"], "HOLD")
        self.assertTrue(expired["wall_budget_exhausted"])
        self.assertEqual(expired["visits"][0]["error_type"], "TimeoutError")

    def test_source_mismatch_does_not_execute_a_different_operator(self):
        with patch.object(audit, "source_hashes", return_value={}), patch.object(audit, "audit_visit") as visit:
            report = audit.audit_projected_trace(self.trace)
        self.assertEqual(report["status"], "HOLD")
        self.assertFalse(report["source_matches_trace"])
        self.assertEqual(report["audited_records"], 0)
        visit.assert_not_called()

    def test_source_change_during_audit_cannot_qualify(self):
        sources = audit.source_hashes()
        with patch.object(audit, "source_hashes", side_effect=[sources, {}]):
            report = audit.audit_projected_trace(self.trace, max_records=1)
        self.assertEqual(report["status"], "HOLD")
        self.assertFalse(report["source_unchanged_during_audit"])

    def test_boundary_stencil_is_held_without_method_switch(self):
        visit = dict(self.visits[0], parameters={**self.visits[0]["parameters"], "discount": .001})
        with self.assertRaisesRegex(ValueError, "numerical domain"):
            audit.audit_visit(visit)


if __name__ == "__main__":
    unittest.main()
