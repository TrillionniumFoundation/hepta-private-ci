"""Adversarial reviewer-only target-reconstruction tests (source fixtures != real model)."""
from __future__ import annotations

import copy
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import held_target_source_revalidation as source
import modernbert_feature_bridge as bridge
from physical_bank import Denied
from test_modernbert_feature_bridge import prepared


class PublisherTargetRevalidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inp, observer, selection = prepared()
        cls.public, cls.private = bridge.stage_original(inp, observer, selection)
        cls.cases = {
            "fit": [{"id": r["id"], "label": r["label"]} for r in inp["fit"]],
            "heldout": [{"id": r["id"], "label": r["label"]} for r in observer["rows"]],
        }

    def check_cases(self, pub=None, priv=None, cases=None):
        with patch.object(source, "ORIGINAL_SELECTION_ID", self.public["input_id"]), \
             patch.object(source, "ORIGINAL_SOURCE_CSV", self.public["source_material_sha256"]):
            source._compare_original_cases(pub or self.public, priv or self.private, cases or self.cases)

    def test_positive_comparison_has_original_case_id_and_binary_label_parity(self):
        # Only the inner *case-comparison* unit uses fixture cases. The actual
        # public verifier separately requires byte-exact original CSV files.
        self.check_cases()
        self.assertEqual(len(self.cases["fit"]), 64)
        self.assertEqual(len(self.cases["heldout"]), 32)

    def test_altered_private_binary_label_denied(self):
        priv = copy.deepcopy(self.private)
        priv["targets"][0]["target"] ^= 1
        with self.assertRaisesRegex(Denied, "blind target"):
            self.check_cases(priv=priv)

    def test_altered_private_type_denied(self):
        priv = copy.deepcopy(self.private)
        priv["targets"][0]["type"] = "hash1" if priv["targets"][0]["type"] == "hash0" else "hash0"
        with self.assertRaises(Denied):
            self.check_cases(priv=priv)

    def test_swapped_label_rows_denied_even_if_population_intact(self):
        cases = copy.deepcopy(self.cases)
        cases["heldout"][0], cases["heldout"][1] = cases["heldout"][1], cases["heldout"][0]
        with self.assertRaises(Denied):
            self.check_cases(cases=cases)

    def test_modified_training_label_denied(self):
        cases = copy.deepcopy(self.cases)
        cases["fit"][0]["label"] = (cases["fit"][0]["label"] + 1) % 4
        with self.assertRaisesRegex(Denied, "training label"):
            self.check_cases(cases=cases)

    def test_duplicated_or_missing_held_cases_denied(self):
        for variant in ("duplicate", "missing"):
            cases = copy.deepcopy(self.cases)
            if variant == "duplicate":
                cases["heldout"][1] = dict(cases["heldout"][0])
            else:
                cases["heldout"].pop()
            with self.subTest(variant=variant), self.assertRaises(Denied):
                self.check_cases(cases=cases)

    def test_modified_published_source_claim_denied(self):
        public = copy.deepcopy(self.public)
        public["source_material_sha256"]["test"] = "f" * 64
        with self.assertRaisesRegex(Denied, "source identity"):
            self.check_cases(pub=public)

    def test_actual_entry_rejects_unpinned_csv_before_reconstruct(self):
        with self.assertRaisesRegex(Denied, "publisher CSV bytes"):
            source.verify_publisher_held_targets(self.public, self.private, b"fake-train", b"fake-test")
        with self.assertRaises(Denied):
            source.verify_publisher_held_targets(self.public, self.private, "not-bytes", b"fake-test")

    def test_review_cli_requires_both_publisher_sources(self):
        script = Path(__file__).with_name("modernbert_feature_bridge.py")
        result = subprocess.run([sys.executable, str(script), "review",
                                 "--public", "public.json", "--private", "private.json",
                                 "--features", "features.json", "--feature-receipt", "receipt.json",
                                 "--trial", "trial.json", "--out", "review.json"],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--publisher-train", result.stderr)
        self.assertIn("--publisher-test", result.stderr)

    def test_fake_direct_review_cannot_use_claimed_original_source(self):
        inp, observer, sel = prepared()
        pub, priv = bridge.stage_original(inp, observer, sel)
        # This fixture is deliberately NOT the exact original source. Patching
        # the unrelated public source validator isolates the missing-CSV gate.
        with patch.object(bridge, "validate_public", return_value=None):
            with self.assertRaisesRegex(Denied, "requires original publisher CSV"):
                bridge.review_original(pub, priv, {}, {}, {}, exact_original_source=True)


if __name__ == "__main__":
    unittest.main()
