"""Source-identity and counterfactual pairing tests for sealed 200 Reader outputs."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from system2_onehop_label_triad_audit import (
    ARMS,
    E_RAW_SHA256,
    E_ZIP_SHA256,
    METRICS,
    PRESENTATIONS,
    R_RAW_SHA256,
    R_ZIP_SHA256,
    SCHEMA,
    audit,
    strict_rows,
)


class LabelTriadTests(unittest.TestCase):
    def fixtures(self):
        keys = (
            "HEPTA_ONEHOP_CARDINALITY_ARCHIVE",
            "HEPTA_ONEHOP_LABEL_ARCHIVE",
            "HEPTA_ONEHOP_NEUTRAL_ARCHIVE",
        )
        paths = [Path(os.environ.get(k, "")) for k in keys]
        if not all(
            k in os.environ and p.is_file() for k, p in zip(keys, paths, strict=True)
        ):
            self.skipTest(
                "three externally pinned completed hosted archives not mounted"
            )
        return paths

    def test_frozen_census_and_role_structure(self):
        self.assertEqual(SCHEMA, "hepta.system2.onehop-three-presentation-audit.v1")
        self.assertEqual(len(ARMS) * len(PRESENTATIONS) * 20, 180)
        self.assertEqual(len(METRICS), 8)

    def test_bad_supposed_completions_are_rejected(self):
        with self.assertRaises(ValueError):
            strict_rows(b'{"a":1}\n', length=2, label="source")
        with self.assertRaises(ValueError):
            strict_rows(b'{"a":1}\n{"a":1}\n', length=1, label="source")
        with self.assertRaises(ValueError):
            strict_rows(b'{"a": NaN}\n', length=1, label="source")
        with self.assertRaises(ValueError):
            strict_rows(b'{"a":1, "a":2}\n', length=1, label="source")

    def test_externally_fixed_zip_digest_shape(self):
        self.assertEqual(len(E_ZIP_SHA256), 64)
        self.assertEqual(len(R_ZIP_SHA256), 64)
        self.assertNotEqual(E_RAW_SHA256, R_RAW_SHA256)

    def test_all_originals_reproduce_from_three_hosted_archives(self):
        card, e, r = self.fixtures()
        result = audit(card, e, r)
        self.assertEqual(result["schema"], SCHEMA)
        self.assertTrue(result["e_original_checked"])
        self.assertEqual(result["planned_source_model_calls"], 200)
        self.assertEqual(result["model_calls_added"], 0)
        self.assertEqual(result["source_question_count"], 20)
        self.assertEqual(result["paired_subjects"], 60)
        self.assertEqual(len(result["by_arm"]), 3)
        self.assertTrue(
            all(x["complete"] == 20 and x["unknown"] == 0 for x in result["by_arm"])
        )
        for arm in result["by_arm"]:
            self.assertEqual(arm["e_r_same_input_token_count"], 20)
            self.assertEqual(arm["e_r_different_input_token_ids"], 20)
            for metric in arm["metrics"].values():
                self.assertEqual(sum(metric["patterns"].values()), 20)
                self.assertEqual(metric["planned"], 20)
                self.assertEqual(metric["unknown"], 0)
                self.assertTrue(
                    all(lo == hi for lo, hi in metric["planned_each_bounds"].values())
                )

    def test_full_archive_does_not_promote_reader_adequacy(self):
        result = audit(*self.fixtures())
        for arm in result["by_arm"]:
            for metric in ("exact_answer_only", "prescribed_refusal", "success"):
                self.assertEqual(
                    arm["metrics"][metric]["observed_each"],
                    {"E": 0, "R": 0, "unlabeled": 0},
                )
        self.assertFalse(result["production_accepted"])
        self.assertTrue(result["no_trained_NDU_gain"])

    def test_label_echo_and_json_copy_account_for_different_failure_modes(self):
        result = audit(*self.fixtures())
        for arm in result["by_arm"]:
            echoes = arm["metrics"]["label_only_echo"]["observed_each"]
            copied = arm["metrics"]["json_input_echo"]["observed_each"]
            self.assertGreater(echoes["E"], 0)
            self.assertEqual(echoes["R"], 0)
            self.assertEqual(echoes["unlabeled"], 0)
            self.assertEqual(copied["R"], 20)
            self.assertEqual(copied["unlabeled"], 20)
            self.assertEqual(
                arm["metrics"]["at_64_token_cap"]["observed_each"]["R"], 20
            )

    def test_modified_neutral_zip_rejected_by_external_digest(self):
        card, e, r = self.fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            forged = Path(tmp) / "replaced.zip"
            shutil.copyfile(r, forged)
            with forged.open("ab") as stream:
                stream.write(b"not externally pinned")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                audit(card, e, forged)

    def test_modified_labeled_zip_rejected_by_external_digest(self):
        card, e, r = self.fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            forged = Path(tmp) / "changed.zip"
            shutil.copyfile(e, forged)
            with forged.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                audit(card, forged, r)

    def test_archive_swapping_rejected(self):
        card, e, r = self.fixtures()
        with self.assertRaises(ValueError):
            audit(card, r, e)

    def test_unverified_source_code_cannot_be_called_successful(self):
        with patch(
            "system2_onehop_label_triad_audit.verified_archive",
            side_effect=ValueError("untrusted source"),
        ):
            with self.assertRaisesRegex(ValueError, "untrusted source"):
                audit(Path("card"), Path("E"), Path("R"))


if __name__ == "__main__":
    unittest.main()
