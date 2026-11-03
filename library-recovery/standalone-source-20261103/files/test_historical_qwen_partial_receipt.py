"""Fail-closed archive validator plus optional externally-pinned run replay."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import historical_qwen_partial_receipt as forensic


PARTIAL = Path(os.getenv("HEPTA_PARTIAL_QWEN_ZIP", "/mnt/data/strong-rag-reader-failure-38111452963.zip"))
REFERENCE = Path(os.getenv("HEPTA_HISTORICAL_QWEN_ZIP", "/mnt/data/event-reader-actual-48.zip"))


class PartialCalibrationTests(unittest.TestCase):
    def test_exact_partial_and_full_archived_reference(self):
        if not PARTIAL.is_file() or not REFERENCE.is_file():
            self.skipTest("Requires exact GitHub Actions artifact ZIPs; no dummy model output")
        report = forensic.audit(PARTIAL, REFERENCE)
        self.assertEqual((report["observed_calibration_attempts"], report["missing_calibration_attempts"]), (4, 36))
        self.assertEqual((report["generation_succeeded"], report["observed_strict_success"]), (4, 0))
        self.assertTrue(report["old_host_k1_exceeds_current_180s_gate"])
        self.assertFalse(report["production_accepted"])
        self.assertIsNone(report["frozen_k_selected"])

    def test_reference_model_cannot_be_substituted(self):
        if not PARTIAL.is_file() or not REFERENCE.is_file():
            self.skipTest("Requires exact historical model artifact ZIPs")
        with self.assertRaises(ValueError):
            forensic.audit(PARTIAL, Path("not-an-authorized-original.zip"))

    def test_valid_synthetic_manifest_and_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.zip"
            member = b"strictly-not-a-model-answer"
            with zipfile.ZipFile(path, "w") as stream:
                stream.writestr("source.txt", member)
                stream.writestr("SHA256SUMS", forensic.sha256(member) + "  source.txt\n")
            pin = forensic.sha256(path.read_bytes())
            self.assertEqual(forensic.verified_zip(path, pin)["source.txt"], member)
            with self.assertRaisesRegex(ValueError, "outer|bytes"):
                forensic.verified_zip(path, "0" * 64)
            with zipfile.ZipFile(path, "w") as stream:
                stream.writestr("source.txt", member + b"changed")
                stream.writestr("SHA256SUMS", forensic.sha256(member) + "  source.txt\n")
            pin = forensic.sha256(path.read_bytes())
            with self.assertRaisesRegex(ValueError, "member"):
                forensic.verified_zip(path, pin)

    def test_manifest_rejects_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.zip"
            with zipfile.ZipFile(path, "w") as stream:
                stream.writestr("source.txt", b"x")
                stream.writestr("source.txt", b"x")
                stream.writestr("SHA256SUMS", forensic.sha256(b"x") + "  source.txt\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                forensic.verified_zip(path, forensic.sha256(path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
