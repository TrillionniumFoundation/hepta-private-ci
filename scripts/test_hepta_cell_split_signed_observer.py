"""Cryptographic matrix observer tests with generated test-only Ed25519 keys.

Generated keys are never production trust anchors. Passing these tests only
proves the signature protocol; it cannot attest real workloads or independence.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hepta_cell_split_observer_crypto import signed_observer_payload
from scripts.test_hepta_cell_split_matrix_integrity import MATRIX, synthetic_complete_report


PROVISIONAL_KEYS = (
    "schema",
    "authority",
    "sourceCommit",
    "workloadDigest",
    "workloadSourceDigest",
    "host",
    "cases",
)


class SignedObserverProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = tempfile.TemporaryDirectory(prefix="synthetic-observer-test-")
        cls.directory = Path(cls.workspace.name)
        cls.private = cls.directory / "test-only-private.pem"
        cls.public = cls.directory / "test-only-public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(cls.private)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(cls.private), "-pubout", "-out", str(cls.public)],
            check=True, capture_output=True,
        )
        cls.key_digest = hashlib.sha256(cls.public.read_bytes()).hexdigest()
        cls.observer_id = "synthetic-test-only-observer"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.workspace.cleanup()

    def setUp(self) -> None:
        self.report = synthetic_complete_report()
        self.observer = self.report["observer"]
        self.sign()

    def sign(self) -> None:
        self.observer["observerId"] = self.observer_id
        self.observer["signatureAlgorithm"] = "Ed25519"
        self.observer["publicKeySha256"] = self.key_digest
        payload_path = self.directory / "test-only-payload.json"
        sig_path = self.directory / "test-only-sig"
        payload_path.write_bytes(signed_observer_payload(self.observer))
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(self.private),
             "-in", str(payload_path), "-out", str(sig_path)],
            check=True, capture_output=True,
        )
        self.observer["signatureBase64"] = base64.b64encode(sig_path.read_bytes()).decode()
        self.reseal_digests_only()

    def reseal_digests_only(self) -> None:
        self.observer["receiptDigest"] = MATRIX.digest({
            key: value for key, value in self.observer.items() if key != "receiptDigest"
        })
        provisional = {key: self.report[key] for key in PROVISIONAL_KEYS}
        self.report["reportDigest"] = MATRIX.digest({**provisional, "observer": self.observer})

    def verify(self, **overrides: object) -> None:
        params = {
            "observer_public_key": self.public,
            "observer_key_sha256": self.key_digest,
            "expected_observer_id": self.observer_id,
        }
        params.update(overrides)
        MATRIX.validate_report(self.report, **params)

    def test_valid_test_signature_can_only_qualify_synthetic_schema(self) -> None:
        self.verify()
        self.assertEqual(self.report["authority"], "DENY_ALL")
        self.assertEqual(self.report["host"]["hostId"], "synthetic-only")

    def test_missing_trust_root_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "independently pinned"):
            MATRIX.validate_report(self.report)

    def test_wrong_independently_pinned_key_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            self.verify(observer_key_sha256="0" * 64)

    def test_wrong_observer_principal_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "principal"):
            self.verify(expected_observer_id="wrong-principal")

    def test_bad_signature_with_resealed_digests_fails(self) -> None:
        self.observer["signatureBase64"] = base64.b64encode(b"\\x01" * 64).decode()
        self.reseal_digests_only()
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            self.verify()

    def test_bad_message_with_resealed_receipt_fails(self) -> None:
        self.observer["metricsDigest"] = "f" * 64
        self.reseal_digests_only()
        with self.assertRaisesRegex(ValueError, "metrics binding"):
            self.verify()

    def test_signature_replay_across_reordered_cases_fails(self) -> None:
        self.report["cases"].reverse()
        # Hashes re-sealed to avoid accepting a forged report merely because
        # its weak structural SHA256 hashes agree. Original signature unchanged.
        self.observer["reportDigest"] = MATRIX.digest({
            key: self.report[key] for key in PROVISIONAL_KEYS
        })
        self.observer["metricsDigest"] = MATRIX.digest([
            {"caseId": case["caseId"], "metricsDigest": case["metricsDigest"]}
            for case in self.report["cases"]
        ])
        self.reseal_digests_only()
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            self.verify()

    def test_signature_is_not_attested_by_unsigned_verified_flag(self) -> None:
        self.observer.pop("signatureBase64")
        self.reseal_digests_only()
        with self.assertRaisesRegex(ValueError, "signature missing"):
            self.verify()

    def test_observer_command_without_pinned_key_is_not_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "blocked.json"
            with patch.object(MATRIX.subprocess, "run") as runner:
                report = MATRIX.run_matrix(
                    workload_command=None,
                    observer_command="untrusted-observer",
                    workload_digest="a" * 64,
                    source_commit="b" * 40,
                    output=output,
                )
                runner.assert_not_called()
            self.assertEqual(report["status"], "blocked")
            self.assertIn("independent-observer", report["blockingCases"])
            MATRIX.validate_report(json.loads(output.read_text()))


if __name__ == "__main__":
    unittest.main()
