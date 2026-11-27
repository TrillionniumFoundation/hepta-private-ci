"""Exercise the real training, selection, holdout and artifact boundaries."""

from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import run as campaign
from .simulator import generate_dataset


class CampaignTests(unittest.TestCase):
    def test_real_campaign_freezes_before_new_seeds_and_confirmation(self):
        config = {
            "base_commit": "test-only",
            "selection_seeds": [61],
            "seeds": [71, 72],
            "train_episodes": 12,
            "dev_episodes": 6,
            "confirm_episodes": 6,
            "history_length": 4,
            "epochs": 1,
            "batch_size": 6,
            "target_parameters": 128,
            "learning_rate": 0.003,
            "practical_utility_gain": 0.02,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            calls = []

            def guarded_generate(count, seed, split, length):
                if seed in config["seeds"]:
                    self.assertTrue((output / "family-selection.json").is_file())
                if split == "confirm":
                    frozen = json.loads((output / "selection.json").read_text())
                    self.assertEqual(len(frozen["checkpoint_sha256"]), 18)
                    self.assertEqual(len([c for c in calls if c[1] == "train"]), 3)
                calls.append((seed, split))
                return generate_dataset(count, seed, split, length)

            with patch.object(
                campaign, "generate_dataset", side_effect=guarded_generate
            ):
                with redirect_stdout(io.StringIO()):
                    result = campaign.run(config, output)
            self.assertEqual(len(result["confirm_by_seed"]), 12)
            self.assertEqual(result["primary_comparison"]["independent_seed_count"], 2)
            self.assertFalse(result["physical_cost_complete"])
            manifest = json.loads((output / "manifest.json").read_text())
            for name, metadata in manifest.items():
                self.assertEqual(
                    sha256((output / name).read_bytes()).hexdigest(), metadata["sha256"]
                )
            saved = (output / "attempt.json").read_bytes()
            with self.assertRaises(FileExistsError):
                campaign.run(config, output)
            self.assertEqual((output / "attempt.json").read_bytes(), saved)

    def test_paired_seed_inference_keeps_training_denominator(self):
        result = campaign.paired_statistics([0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertAlmostEqual(result["mean_difference"], 0.3)
        self.assertEqual(result["one_sided_signflip_p"], 1 / 32)
        self.assertEqual(result["independent_seed_count"], 5)
        self.assertEqual(
            campaign.paired_statistics([0.0] * 5)["one_sided_signflip_p"], 1.0
        )
        with self.assertRaises(ValueError):
            campaign.paired_statistics([np.nan, 0.1])


if __name__ == "__main__":
    unittest.main()
