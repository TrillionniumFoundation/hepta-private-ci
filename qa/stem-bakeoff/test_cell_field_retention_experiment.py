"""Real local worker/seal guards on constructed numerical inputs, not task gain."""

from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_control import build_reference
from cell_field_retention_experiment import SCHEMA, SOURCE_FILES, supervise
from cell_field_retention_run import ARMS, RetentionRunLimits
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, canonical


class FreshWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.code, self.run = self.root / "code", self.root / "run"
        self.code.mkdir()
        self.run.mkdir()
        hashes = {}
        for name in SOURCE_FILES:
            source = Path(importlib.import_module(name[:-3]).__file__)
            payload = source.read_bytes()
            (self.code / name).write_bytes(payload)
            hashes[name] = hashlib.sha256(payload).hexdigest()
        rng = np.random.default_rng(981)
        mode = "gated" if self._testMethodName == "test_hinge_worker_executes_the_registered_full_horizon" else "linear"
        old_x, current_x = rng.normal(size=(32, 8)), rng.normal(size=(32, 8))
        old_y, current_y = np.tile(np.arange(4), 8), np.tile(np.arange(4), 8)
        state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=7),
            bindings={"scope": "new numerical-only worker test; no public task corpus"},
            contexts={"old": dataset_digest(old_x, old_y), "current": dataset_digest(current_x, current_y)},
            active_context="old")
        for _ in range(64):
            state.advance(old_x, old_y)
        state.select_context("current")
        ref = build_reference(state, current_x, current_y, ((current_x, current_y), (old_x, old_y)), horizon=24)
        self.state, self.ref = state, ref
        state.save(self.run / "initial")
        with (self.run / "reference.npz").open("xb") as stream:
            np.savez_compressed(stream, **ref.arrays(), train_features=ref.train_features, train_labels=ref.train_labels,
                probe_current_x=ref.probes[0][0], probe_current_y=ref.probes[0][1],
                probe_old_x=ref.probes[1][0], probe_old_y=ref.probes[1][1])
        self.features = rng.normal(size=(480, 8))
        np.savez_compressed(self.run / "projected_features.npz", features=self.features)
        plan = {"schema": SCHEMA, "status": "FROZEN", "source_code_sha256": hashes,
                "authority": "DENY_ALL", "production_activation_allowed": False,
                "policies": list(ARMS), "action_masks": ["bias"], "seeds": [7, 17, 29],
                "head_modes": ["linear", "gated"], "classes": 4, "horizon": 24,
                "warmup_steps": 64, "projection": {"width": 8}, "optimizer": state.protocol,
                "h": 0.02, "retention_tolerance": 0.02, "retention_weight": 1.0,
                "current_target_displacement": -0.03, "effort_price": 0.1,
                "worker_wall_seconds": 75, "worker_cpu_seconds": 15,
                "run_limits": asdict(RetentionRunLimits())}
        (self.run / "protocol.json").write_bytes(canonical(plan) + b"\n")
        self.spec = {"run_root": str(self.run), "run_id": "unit-zero", "arm": "zero", "initial_index": int(mode == "gated"),
            "seed": 7, "head": mode, "initial_path": "initial", "initial_state_sha256": state.digest(),
            "bindings": state.bindings, "contexts": state.contexts, "reference_path": "reference.npz",
            "feature_identity": {"scope": "constructed-numerical-fixture"}}
        for key, name in (("protocol_sha256", "protocol.json"), ("reference_sha256", "reference.npz"),
                          ("projected_features_sha256", "projected_features.npz")):
            self.spec[key] = hashlib.sha256((self.run / name).read_bytes()).hexdigest()

    def call_worker(self, timeout=75):
        request = self.run / "request.json"
        request.write_bytes(canonical(self.spec) + b"\n")
        with patch("cell_field_retention_experiment.__file__", str(self.code / "cell_field_retention_experiment.py")):
            return supervise(request, self.run, self.spec["run_id"], timeout)

    def test_fresh_worker_keeps_zero_trajectory_and_prediction_identity(self):
        record = self.call_worker()
        self.assertEqual(record["status"], "completed", record)
        self.assertEqual(record["supervisor"]["return_code"], 0)
        self.assertEqual(record["controller_receipt"]["applied_steps"], 24)
        self.assertEqual(record["child_process_cpu_ns"], 0)
        self.assertGreater(record["process_peak_rss_bytes"], 0)
        self.assertGreater(record["supervisor"]["reaped_child_cpu_ns"], 0)
        path = self.run / "conditions/unit-zero/trajectory.npz"
        with np.load(path, allow_pickle=False) as arrays:
            np.testing.assert_array_equal(arrays["states"], self.ref.states)
        with np.load(self.run / "conditions/unit-zero/predictions.npz", allow_pickle=False) as values:
            expected = self.state.head_from_vector(self.ref.states[-1]).predict_proba(self.features)
            np.testing.assert_array_equal(values["probabilities"], expected)

    def test_hard_timeout_is_retained_as_unknown_prefix_and_failure(self):
        record = self.call_worker(timeout=0.000001)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["supervisor"]["wall_timeout"])
        self.assertIn("unknown", record["applied_steps"])
        self.assertIsNone(record["process_peak_rss_bytes"])
        self.assertNotEqual(record["supervisor"]["return_code"], 0)

    def test_stale_reference_fails_without_marking_zero_effect_as_success(self):
        self.spec["reference_sha256"] = "0" * 64
        record = self.call_worker()
        self.assertEqual(record["status"], "failed")
        self.assertIn("reference", record["failure"]["message"])
        self.assertNotIn("predictions_sha256", record)

    def test_hinge_worker_executes_the_registered_full_horizon(self):
        self.spec.update(run_id="unit-hinge", arm="retention_hinge_suffix")
        record = self.call_worker()
        self.assertEqual(record["status"], "completed", record)
        self.assertEqual(record["controller_receipt"]["applied_steps"], 24)
        self.assertEqual(len(record["controller_receipt"]["solver_receipts"]), 24)
        self.assertEqual(record["controller_receipt"]["contract"]["anchor"],
                         float(self.ref.observations[0, 1]))
        self.assertTrue(record["serving_roundtrip_equal"])


if __name__ == "__main__":
    unittest.main()
