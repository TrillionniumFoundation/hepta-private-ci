"""Retained actual optimizer states, independent replay and missing coverage."""

import hashlib
from pathlib import Path
import tempfile
import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork
from qualification.hcsn_differentiable.training_domain import (
    TrainingDomainRecorder,
    read_trace,
)
from qualification.hcsn_differentiable.training_domain_audit import audit_trace


class TrainingDomainTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(314159)
        self.model = ContinuousSpikingNetwork(
            2,
            content_dim=2,
            layer_count=1,
            grid=GridSpec(active_cells=8, phase_cells=4, quadrature_order=8),
        )
        self.features = torch.randn((1, 4, 2), dtype=torch.float64)
        self.dt = torch.tensor([[0.01, 0.03, 0.0, 0.07]], dtype=torch.float64)
        self.binding = hashlib.sha256(
            self.features.numpy().tobytes() + self.dt.numpy().tobytes()
        ).hexdigest()

    def recorder(self, path, max_records=32):
        return TrainingDomainRecorder(
            path,
            data_sha256=self.binding,
            configuration_sha256="1" * 64,
            max_records=max_records,
        )

    def test_post_optimizer_states_replay_and_keep_qualification_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            recorder = self.recorder(path)
            optimizer = torch.optim.Adam(self.model.parameters(), lr=0.002)
            for update in range(2):
                state = self.model.initial_state(1)
                result = self.model(
                    self.features, self.dt, state=state, return_trace=True
                )
                recorder.capture(
                    self.model,
                    state,
                    result,
                    self.dt,
                    episode_id=f"train-{update}",
                    update_index=update,
                )
                optimizer.zero_grad()
                (result.predictions - 0.5).square().mean().backward()
                optimizer.step()
            recorder.close()
            header, visits, footer, digest = read_trace(path)
            self.assertEqual(
                (footer["captures"], footer["seen_records"], footer["dropped_records"]),
                (2, 8, 0),
            )
            self.assertEqual(header["data_sha256"], self.binding)
            self.assertNotEqual(visits[0]["model_sha256"], visits[-1]["model_sha256"])
            report = audit_trace(path)
            self.assertEqual(report["trace_sha256"], digest)
            self.assertTrue(report["source_matches_trace"])
            self.assertTrue(report["complete_retained_coverage"])
            self.assertEqual(report["scientific_admission"], "HOLD")
            self.assertTrue(
                all(row["status"] != "error" for row in report["visits"]), report
            )
            self.assertLess(
                max(row["maximum_mass_error"] for row in report["visits"]), 5e-11
            )
            self.assertLess(
                max(row["maximum_event_replay_error"] for row in report["visits"]),
                5e-11,
            )
            self.assertLess(
                max(
                    row.get("scaled_continuum_gradient_error", 0)
                    for row in report["visits"]
                ),
                2e-9,
            )
            self.assertEqual(
                sum(row["gradient_posterior_count"] for row in report["visits"]), 8
            )
            self.numerical_evidence = report
            # Modifying retained evidence is detected before any numerical claim.
            data = path.read_bytes().replace(
                b'"episode_id":"train-0"', b'"episode_id":"train-9"', 1
            )
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                read_trace(path)

    def test_truncated_or_partial_audits_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            recorder = self.recorder(path, max_records=1)
            state = self.model.initial_state(1)
            result = self.model(self.features, self.dt, state=state, return_trace=True)
            recorder.capture(
                self.model, state, result, self.dt, episode_id="one", update_index=0
            )
            with self.assertRaisesRegex(ValueError, "incomplete"):
                read_trace(path)
            recorder.close()
            report = audit_trace(path)
            self.assertEqual(report["trace_summary"]["dropped_records"], 3)
            self.assertFalse(report["complete_retained_coverage"])
            self.assertEqual(report["status"], "HOLD")

    def test_padding_and_byte_budget_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "padding.jsonl"
            recorder = self.recorder(path)
            features, dt = (
                self.features.expand(2, -1, -1).clone(),
                self.dt.expand(2, -1).clone(),
            )
            valid = torch.tensor([[True] * 4, [True, True, False, False]])
            dt[~valid] = 0
            state = self.model.initial_state(2)
            result = self.model(
                features,
                dt,
                state=state,
                return_trace=True,
                observed=valid,
                valid_mask=valid,
            )
            recorder.capture(
                self.model,
                state,
                result,
                dt,
                episode_id="padded",
                update_index=0,
                valid_mask=valid,
            )
            recorder.close()
            _, visits, footer, _ = read_trace(path)
            self.assertEqual([len(row["dt"]) for row in visits], [2, 2, 1, 1])
            self.assertEqual(footer["padded_states_excluded"], 2)
            path = Path(directory) / "bounded.jsonl"
            recorder = TrainingDomainRecorder(
                path,
                data_sha256=self.binding,
                configuration_sha256="1" * 64,
                max_records=32,
                max_bytes=65536,
            )
            features, dt = self.features.expand(64, -1, -1), self.dt.expand(64, -1)
            state = self.model.initial_state(64)
            result = self.model(features, dt, state=state, return_trace=True)
            recorder.capture(
                self.model, state, result, dt, episode_id="large", update_index=0
            )
            recorder.close()
            _, _, footer, _ = read_trace(path)
            self.assertLessEqual(path.stat().st_size, 65536)
            self.assertEqual(footer["drop_reason"], "byte_budget")
            self.assertTrue(footer["truncated"])

    def test_capture_rejects_missing_trace_or_changed_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = self.recorder(Path(directory) / "trace.jsonl")
            state = self.model.initial_state(1)
            result = self.model(self.features, self.dt, state=state)
            with self.assertRaisesRegex(ValueError, "complete return_trace"):
                recorder.capture(
                    self.model, state, result, self.dt, episode_id="one", update_index=0
                )
            with torch.no_grad():
                next(self.model.parameters()).add_(0.001)
            with self.assertRaisesRegex(ValueError, "parameters changed"):
                recorder.capture(
                    self.model, state, result, self.dt, episode_id="one", update_index=1
                )
            recorder.close()


if __name__ == "__main__":
    unittest.main()
