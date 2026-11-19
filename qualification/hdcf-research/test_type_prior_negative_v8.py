"""Adversarial checks on the exact original V6 pretrained-feature negative control.

The original-only class uses independently retrieved immutable Actions ZIPs.
When missing, it skips and MUST NOT be called an original-real-model test pass.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from physical_bank import Denied, digest
from type_prior_negative_v8 import (
    ORIGINAL_FEATURE_DIGEST,
    ORIGINAL_INPUT,
    _original_census,
    _pairs,
    _read_pinned_archive,
    audit_pinned_original,
)

ARCHIVES = {k: os.environ.get("HDCF_V8_" + k.upper() + "_ZIP")
            for k in ("features", "trial", "targets", "public")}


class SourceOnlySecurityTests(unittest.TestCase):
    def test_reject_duplicate_json_key(self):
        with self.assertRaises(Denied):
            _pairs([("source", 1), ("source", 2)])

    def test_reject_missing_archive(self):
        with self.assertRaises((Denied, FileNotFoundError)):
            _read_pinned_archive("/not-a-real-archive-hdcf-v8.zip", "features")

    def test_reject_directory(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises((Denied, IsADirectoryError)):
                _read_pinned_archive(td, "features")

    def test_reject_unsigned_fake_zip(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "empty.zip"
            f.write_bytes(b"PK\x03\x04")
            with self.assertRaisesRegex(Denied, "archive byte identity"):
                _read_pinned_archive(str(f), "trial")

    def test_reject_invalid_archive_kind(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "empty.zip"
            f.write_bytes(b"PK\x03\x04")
            with self.assertRaises(KeyError):
                _read_pinned_archive(str(f), "not-a-registered-arm")

    def test_math_strictly_descriptive(self):
        p = (20 + 1) / (35 + 2)
        self.assertGreater(p, 0.5)
        self.assertTrue(math.isfinite(-math.log(p)))
        self.assertFalse(32 >= 200)  # no independent 200-case certification


@unittest.skipUnless(all(ARCHIVES.values()), "original exact SHA-pinned V6 ZIPs not supplied")
class ActualOriginalArchivedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kwargs = {k + "_zip": v for k, v in ARCHIVES.items()}
        cls.report = audit_pinned_original(**cls.kwargs)
        cls.features = _read_pinned_archive(ARCHIVES["features"], "features")["features.json"]
        cls.receipt = _read_pinned_archive(ARCHIVES["features"], "features")["feature-receipt.json"]
        cls.trial = _read_pinned_archive(ARCHIVES["trial"], "trial")["trial.json"]
        cls.public = _read_pinned_archive(ARCHIVES["public"], "public")["public.json"]
        cls.targets = _read_pinned_archive(ARCHIVES["targets"], "targets")["targets.json"]

    def test_original_full_head_replay_and_source_identity(self):
        self.assertEqual(self.report["original_five_arm_predictions_independently_replayed"], 160)
        self.assertEqual(self.report["original_input_id"], ORIGINAL_INPUT)
        self.assertEqual(digest(self.features), ORIGINAL_FEATURE_DIGEST)
        self.assertEqual(self.report["real_original_encoder_forwards"], 96)

    def test_cheaper_type_only_matches_split(self):
        x = self.report
        self.assertEqual(x["test_count"], 32)
        self.assertEqual(x["type_only_correct"], x["split_correct"])
        self.assertEqual(x["type_only_correct"], 20)
        self.assertEqual(x["type_only_vs_split_decision_agreements"], 32)
        self.assertEqual(x["type_only_head_sgd_steps"], 0)
        self.assertEqual(x["type_only_required_pretrained_encoder_forwards"], 0)
        self.assertEqual(x["split_head_sgd_steps"], 256)

    def test_training_only_priors_and_calibration(self):
        x = self.report
        self.assertEqual(x["train_only_route_class_counts"], {
            "hash0": {"negative": 15, "positive": 20},
            "hash1": {"negative": 17, "positive": 12},
        })
        self.assertLess(x["type_only_brier"], x["split_brier"])
        self.assertLess(x["type_only_logloss"], x["split_logloss"])
        self.assertAlmostEqual(x["type_only_brier"], 0.23725020123760174, places=13)
        self.assertAlmostEqual(x["split_brier"], 0.23901124936861365, places=13)

    def test_zeroing_all_768_features_does_not_change_any_classification(self):
        self.assertEqual(self.report["zero_feature_vs_original_split_decision_agreements"], 32)
        self.assertEqual(self.report["zero_feature_split_correct"], 20)
        self.assertEqual(self.features["dimension"], 768)

    def test_no_learned_capability_or_promotion(self):
        self.assertTrue(self.report["same_publisher_retrospective_only"])
        self.assertFalse(self.report["future_window_verified"])
        self.assertFalse(self.report["task_transfer_verified"])
        self.assertFalse(self.report["original_publisher_signature_verified"])
        self.assertFalse(self.report["native_effect_authorized"])
        self.assertFalse(self.report["production_authorized"])
        self.assertEqual(self.report["disposition"], "HOLD_NO_GO")

    def test_archive_tamper_rejected_at_outer_digest(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "tampered.zip"
            dest.write_bytes(Path(ARCHIVES["features"]).read_bytes() + b"!new-archive-tail!")
            kw = dict(self.kwargs, features_zip=str(dest))
            with self.assertRaisesRegex(Denied, "archive byte identity"):
                audit_pinned_original(**kw)

    def test_symlink_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "linked.zip"
            path.symlink_to(Path(ARCHIVES["trial"]).resolve())
            with self.assertRaises(OSError):
                _read_pinned_archive(str(path), "trial")

    def test_wrong_train_only_type_or_class_fails_closed(self):
        fake = copy.deepcopy(self.features)
        fake["fit"][0]["target"] ^= 1
        with self.assertRaisesRegex(Denied, "wrong original pretrained feature population"):
            _original_census(fake, self.public, self.targets, self.receipt, self.trial)
        fake = copy.deepcopy(self.features)
        fake["fit"][0]["type"] = "hash0" if fake["fit"][0]["type"] == "hash1" else "hash1"
        with self.assertRaisesRegex(Denied, "wrong original pretrained feature population"):
            _original_census(fake, self.public, self.targets, self.receipt, self.trial)

    def test_wrong_terminal_or_model_identity_fails_closed(self):
        altered = copy.deepcopy(self.trial)
        altered["trial_identity"] = "0" * 64
        with self.assertRaisesRegex(Denied, "original trained trial drift"):
            _original_census(self.features, self.public, self.targets, self.receipt, altered)
        altered_receipt = copy.deepcopy(self.receipt)
        altered_receipt["observed_encoder_forward_calls"] = 95
        with self.assertRaisesRegex(Denied, "original Encoder-forward receipt changed"):
            _original_census(self.features, self.public, self.targets, altered_receipt, self.trial)

    def test_missing_held_case_denied(self):
        changed = copy.deepcopy(self.targets)
        changed["targets"].pop()
        with self.assertRaisesRegex(Denied, "original blind label population drift"):
            _original_census(self.features, self.public, changed, self.receipt, self.trial)


if __name__ == "__main__":
    unittest.main()
