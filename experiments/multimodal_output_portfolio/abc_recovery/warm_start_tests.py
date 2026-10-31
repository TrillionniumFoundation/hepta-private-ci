"""The S-only optimization trace must match the original v7 training recipe."""

from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import SourceCorpus, SourceSplit
from ..v7.training import TrainConfig, train_profiles
from .warm_start import save_training_checkpoint, train_supervised


class WarmStartTests(unittest.TestCase):
    def test_s_only_matches_original_parameters_history_and_resume_checkpoint(self):
        rng = torch.Generator().manual_seed(62)
        source = SourceSplit(torch.randint(256, (32, 1, 28, 28), generator=rng, dtype=torch.uint8),
                             torch.arange(32) % 10, tuple(f"unit:{i}" for i in range(32)),
                             tuple(f"unit-hash:{i}" for i in range(32)))
        corpus = SourceCorpus({"train": source}, {"manifest_sha256": "unit-fixture-only"})
        config = TrainConfig(seed=29, steps=3, batch_size=2, scenarios=2, threads=2)
        original, old_reports = train_profiles(corpus, config)
        with tempfile.TemporaryDirectory() as directory:
            checkpoints = []
            def checkpoint(model, optimizer, step, generator, schedule):
                checkpoints.append(save_training_checkpoint(Path(directory) / f"{step}.pt", model,
                    optimizer, step, generator, {"schedule_sha256": schedule}))
            with torch.inference_mode():
                recovered, report = train_supervised(corpus, config, checkpoint=checkpoint,
                                                      checkpoint_interval=1)
            self.assertEqual(original["supervised"].parameter_sha256, recovered.parameter_sha256)
            self.assertEqual(original["supervised"].fingerprint, recovered.fingerprint)
            excluded = {"wall_ns", "cpu_ns"}
            self.assertEqual({k: v for k, v in old_reports["supervised"].items() if k not in excluded},
                             {k: v for k, v in report.items() if k not in excluded})
            self.assertEqual([record["step"] for record in checkpoints], [0, 1, 2, 3])
            record = torch.load(checkpoints[-1]["path"], weights_only=True)
            self.assertEqual(record["parameter_sha256"], recovered.parameter_sha256)
            self.assertEqual(record["metadata"]["schedule_sha256"], report["schedule_sha256"])
            self.assertTrue(record["optimizer_state_dict"]["state"])
            for name, tensor in record["state_dict"].items():
                self.assertTrue(torch.equal(tensor, recovered.to_record()["state_dict"][name]))


if __name__ == "__main__":
    unittest.main()
