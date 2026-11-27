"""Meaningful selection, parameter-matching, failure, and fresh-process replay checks."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from . import training
from .benchmark_models import BASELINE_NAMES, MODEL_NAMES, build_model


def _dataset(path, omit_validation=False):
    generator = np.random.default_rng(442)
    arrays = {}
    for split, size in (("train", 24), ("val", 12), ("test", 12), ("ood", 12)):
        if omit_validation and split == "val":
            continue
        x = generator.normal(size=(size, 5, 3)).astype(np.float32)
        y = np.full((size, 5), -100, dtype=np.int64)
        y[:, -1] = (x[:, :3, 0].sum(1) > 0).astype(np.int64)
        arrays.update({f"{split}_x": x, f"{split}_dt": np.full((size, 5), 0.8, np.float32),
                       f"{split}_y": y})
    np.savez_compressed(path, **arrays)


class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_real_baselines_match_budget_and_share_frontend(self):
        reference = build_model("free_dual", 3, 2, width=32, seed=19)
        x, dt = torch.randn(3, 5, 3), torch.ones(3, 5)
        matches = {}
        for name in MODEL_NAMES:
            model = build_model(name, 3, 2, width=32, seed=19)
            for component in ("frontend", "readout"):
                actual = getattr(model, component).state_dict()
                expected = getattr(reference, component).state_dict()
                for key in expected:
                    torch.testing.assert_close(actual[key], expected[key], rtol=0, atol=0)
            logits, _ = model(x, dt, return_sequence=True)
            self.assertEqual(logits.shape, (3, 5, 2), name)
            logits.square().mean().backward()
            for key, parameter in model.named_parameters():
                self.assertIsNotNone(parameter.grad, (name, key))
                self.assertTrue(torch.isfinite(parameter.grad).all(), (name, key))
            if name in BASELINE_NAMES:
                receipt = model.counts()["matching"]
                self.assertTrue(receipt["within_five_percent"], (name, receipt))
                self.assertFalse(receipt["parameter_padding"])
                matches[name] = receipt
        print(json.dumps(dict(test="active_parameter_matching", matches=matches), sort_keys=True))

    def test_no_holdout_until_selection_and_fresh_process_replay(self):
        with tempfile.TemporaryDirectory(prefix="hcsn_training_test_") as directory:
            directory = Path(directory)
            data, output = directory / "data.npz", directory / "run"
            _dataset(data)
            original_loader = training.load_split

            def guarded_loader(path, split, access_log=None):
                if split in {"test", "ood"}:
                    selection = json.loads((output / "selection.json").read_text())
                    self.assertEqual(selection["completed_lr_candidates"], 2)
                return original_loader(path, split, access_log)

            with patch.object(training, "load_split", guarded_loader):
                result = training.run_search(data, "free_dual", 44, output,
                                              cpu_seconds=0.08, width=8, batch_size=8)
            self.assertEqual(result["status"], "completed")
            self.assertEqual([item.get("split", item["event"]) for item in result["access_log"]],
                              ["train", "val", "selection_locked", "test", "ood"])
            first_batches = []
            for candidate in result["candidates"]:
                updates = (output / candidate["directory"] / "updates.jsonl").read_text().splitlines()
                first_batches.append(json.loads(updates[0])["batch_sha256"])
            self.assertEqual(*first_batches)
            self.assertEqual(result["selection"]["selected_validation"]["cross_entropy"],
                              min(candidate["best"]["validation"]["cross_entropy"]
                                  for candidate in result["candidates"]))
            code = """
import json, sys
from pathlib import Path
import numpy as np
import torch
from experiments.hcsn_free_boundary_v1.benchmark_models import build_model
from experiments.hcsn_free_boundary_v1.training import load_weights, load_split, evaluate
torch.set_num_threads(1)
data, output = Path(sys.argv[1]), Path(sys.argv[2])
summary = json.loads((output / 'summary.json').read_text())
request = summary['request']
model = build_model(request['model'], 3, 2, width=request['width'], depth=request['depth'], seed=request['seed'])
load_weights(output / 'selected.npz', model)
metrics = evaluate(model, load_split(data, 'test'), output_path=output / 'fresh_process_predictions.npz')
with np.load(output / 'test_predictions.npz', allow_pickle=False) as saved, np.load(output / 'fresh_process_predictions.npz', allow_pickle=False) as replay:
    error = float(np.max(np.abs(saved['logits'] - replay['logits'])))
print(json.dumps(dict(max_logit_error=error, metrics=metrics)))
"""
            completed = subprocess.run([sys.executable, "-c", code, str(data), str(output)],
                                        cwd=Path(__file__).resolve().parents[2],
                                        check=True, capture_output=True, text=True)
            replay = json.loads(completed.stdout)
            self.assertEqual(replay["max_logit_error"], 0)
            self.assertEqual(replay["metrics"], result["holdout"]["test"])

    def test_update_cap_reports_unspent_budget(self):
        with tempfile.TemporaryDirectory(prefix="hcsn_cap_test_") as directory:
            directory = Path(directory)
            data = directory / "data.npz"
            _dataset(data)
            result = training.run_search(data, "two_gates", 41, directory / "run",
                                          cpu_seconds=20.0, width=8, batch_size=8,
                                          max_updates=2)
            for candidate in result["candidates"]:
                self.assertEqual(candidate["updates"], 2)
                self.assertEqual(candidate["stopping_reason"], "update_cap")
                self.assertLess(candidate["training_cpu_seconds"], 20)

    def test_failure_is_saved_and_not_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="hcsn_failure_test_") as directory:
            directory = Path(directory)
            data, output = directory / "bad.npz", directory / "run"
            _dataset(data, omit_validation=True)
            with self.assertRaises(ValueError):
                training.run_search(data, "free_dual", 7, output, cpu_seconds=0.02)
            before = (output / "failure.json").read_bytes()
            self.assertNotIn(b'"split": "test"', before)
            with self.assertRaises(FileExistsError):
                training.run_search(data, "free_dual", 7, output, cpu_seconds=0.02)
            self.assertEqual((output / "failure.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
