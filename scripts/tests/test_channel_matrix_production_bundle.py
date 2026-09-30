"""Protected production bundle and split-signature tests for channel.matrix."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import channel_matrix_production_bundle as bundle


class ProductionBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.governance = self.root / "governance"
        self.governance.mkdir()
        self.candidate = {"commit": "a" * 40, "tree": "b" * 40}
        self.target_manifest = self.evidence / bundle.MANIFEST_NAMES[bundle.TARGET_SCOPE]
        self.acceptance_manifest = self.evidence / bundle.MANIFEST_NAMES[bundle.SECURITY_SCOPE]
        self.write(self.target_manifest, {"scope": bundle.TARGET_SCOPE, "result": "pass"})
        self.write(
            self.acceptance_manifest,
            {"scope": "independent_acceptance", "result": "pass"},
        )
        self.private_keys = {}
        public_names = {}
        principals = {
            bundle.TARGET_SCOPE: "matrix-target-operator",
            bundle.SECURITY_SCOPE: "matrix-security-review",
            bundle.OPERATIONS_SCOPE: "matrix-operations-review",
        }
        for scope in bundle.SCOPES:
            private = self.governance / f"{scope}.private.pem"
            public = self.governance / f"{scope}.public.pem"
            self.openssl("genpkey", "-algorithm", "ED25519", "-out", str(private))
            self.openssl(
                "pkey",
                "-in",
                str(private),
                "-pubout",
                "-out",
                str(public),
            )
            self.private_keys[scope] = private
            public_names[scope] = public.name
        self.policy = self.governance / "policy.json"
        self.write(
            self.policy,
            {
                "schema": bundle.POLICY_SCHEMA,
                "namespace": "hepta-channel-matrix-production",
                "principals": principals,
                "publicKeys": public_names,
            },
        )
        self.production_profile = {
            bundle.TARGET_SCOPE: ("encrypted_room_rotation", "process_fault_matrix"),
            "independent_acceptance": tuple(
                sorted((*bundle.SECURITY_CHECKS, *bundle.OPERATIONS_CHECKS))
            ),
        }
        self.target_validation = {
            "scope": bundle.TARGET_SCOPE,
            "candidate": self.candidate,
            "result": "pass",
            "executor": {
                "principal": "matrix-target-executor",
                "hostFingerprint": "target-host",
                "startedAtUnixMs": 100,
                "finishedAtUnixMs": 200,
            },
        }
        self.acceptance_validation = {
            "scope": "independent_acceptance",
            "candidate": self.candidate,
            "result": "pass",
            "executor": {
                "principal": "matrix-independent-executor",
                "hostFingerprint": "review-host",
                "startedAtUnixMs": 201,
                "finishedAtUnixMs": 300,
            },
        }
        self.target_validation_path = (
            self.evidence / bundle.VALIDATION_NAMES[bundle.TARGET_SCOPE]
        )
        self.acceptance_validation_path = (
            self.evidence / bundle.VALIDATION_NAMES[bundle.SECURITY_SCOPE]
        )
        self.write(self.target_validation_path, self.target_validation)
        self.write(self.acceptance_validation_path, self.acceptance_validation)
        self.attest(bundle.TARGET_SCOPE, self.target_validation_path, 210)
        self.attest(bundle.SECURITY_SCOPE, self.acceptance_validation_path, 310)
        self.attest(bundle.OPERATIONS_SCOPE, self.acceptance_validation_path, 320)

    @staticmethod
    def write(path: Path, row) -> None:
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def openssl(*arguments: str) -> None:
        subprocess.run(
            ["openssl", *arguments],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def expected_checks(self, scope: str):
        if scope == bundle.TARGET_SCOPE:
            return self.production_profile[bundle.TARGET_SCOPE]
        if scope == bundle.SECURITY_SCOPE:
            return bundle.SECURITY_CHECKS
        return bundle.OPERATIONS_CHECKS

    def attest(self, scope: str, manifest: Path, issued: int) -> Path:
        stem = scope.replace("_", "-") + ".attestation.json"
        receipt = self.evidence / stem
        principal = {
            bundle.TARGET_SCOPE: "matrix-target-operator",
            bundle.SECURITY_SCOPE: "matrix-security-review",
            bundle.OPERATIONS_SCOPE: "matrix-operations-review",
        }[scope]
        payload = manifest.read_bytes()
        self.write(
            receipt,
            {
                "schema": bundle.ATTESTATION_SCHEMA,
                "scope": scope,
                "candidate": self.candidate,
                "result": "pass",
                "principal": principal,
                "issuedAtUnixMs": issued,
                "evidenceManifest": {
                    "path": manifest.name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                "checks": list(self.expected_checks(scope)),
                "authorityGranted": False,
                "activation": False,
                "promotion": False,
                "release": False,
            },
        )
        message = self.evidence / f"{scope}.message"
        message.write_bytes(
            bundle._signed_payload(
                "hepta-channel-matrix-production", scope, receipt.read_bytes()
            )
        )
        signature = self.evidence / f"{stem}.sig"
        self.openssl(
            "pkeyutl",
            "-sign",
            "-inkey",
            str(self.private_keys[scope]),
            "-rawin",
            "-in",
            str(message),
            "-out",
            str(signature),
        )
        message.unlink()
        return receipt

    def validate(self):
        with (
            mock.patch.object(
                bundle.production,
                "load_profile",
                return_value=(self.production_profile, "f" * 64),
            ),
            mock.patch.object(
                bundle.production,
                "validate_manifest",
                side_effect=[self.target_validation, self.acceptance_validation],
            ),
        ):
            return bundle.validate_bundle(self.evidence, self.policy, self.candidate)

    def test_three_distinct_signatures_produce_non_authorizing_qualification(self):
        row = self.validate()
        self.assertTrue(row["productionQualified"])
        self.assertEqual(set(row["attestations"]), set(bundle.SCOPES))
        self.assertFalse(row["authorityGranted"])
        self.assertFalse(row["activation"])
        self.assertFalse(row["promotion"])
        self.assertFalse(row["release"])
        spki = row["governancePolicy"]["publicKeySpkiSha256"]
        self.assertEqual(len(set(spki.values())), 3)

    def test_missing_operations_signature_fails_closed(self):
        (self.evidence / "operations-acceptance.attestation.json.sig").unlink()
        with self.assertRaises((OSError, ValueError)):
            self.validate()

    def test_target_and_independent_executor_must_be_distinct_and_ordered(self):
        self.acceptance_validation["executor"]["principal"] = "matrix-target-executor"
        self.write(self.acceptance_validation_path, self.acceptance_validation)
        with self.assertRaises(ValueError):
            self.validate()
        self.acceptance_validation["executor"]["principal"] = "matrix-independent-executor"
        self.acceptance_validation["executor"]["startedAtUnixMs"] = 199
        self.write(self.acceptance_validation_path, self.acceptance_validation)
        with self.assertRaises(ValueError):
            self.validate()

    def test_attestation_must_bind_validated_manifest_and_exact_check_partition(self):
        receipt = self.evidence / "security-acceptance.attestation.json"
        row = json.loads(receipt.read_text())
        row["evidenceManifest"]["sha256"] = "0" * 64
        self.write(receipt, row)
        with self.assertRaises(ValueError):
            self.validate()

    def test_same_key_across_security_and_operations_is_rejected(self):
        security = self.governance / "security_acceptance.public.pem"
        operations = self.governance / "operations_acceptance.public.pem"
        operations.write_bytes(security.read_bytes())
        with self.assertRaises(ValueError):
            bundle.load_policy(self.policy)


if __name__ == "__main__":
    unittest.main()
