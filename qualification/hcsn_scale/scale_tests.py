"""Behavioral tests for real encoder gradients, timestamps and complete restart."""

from dataclasses import asdict
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import torch

from qualification.hcsn_adaptive.budget import Budget
from qualification.hcsn_adaptive.datasets import inspect_splits
from .model import ModelConfig, SequenceModel
from .train import train_one, failure_receipt
from .campaign import finalize_one, seal_selection_set
from qualification.hcsn_adaptive.campaign import write_json
from qualification.hcsn_adaptive.datasets import file_digest


class ScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def test_bp_reaches_every_encoder_family_and_changes_encoder_weights(self):
        x = torch.tensor([[[.2, -.3, .7], [.4, .1, -.2], [-.5, .8, .3], [.1, -.2, .4]]], dtype=torch.float64)
        dt = np.array([[30., 31., 29., 30.]])
        for kind in ("hcsn", "gru"):
            torch.manual_seed(9)
            model = SequenceModel(ModelConfig(kind, 3, 2, 300.0))
            before = {name: p.detach().clone() for name, p in model.named_parameters()}
            optimizer = torch.optim.Adam(model.parameters(), lr=.003)
            model.next_sensor_loss(x, dt).backward()
            gradients = {name: p.grad for name, p in model.named_parameters()}
            self.assertEqual(set(gradients), set(before))
            self.assertTrue(all(value is not None and torch.isfinite(value).all() for value in gradients.values()))
            self.assertTrue(all(float(value.norm()) > 0 for value in gradients.values()))
            optimizer.step()
            self.assertTrue(any(not torch.equal(before[name], p) for name, p in model.named_parameters()
                                if not name.startswith("predictor.")))

    def test_real_intervals_change_both_models_without_resampling_inputs(self):
        sequence = torch.tensor([[.4, -.2, .7], [.5, .1, -.3], [-.2, .3, .6]], dtype=torch.float64)
        for kind in ("hcsn", "gru"):
            torch.manual_seed(9)
            model = SequenceModel(ModelConfig(kind, 3, 2, 300.0))
            a = model.encode_one(sequence, [30., 31., 29.])
            b = model.encode_one(sequence, [60., 11., 19.])
            self.assertGreater(float((a - b).detach().abs().max()), 1e-8)
            with self.assertRaises(ValueError):
                model.encode_one(sequence, [30., .0000001, 29.])

    def test_adam_rng_controller_and_encoder_resume_reproduce_next_updates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            rng = np.random.default_rng(11)
            for split, size in (("train", 8), ("dev", 4), ("test", 4)):
                x = rng.normal(size=(size, 3, 3))
                y = np.eye(2)[(x[:, -1, 0] > 0).astype(int)]
                np.savez(data / (split + ".npz"), x=x, y=y,
                         dt=np.tile([30., 31., 29.], (size, 1)),
                         ids=np.array([f"{split}:{i}" for i in range(size)]))
            config = {"data_dir": str(data), "bins": 4, "stages": 2, "dtype": "float64", "device": "cpu",
                      "learning_rate": .003, "ridge": .001, "gradient_clip": 1.0,
                      "steps": 2, "checkpoints": [0, 2], "batch_size": 2,
                      "budget": asdict(Budget(wall_seconds=100.0))}
            manifest = {"sha256": "fixture", "input_size": 3, "clock_scale_seconds": 300.0,
                        "config": config, "data": inspect_splits(data)}
            for kind in ("hcsn", "gru"):
                track = {"id": kind, "kind": kind, "width": 2, "seed": 9}
                whole = train_one(manifest, track, root / "whole")
                paused = train_one(manifest, track, root / "resumed", stop_after=1)
                self.assertEqual(paused["status"], "paused")
                resumed = train_one(manifest, track, root / "resumed", resume=True)
                self.assertEqual(whole["status"], "completed")
                self.assertEqual(resumed["status"], "completed")
                self.assertEqual(whole["history"], resumed["history"])
                self.assertEqual(whole["curve"], resumed["curve"])
                self.assertEqual(whole["current_parameter_sha256"], resumed["current_parameter_sha256"])
                self.assertEqual(whole["best_step"], resumed["best_step"])
                self.assertEqual(whole["cost"]["backward_examples"], resumed["cost"]["backward_examples"])


    def test_final_test_cannot_open_before_all_choices_are_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            track = {"id": "raw", "kind": "raw", "width": 0, "seed": None}
            manifest = {"sha256": "fixture", "config": {}, "tracks": [track]}
            with patch("qualification.hcsn_scale.campaign.load_split") as loader:
                with self.assertRaisesRegex(ValueError, "sealed before test"):
                    finalize_one(manifest, track, directory, {})
                loader.assert_not_called()

    def test_capacity_seed_selection_uses_dev_and_detects_later_changes(self):
        from .train import prepare_track
        with tempfile.TemporaryDirectory() as directory:
            tracks = [{"id": str(index), "kind": "gru", "width": index + 2, "seed": index}
                      for index in range(2)]
            manifest = {"sha256": "fixture", "input_size": 3, "clock_scale_seconds": 300.0,
                        "config": {"bins": 4, "stages": 2, "dtype": "float64"}, "tracks": tracks}
            for index, track in enumerate(tracks):
                identity, path, _ = prepare_track(manifest, track, directory)
                path.mkdir(parents=True)
                (path / "selected.pt").write_bytes(b"sealed selection fixture")
                write_json(path / "training.json", {"identity": identity, "manifest": "fixture", "track": track,
                    "status": "completed", "best_dev": 1.0 / (index + 1),
                    "selected_sha256": file_digest(path / "selected.pt")})
            records, seal = seal_selection_set(manifest, directory)
            self.assertEqual(seal["capacity_seed_choices_by_dev"], {"gru": "1"})
            _, path, _ = prepare_track(manifest, tracks[0], directory)
            records[0]["best_dev"] = 0.01
            write_json(path / "training.json", records[0])
            with self.assertRaisesRegex(ValueError, "sealed"):
                seal_selection_set(manifest, directory)
            with self.assertRaisesRegex(ValueError, "sealed"):
                finalize_one(manifest, tracks[1], directory, records[1])

    def test_precondition_failure_preserves_a_resumable_training_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            track = {"id": "raw", "kind": "raw", "width": 0, "seed": None}
            manifest = {"sha256": "fixture", "config": {}, "tracks": [track]}
            path = Path(directory) / "tracks/raw/training.json"
            write_json(path, {"status": "paused", "state": "must remain recoverable"})
            before = path.read_bytes()
            failed = failure_receipt(manifest, track, directory, FileExistsError("use explicit resume"))
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(path.parent.glob("attempt-failure-*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
