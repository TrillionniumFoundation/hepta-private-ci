import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import campaign
from .datasets import make_synthetic


class CampaignTests(unittest.TestCase):
    def prepare(self, directory):
        root = Path(directory)
        make_synthetic(root / "data", train=8, dev=4, test=4, length=3, seed=72)
        config = {"experiment_id": "isolated-integration-test", "stage": "smoke",
                  "data_dir": str(root / "data"), "seeds": [7], "methods": ["ridge"],
                  "variants": [{"id": "fixed", "boundary": "fixed", "drift": "input", "channels": "dual"}],
                  "flow": {"bins": 2, "stages": 1, "content_size": 1, "upper_mode": "reflecting"},
                  "budget": {"wall_seconds": 60.0}, "feature_budget": {"wall_seconds": 60.0}}
        campaign.write_json(root / "config.json", config)
        manifest = campaign.freeze(root / "config.json", root / "manifest.json")
        return root, manifest, manifest["trials"][0]

    def test_holdout_is_unopened_until_all_selections_are_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, trial = self.prepare(directory)
            calls = []
            original = campaign.load_split
            def observed_load(data_dir, split, expected):
                calls.append(split)
                return original(data_dir, split, expected)
            with patch.object(campaign, "load_split", side_effect=observed_load):
                training = campaign.train_trial(manifest, trial, root / "out")
                self.assertIn("selected_sha256", training)
                self.assertNotIn("test", calls)
                with self.assertRaises(FileNotFoundError):
                    campaign.finalize_trial(manifest, trial, root / "out", training)
                campaign.seal_selection_set(manifest, root / "out")
                final = campaign.finalize_trial(manifest, trial, root / "out", training)
                repeated = campaign.finalize_trial(manifest, trial, root / "out", training)
            self.assertEqual(final, repeated)
            self.assertEqual(calls.count("test"), 1)
            summary = campaign.summarize_campaign(manifest, root / "out")
            self.assertEqual(summary["groups"]["fixed:ridge"]["completed_test"], 1)
            self.assertEqual(summary["uncertain_or_unavailable_cost_records"], [])

    def test_corrupt_feature_cache_is_rejected_before_final_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, trial = self.prepare(directory)
            training = campaign.train_trial(manifest, trial, root / "out")
            self.assertIn("selected_sha256", training)
            campaign.seal_selection_set(manifest, root / "out")
            feature_path = next((root / "out/features").glob("*/features.pt"))
            feature_path.write_bytes(feature_path.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                campaign.finalize_trial(manifest, trial, root / "out", training)
            self.assertFalse((root / "out/trials" / trial["id"] / "final.started").exists())


if __name__ == "__main__":
    unittest.main()
