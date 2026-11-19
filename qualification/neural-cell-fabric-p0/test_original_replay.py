"""Source-only abuse cases; optional byte-verified historical original ZIP replay."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from fabric import Denied
from original_replay import _no_duplicate_pairs, read_original, recount


ORIGINAL = os.getenv("HDCF_ORIGINAL_ARCHIVE_DIR")


class OriginalSourceTests(unittest.TestCase):
    def test_missing_original_archives_denied(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(Denied):
                read_original(Path(path))

    def test_original_symlink_root_denied(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            (root / "alias").symlink_to(root, target_is_directory=True)
            with self.assertRaises(Denied):
                read_original(root / "alias")

    def test_duplicate_json_member_key_denied(self):
        with self.assertRaises(Denied):
            json.loads('{"arm":1,"arm":2}', object_pairs_hook=_no_duplicate_pairs)

    @unittest.skipUnless(ORIGINAL, "requires authentic SHA256-pinned original GitHub artifacts")
    def test_actual_original_160_pretrained_predictions_recounted(self):
        r = recount(read_original(Path(ORIGINAL)))
        self.assertEqual(r["replayed_original_prediction_rows"], 160)
        self.assertEqual(r["physical_encoder_forward_count_in_original_receipt"], 96)
        self.assertTrue(r["trial_reused_cached_features_without_new_forwards"])
        self.assertEqual(r["train_only_type_counts"], {
            "hash0": {"neg": 15, "pos": 20},
            "hash1": {"neg": 17, "pos": 12},
        })
        self.assertEqual(r["metrics"]["split"]["correct"], 20)
        self.assertEqual(r["metrics"]["type_prior_zero_sgd"]["correct"], 20)
        self.assertEqual(r["split_vs_prior_agreement"], 32)
        self.assertAlmostEqual(r["split_vs_shared_one_touch_mcnemar_exact_p"], .5034446716308594)
        self.assertFalse(r["zero_feature_original_predictions_reexecuted"])
        self.assertEqual((r["disposition"], r["authority"]), ("HOLD_NO_GO", "DENY_ALL"))

    @unittest.skipUnless(ORIGINAL, "requires original archive for adversarial source mutation")
    def test_real_original_trial_arm_mutation_denied(self):
        source = read_original(Path(ORIGINAL))
        source["hdcf-original-head-trial.zip"]["predictions"]["split"][0]["p1"] = float("nan")
        with self.assertRaises(Denied):
            recount(source)

    @unittest.skipUnless(ORIGINAL, "requires original archive for route/order mutation")
    def test_real_original_case_order_mutation_denied(self):
        source = read_original(Path(ORIGINAL))
        source["hdcf-original-targets.zip"]["targets"].reverse()
        with self.assertRaises(Denied):
            recount(source)


if __name__ == "__main__":
    unittest.main()
