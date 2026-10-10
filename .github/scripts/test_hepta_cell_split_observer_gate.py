"""Signed-observer evidence tests; fixture signatures are not host certification."""

import base64
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hepta_cell_split_observer_gate import (
    OBSERVER_SCHEMA,
    SIGNED_SCHEMA,
    SIGNING_DOMAIN,
    canonical_bytes,
    digest,
    raw_evidence_root_digest,
    verify_observer_packet,
)
from hepta_cell_split_perf_gate import MODES, SCOPES, InvalidEvidence, analyze
from test_hepta_cell_split_perf_gate import synthetic_matrix


def ordered_run_digest(matrix):
    ordered = [
        {
            "scopes": scope,
            "mode": mode,
            "measurement_sha256": digest(
                next(
                    row
                    for row in matrix["runs"]
                    if row["scopes"] == scope and row["mode"] == mode
                )
            ),
        }
        for scope in SCOPES
        for mode in MODES
    ]
    return digest(ordered)


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL Ed25519 is required")
class IndependentObserverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.private = root / "private.pem"
        self.public = root / "observer.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.private)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(self.private), "-pubout", "-out", str(self.public)],
            check=True,
            capture_output=True,
        )
        self.pin = hashlib.sha256(self.public.read_bytes()).hexdigest()
        self.matrix = synthetic_matrix()
        self.comparison = analyze(self.matrix)
        self.claim = {
            "schema": OBSERVER_SCHEMA,
            "observer_id": "independent-signing-service",
            "producer_id": "source-measurement-service",
            "source_sha": self.matrix["source_sha"],
            "hardware_id": self.matrix["hardware_id"],
            "model_digest": self.matrix["model_digest"],
            "workload_digest": self.matrix["workload_digest"],
            "attempted_request_trace_sha256": self.matrix["runs"][0][
                "attempted_request_trace_sha256"
            ],
            "matrix_sha256": digest(self.matrix),
            "comparison_sha256": digest(self.comparison),
            "ordered_run_sha256": ordered_run_digest(self.matrix),
            "raw_evidence_root_sha256": "a" * 64,
            "observed_at_unix_seconds": 1770000000,
        }
        self.signed = self.sign(self.claim)

    def sign(self, claim):
        folder = Path(self.directory.name)
        message = folder / "claim.bin"
        signature = folder / "signature.bin"
        message.write_bytes(SIGNING_DOMAIN + canonical_bytes(claim))
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(self.private),
                "-rawin",
                "-in",
                str(message),
                "-out",
                str(signature),
            ],
            check=True,
            capture_output=True,
        )
        return {
            "schema": SIGNED_SCHEMA,
            "attestation": claim.copy(),
            "signature_base64": base64.b64encode(signature.read_bytes()).decode("ascii"),
        }

    def verify(self):
        return verify_observer_packet(
            self.matrix, self.comparison, self.signed, self.public, self.pin
        )

    def test_attests_exact_matrix_but_never_authorizes_physical_split(self):
        result = self.verify()
        self.assertTrue(result["observer_signature_verified"])
        self.assertTrue(result["exact_matrix_binding_verified"])
        self.assertFalse(result["raw_evidence_retention_verified"])
        self.assertTrue(result["comparative_gate_passed"])
        self.assertFalse(result["host_attestation_verified"])
        self.assertFalse(result["future_windows_verified"])
        self.assertFalse(result["production_activation_authorized"])

    def test_measurement_mutation_and_fabricated_comparison_are_rejected(self):
        self.matrix["runs"][0]["cpu_seconds"] += 1
        with self.assertRaisesRegex(InvalidEvidence, "comparison|digests"):
            self.verify()
        self.matrix = synthetic_matrix()
        self.comparison = analyze(self.matrix)
        self.comparison["comparative_gate_passed"] = False
        with self.assertRaisesRegex(InvalidEvidence, "comparison"):
            self.verify()

    def test_signature_tamper_and_wrong_trust_pin_are_rejected(self):
        self.signed["attestation"]["raw_evidence_root_sha256"] = "b" * 64
        with self.assertRaisesRegex(InvalidEvidence, "signature verification"):
            self.verify()
        self.signed = self.sign(self.claim)
        self.pin = "0" * 64
        with self.assertRaisesRegex(InvalidEvidence, "trust pin"):
            self.verify()

    def test_same_principal_missing_run_and_unpinned_fields_rejected(self):
        self.signed["attestation"]["observer_id"] = self.claim["producer_id"]
        with self.assertRaisesRegex(InvalidEvidence, "distinct"):
            self.verify()
        self.signed = self.sign(self.claim)
        self.signed["attestation"]["unexpected_field"] = "untrusted"
        with self.assertRaisesRegex(InvalidEvidence, "unknown"):
            self.verify()
        self.signed = self.sign(self.claim)
        self.matrix["runs"].pop()
        with self.assertRaisesRegex(InvalidEvidence, "exactly"):
            self.verify()

    def test_raw_evidence_root_requires_retained_bytes_and_rejects_mutation(self):
        raw = Path(self.directory.name) / "raw-measurements"
        raw.mkdir()
        receipt = raw / "64-no_split.json"
        receipt.write_bytes(b"real-observer-owned-raw-record")
        self.claim["raw_evidence_root_sha256"] = raw_evidence_root_digest(raw)
        self.signed = self.sign(self.claim)
        result = verify_observer_packet(
            self.matrix, self.comparison, self.signed, self.public, self.pin, raw
        )
        self.assertTrue(result["raw_evidence_retention_verified"])
        self.assertFalse(result["production_activation_authorized"])
        receipt.write_bytes(b"modified-underlying-record")
        with self.assertRaisesRegex(InvalidEvidence, "retained bytes"):
            verify_observer_packet(
                self.matrix, self.comparison, self.signed, self.public, self.pin, raw
            )

    def test_cryptographically_verified_failure_stays_failure(self):
        self.matrix["runs"][-1]["elapsed_seconds"] = 1000
        self.comparison = analyze(self.matrix)
        self.claim["matrix_sha256"] = digest(self.matrix)
        self.claim["comparison_sha256"] = digest(self.comparison)
        self.claim["ordered_run_sha256"] = ordered_run_digest(self.matrix)
        self.signed = self.sign(self.claim)
        result = self.verify()
        self.assertTrue(result["observer_signature_verified"])
        self.assertFalse(result["comparative_gate_passed"])
        self.assertFalse(result["production_activation_authorized"])


if __name__ == "__main__":
    unittest.main()
