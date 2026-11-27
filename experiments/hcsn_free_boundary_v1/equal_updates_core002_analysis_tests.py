"""Integrity-gate fixtures only; no training or heldout observations."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from .equal_updates_core002_analysis import checkpoint_retention_audit


class RetentionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        for name in ("initial.npz", "step_000128.npz"):
            (self.folder/name).write_bytes(name.encode())
        payload = b"synthetic intermediate bytes"
        self.candidate = {
            "retained_numeric": ["initial.npz", "step_000128.npz"],
            "terminal_checkpoint": {"weights": "step_000128.npz"},
            "pruned_intermediate_numeric": [dict(weights="step_000032.npz",
                sha256=hashlib.sha256(payload).hexdigest())]}
        self.payload = payload

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_retention(self):
        self.assertEqual(checkpoint_retention_audit(self.folder,self.candidate),[])

    def test_only_verified_extra_classified_and_kept(self):
        extra=self.folder/"step_000032.npz"
        extra.write_bytes(self.payload)
        result=checkpoint_retention_audit(self.folder,self.candidate)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["expected_sha256"],result[0]["actual_sha256"])
        self.assertFalse(result[0]["participated_in_terminal128_selection"])
        self.assertEqual(extra.read_bytes(),self.payload)

    def test_unknown_extra_is_fatal(self):
        (self.folder/"unknown.npz").write_bytes(self.payload)
        with self.assertRaisesRegex(ValueError,"Unknown extra"):
            checkpoint_retention_audit(self.folder,self.candidate)

    def test_changed_extra_is_fatal(self):
        (self.folder/"step_000032.npz").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            checkpoint_retention_audit(self.folder,self.candidate)

    def test_missing_required_is_fatal(self):
        (self.folder/"step_000128.npz").unlink()
        with self.assertRaisesRegex(ValueError,"Missing required"):
            checkpoint_retention_audit(self.folder,self.candidate)


if __name__ == "__main__":
    unittest.main()
