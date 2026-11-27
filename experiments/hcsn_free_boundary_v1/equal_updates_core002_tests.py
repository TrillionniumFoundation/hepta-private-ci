"""Synthetic preflight of fresh initialization and exact-update selection."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from . import training
from .equal_updates_core002 import run_fixed_search, sha


class ExactUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def fixture(self, directory, updates=3):
        directory = Path(directory)
        arrays = {}
        rng = np.random.default_rng(7201)
        for split, size in (("train", 16), ("val", 8), ("test", 8), ("ood", 8)):
            x = rng.normal(size=(size, 3, 3)).astype(np.float32)
            y = np.full((size, 3), -100, np.int64)
            y[:, -1] = np.arange(size) % 2
            arrays.update({f"{split}_x": x, f"{split}_dt": np.full((size, 3), .4, np.float32), f"{split}_y": y})
        data = directory / "data.npz"
        np.savez_compressed(data, **arrays)
        initial = directory / "original_initial.npz"
        model = training.build_model("free_dual", 3, 2, width=4, seed=7202)
        training.save_weights(initial, model)
        references = {str(lr): dict(path=str(initial), sha256=sha(initial)) for lr in (.001, .003)}
        generator = torch.Generator().manual_seed(7202 + 200003)
        running, prefix = hashlib.sha256(), []
        for step in range(1, updates + 1):
            indices = torch.randint(16, (4,), generator=generator).numpy().tobytes()
            running.update(indices)
            prefix.append(dict(step=step, batch_sha256=hashlib.sha256(indices).hexdigest(), prefix_sha256=running.hexdigest()))
        return data, references, prefix

    def execute(self, data, references, prefix, output, existing=None):
        return run_fixed_search(data, 7202, output, references, prefix, existing128=existing,
                                target_updates=3, cpu_ceiling=30, width=4, depth=1, batch_size=4)

    def test_fresh_restart_exact_prefix_checkpoint_and_selection_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            data, references, prefix = self.fixture(directory)
            first = self.execute(data, references, prefix, directory / "first")
            self.assertEqual(first["selection"]["selected_step"], 3)
            self.assertEqual(first["selection"]["completed_lr_candidates"], 2)
            lock = next(i for i, row in enumerate(first["access_log"]) if row["event"] == "selection_locked")
            self.assertTrue(all(i > lock for i, row in enumerate(first["access_log"]) if row.get("split") in ("test", "ood")))
            old = {str(c["learning_rate"]): dict(path=str(directory / "first" / c["directory"] / c["terminal_checkpoint"]["weights"]),
                                                sha256=c["terminal_checkpoint"]["sha256"]) for c in first["candidates"]}
            second = self.execute(data, references, prefix, directory / "second", old)
            self.assertEqual(first["selection"]["selected_checkpoint_sha256"], second["selection"]["selected_checkpoint_sha256"])
            self.assertEqual(first["metrics"], second["metrics"])
            self.assertTrue(all(c["existing_original128_byte_identical"] for c in second["candidates"]))
            self.assertTrue(all(c["updates"] == 3 and c["all_update_prefixes_identical"] for c in second["candidates"]))

    def test_bad_initialization_fails_before_holdout_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            data, references, prefix = self.fixture(directory)
            references["0.001"]["sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                self.execute(data, references, prefix, directory / "failure")
            failed = json.loads((directory / "failure/FAILURE.json").read_text())
            self.assertFalse(any(r.get("split") in ("test", "ood") for r in failed["access_log"]))
            self.assertFalse((directory / "failure/SUMMARY.json").exists())
            self.assertTrue((directory / "failure/lr_0_0.001/updates.jsonl").is_file())

    def test_cpu_gate_best_is_ignored_and_only_own_intermediate_numeric_pruned(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            data, references, prefix = self.fixture(directory)
            original = training.train_candidate
            def altered(*args, **kwargs):
                result = original(*args, **kwargs)
                folder = Path(args[5])
                fake = dict(result["checkpoints"][0])
                fake.update(step=1, weights="synthetic_earlier_cpu_gate.npz", validation=dict(fake["validation"], cross_entropy=-1.0))
                shutil.copyfile(folder / "initial.npz", folder / fake["weights"])
                fake["sha256"] = sha(folder / fake["weights"])
                result["checkpoints"].insert(0, fake)
                result["best"] = fake
                return result
            with patch.object(training, "train_candidate", side_effect=altered):
                result = self.execute(data, references, prefix, directory / "search")
            self.assertEqual(result["selection"]["selected_step"], 3)
            self.assertGreater(result["selection"]["selected_validation"]["cross_entropy"], 0)
            for candidate in result["candidates"]:
                folder = directory / "search" / candidate["directory"]
                self.assertFalse((folder / "synthetic_earlier_cpu_gate.npz").exists())
                self.assertTrue((folder / "initial.npz").is_file())
                self.assertTrue((folder / candidate["terminal_checkpoint"]["weights"]).is_file())
            self.assertTrue(Path(references["0.001"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
