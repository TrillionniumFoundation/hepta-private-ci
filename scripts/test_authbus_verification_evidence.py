#!/usr/bin/env python3
"""Regression tests for receipt classification; no network or source writes."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from authbus_verification_evidence import REQUIRED_FILES
from authbus_verification_evidence import REQUIRED_STEPS
from authbus_verification_evidence import build_receipt
from authbus_verification_evidence import sha256_file


class ReceiptTests(unittest.TestCase):
    def receipt(self, *, steps=None, artifacts=None, recorded_sha=None):
        successful = {
            name: {"outcome": "success", "conclusion": "success"}
            for name in REQUIRED_STEPS
        }
        present = {name: {"bytes": 1, "sha256": "a" * 64} for name in REQUIRED_FILES}
        return build_receipt(
            "1" * 40, "2" * 40,
            "1" * 40 if recorded_sha is None else recorded_sha, "2" * 40,
            successful if steps is None else steps,
            present if artifacts is None else artifacts,
        )

    def test_only_complete_success_is_verified(self):
        self.assertTrue(self.receipt()["candidate_verified"])

    def test_failed_skipped_cancelled_and_absent_steps_are_not_passes(self):
        for outcome in ["failure", "skipped", "cancelled", "not_recorded"]:
            with self.subTest(outcome=outcome):
                steps = {
                    name: {"outcome": "success", "conclusion": "success"}
                    for name in REQUIRED_STEPS
                }
                steps["authbus"] = {"outcome": outcome, "conclusion": outcome}
                self.assertFalse(self.receipt(steps=steps)["candidate_verified"])
        self.assertFalse(self.receipt(steps={})["candidate_verified"])

    def test_continue_on_error_cannot_hide_failure(self):
        steps = {
            name: {"outcome": "success", "conclusion": "success"}
            for name in REQUIRED_STEPS
        }
        steps["bao"]["outcome"] = "failure"
        self.assertFalse(self.receipt(steps=steps)["candidate_verified"])

    def test_mismatched_and_missing_identity_fail_closed(self):
        for source in ["3" * 40, "", "not-a-sha"]:
            self.assertFalse(self.receipt(recorded_sha=source)["candidate_verified"])

    def test_missing_artifact_cannot_be_inferred_from_step_success(self):
        artifacts = {name: {"bytes": 1, "sha256": "a" * 64} for name in REQUIRED_FILES}
        del artifacts["authbus-tests.log"]
        result = self.receipt(artifacts=artifacts)
        self.assertFalse(result["candidate_verified"])
        self.assertIn("evidence_missing_or_invalid:authbus-tests.log", result["blockers"])

    def test_hash_matches_actual_bytes_and_does_not_change_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.txt"
            data = b"actual execution result\n"
            path.write_bytes(data)
            self.assertEqual(
                sha256_file(path),
                {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
            )
            self.assertEqual(path.read_bytes(), data)
            path.write_bytes(b"")
            self.assertIsNone(sha256_file(path))
            path.unlink()
            self.assertIsNone(sha256_file(path))

    def test_symlink_is_not_an_execution_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_bytes(b"unrelated evidence")
            link = Path(directory) / "linked.log"
            link.symlink_to(target)
            self.assertIsNone(sha256_file(link))


if __name__ == "__main__":
    unittest.main()
