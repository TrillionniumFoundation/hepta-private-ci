import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch

from qualification.hcsn_boundary_factorial.run import FactorialModel
from qualification.hcsn_boundary_audit.audit_training_domain import (
    derive_visits, trace_rows, write_sidecar,
)
from qualification.hcsn_differentiable.training_domain import read_trace, source_hashes
from qualification.hcsn_differentiable.training_domain_audit import audit_trace


class TrainingDomainAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        model = FactorialModel(11, "c0_b0")
        cls.operator = model.network.layers[0].operator
        dt = torch.tensor([[.04, .08]], dtype=torch.float64)
        with torch.no_grad():
            output = model(torch.zeros(1, 2, 21, dtype=torch.float64), dt,
                           torch.ones(1, 2, dtype=torch.bool), trace=True)
        cls.row = dict(step=0, episode_id="fixture", model_sha256="a" * 64,
            physical_parameters={k:float(v) for k,v in vars(model.network.layers[0].physics()).items()},
            dt=dt.tolist(), valid_mask=[[True, True]],
            states=[{k:v.tolist() for k,v in trace[0].items()} for trace in output.trace])
        cls.fixture_run = dict(training_schedule=["fixture"], training_forward_calls=1,
                       model_configuration=model.configuration, training_trace_sha256="b" * 64)
        cls.data = {"fixture":dict(dt=[.04, .08], y=[-1, 0])}
        cls.summary = dict(data_sha256="c" * 64,
            source_before={"qualification/hcsn_differentiable/" + k:v for k,v in source_hashes().items()})

    def test_changed_original_trace_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "training.jsonl"
            path.write_text("not even valid JSON")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                trace_rows(path, "0" * 64, {})

    def test_step_and_episode_schedule_mismatch_rejected(self):
        for field, value in (("step", 1), ("episode_id", "other")):
            row = dict(self.row, **{field:value})
            with self.assertRaisesRegex(ValueError, "ordered schedule"):
                derive_visits([(row, "0" * 64)], self.fixture_run, self.data, self.operator)

    def test_prior_chain_and_reordered_posterior_replay_negative_control(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for reordered in (False, True):
                row = copy.deepcopy(self.row)
                if reordered:
                    a, b = row["states"]
                    a["probability"], b["probability"] = b["probability"], a["probability"]
                raw = (json.dumps(row, allow_nan=False) + chr(10)).encode()
                original = directory / ("bad-original" if reordered else "original")
                original.write_bytes(raw)
                digest = hashlib.sha256(raw).hexdigest()
                rows = trace_rows(original, digest, {})
                visits, ranges = derive_visits(rows, self.fixture_run, self.data, self.operator)
                self.assertEqual(visits[1]["prior"], row["states"][0]["probability"])
                self.assertEqual(visits[0]["origin_line_sha256"], digest)
                path = directory / ("bad-sidecar" if reordered else "sidecar")
                write_sidecar(path, visits, ranges, dict(self.fixture_run, training_trace_sha256=digest),
                              self.summary, "d" * 64)
                _, loaded, footer, _ = read_trace(path)
                self.assertEqual(loaded, visits)
                self.assertFalse(footer["truncated"])
                report = audit_trace(path, max_records=4096)
                self.assertTrue(report["complete_retained_coverage"])
                self.assertTrue(report["source_matches_trace"])
                errors = [v["maximum_event_replay_error"] for v in report["visits"]]
                self.assertLessEqual(errors[0], 5e-11)
                if reordered:
                    self.assertGreater(errors[1], 5e-11)
                    self.assertEqual(report["status"], "HOLD")
                else:
                    self.assertLessEqual(max(errors), 5e-11)

