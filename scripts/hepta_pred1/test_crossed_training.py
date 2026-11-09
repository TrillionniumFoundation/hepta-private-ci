"""Campaign checks cover the frozen source, permitted splits and retained failures."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import crossed_training as C
from . import crossed_training_fit as F
from .test_crossed_training_fit import config


class CrossedTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_complete_campaign_generates_only_train_dev_once_per_data_level(self):
        cfg, calls = config(), []
        generate = C.generate_dataset

        def observed(count, seed, split, length):
            self.assertIn(split, ("train", "dev"))
            calls.append((seed, split))
            return generate(count, seed, split, length)

        with patch.object(C, "generate_dataset", observed), patch("builtins.print"):
            result = C.run(cfg, self.root / "campaign")
        self.assertEqual(result["status"], "COMPLETE", result)
        self.assertEqual(result["completed_fits"], 16)
        self.assertEqual(
            calls,
            [(seed, split) for seed in cfg["data_seeds"] for split in ("train", "dev")],
        )
        self.assertEqual(set(result["summary"]["per_variant"]), {"single_step", "gru"})
        self.assertIn(
            "gru_minus_single_step", result["summary"]["paired_factor_cell_differences"]
        )
        attempt = json.loads((self.root / "campaign" / "attempt.json").read_text())
        for name, digest in attempt["source_sha256"].items():
            self.assertEqual(
                C.sha256(
                    (self.root / "campaign" / "source" / name).read_bytes()
                ).hexdigest(),
                digest,
            )
        before = (self.root / "campaign" / "RESULT.json").read_bytes()
        with self.assertRaises(FileExistsError):
            C.run(cfg, self.root / "campaign")
        self.assertEqual(before, (self.root / "campaign" / "RESULT.json").read_bytes())

    def test_failed_fit_remains_failed_with_original_cell_and_consumed_work(self):
        cfg, original, count = config(), F.Model.fit_step, 0

        def fail_second(model, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("injected optimizer failure")
            return original(model, *args, **kwargs)

        with patch.object(F.Model, "fit_step", fail_second), patch("builtins.print"):
            result = C.run(cfg, self.root / "failed")
        self.assertEqual(
            (result["status"], result["completed_fits"], result["failed_fits"]),
            ("INCOMPLETE", 15, 1),
        )
        self.assertIsNone(result["summary"])
        paths = list((self.root / "failed" / "fits").glob("*.failed.json"))
        self.assertEqual(len(paths), 1)
        failed = json.loads(paths[0].read_text())
        self.assertEqual(
            (failed["data_seed"], failed["init_seed"], failed["order_seed"]),
            (910001, 920001, 930001),
        )
        self.assertEqual(
            (failed["fit_step_calls_completed"], failed["examples_completed"]), (1, 8)
        )
        self.assertGreater(failed["failed_fit_wall_seconds"], 0)
        self.assertFalse(list((self.root / "failed" / "fits").glob("*retry*")))


if __name__ == "__main__":
    unittest.main()
