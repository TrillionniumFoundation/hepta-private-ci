"""Compact evidence restores original selected snapshots without optimization."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_development_artifacts_v7 import materialize_checkpoints, read_compressed, save_failure, save_result
from cell_field_development_audit_v7 import per_source_nll
from cell_learning_models import canonical
from test_cell_field_development_audit_v7 import example


class DevelopmentArtifactTests(unittest.TestCase):
    def test_nonstandard_stop_always_retains_exact_terminal_controller_preimage(self):
        for count in (8, 23, 24):
            warmup, train, panels, anchors, config, result = example(count)
            selection = (np.zeros((512, 8)), np.tile(np.arange(4), 128))
            inputs = {"split": {"current_train": train}, "current_panels": panels, "old_panels": panels,
                "selection": {"old": selection, "future": selection}}
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory)/"case"
                row = save_result(target, {"fit_id": "fixture"}, warmup, inputs, anchors, "myopic_h1", config,
                    result, {"cpu_ns": 1000, "wall_ns": 2000}, per_source_nll(warmup, selection))
                self.assertTrue(row["audit_passed"])
                saved = read_compressed(target/"controller-checkpoints.json.gz")
                raw = canonical(saved[str(count)])
                trace = read_compressed(target/"trace.json.gz")
                self.assertEqual(raw, canonical(result["controllers"][-1]))
                self.assertEqual(hashlib.sha256(raw).hexdigest(), trace["controller_sha256"][-1])
                self.assertEqual(saved[str(count)]["run_status"], "stopped")

    def test_compact_trace_recovers_exact0_16_17_32_controller_bytes(self):
        warmup, train, panels, anchors, config, result = example(32)
        selection = (np.zeros((512, 8)), np.tile(np.arange(4), 128))
        inputs = {"split": {"current_train": train}, "current_panels": panels, "old_panels": panels,
            "selection": {"old": selection, "future": selection}}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"case"
            row = save_result(target, {"fit_id": "fixture"}, warmup, inputs, anchors, "myopic_h1", config,
                result, {"cpu_ns": 1000, "wall_ns": 2000}, per_source_nll(warmup, selection))
            self.assertTrue(row["audit_passed"])
            self.assertEqual(read_compressed(target/"policy-record.json.gz"), result["record"])
            actions, states = materialize_checkpoints(target, warmup, inputs, anchors, "myopic_h1", config)
            self.assertTrue(np.array_equal(actions, result["actions"]))
            self.assertEqual(states[-1].digest(), result["state"].digest())
            for step in (0, 16, 17, 32):
                content = (target/"selected-checkpoints"/str(step)/"controller.json").read_bytes()
                self.assertEqual(content, canonical(result["controllers"][step]))
                metadata = json.loads((target/"selected-checkpoints"/str(step)/"state/manifest.json").read_bytes())
                self.assertEqual(metadata["state_sha256"], result["states"][step].digest())
            self.assertFalse((target/"probabilities.npz").exists())
            with self.assertRaisesRegex(ValueError, "expanded bound"):
                read_compressed(target/"policy-record.json.gz", limit=1)

    def test_unavailable_case_preserves_error_without_imputed_terminal_losses(self):
        with tempfile.TemporaryDirectory() as directory:
            row = save_failure(Path(directory)/"failed", {"fit_id": "fixture"}, "future_field_h8",
                ArithmeticError("prospective failure"), {"cpu_ns": 100, "wall_ns": 200})
            self.assertEqual(row["status"], "unavailable_execution_error")
            self.assertIsNone(row["completed_steps"])
            self.assertIsNone(row["future_mean_nll"])
            self.assertEqual(row["future_losses"].size, 0)
            self.assertEqual(row["error"]["type"], "ArithmeticError")


if __name__ == "__main__":
    unittest.main()
