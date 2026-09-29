"""Cryptographic, exact-candidate governance receipt tests for channel.matrix."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import channel_matrix_governed_attestation as governed
import channel_matrix_status as status
from channel_matrix_evidence import file_digest
from channel_matrix_governed_attestation import _signed_payload


class GovernedAttestationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.governance = self.root / "governance"
        self.governance.mkdir()
        self.candidate = {"commit": "a" * 40, "tree": "b" * 40}
        source = {
            "schema": "hepta.channel-matrix-source-snapshot.v1",
            "testedSha": self.candidate["commit"],
            "testedTree": self.candidate["tree"],
            "sourceSha": self.candidate["commit"],
            "baseSha": "c" * 40,
            "lane": "source-head",
            "files": [{"path": "fixture"}],
        }
        self.write(self.evidence / "source.json", source)
        self.write(self.evidence / "source-after.json", source)
        self.write(
            self.evidence / "candidate.json",
            {
                "schema": "hepta.channel-matrix-candidate-receipt.v1",
                "candidate": self.candidate,
                "status": "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING",
            },
        )
        self.private_keys = {}
        public_names = {}
        for scope in ("target_qualification", "independent_acceptance"):
            private = self.governance / f"{scope}.private.pem"
            public = self.governance / f"{scope}.public.pem"
            self.openssl(
                "genpkey",
                "-algorithm",
                "ED25519",
                "-out",
                str(private),
            )
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
                "schema": "hepta.channel-matrix-governance-policy.v1",
                "namespace": "hepta-channel-matrix",
                "principals": {
                    "target_qualification": "matrix-target-operator",
                    "independent_acceptance": "matrix-independent-acceptance",
                },
                "publicKeys": public_names,
            },
        )

    @staticmethod
    def write(path, row):
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def openssl(*arguments):
        subprocess.run(
            ["openssl", *arguments],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def attest(self, scope, *, candidate=None):
        manifest = self.evidence / f"{scope}.manifest.json"
        self.write(
            manifest,
            {
                "schema": "fixture.manifest.v1",
                "scope": scope,
                "result": "pass",
            },
        )
        name = scope.replace("_", "-") + ".attestation.json"
        receipt = self.evidence / name
        principal = {
            "target_qualification": "matrix-target-operator",
            "independent_acceptance": "matrix-independent-acceptance",
        }[scope]
        self.write(
            receipt,
            {
                "schema": "hepta.channel-matrix-governed-attestation.v1",
                "scope": scope,
                "candidate": candidate or self.candidate,
                "result": "pass",
                "principal": principal,
                "issuedAtUnixMs": 1_800_000_000_000,
                "evidenceManifest": {
                    "path": manifest.name,
                    "bytes": manifest.stat().st_size,
                    "sha256": file_digest(manifest),
                },
                "checks": [f"{scope}:fixture"],
                "authorityGranted": False,
                "activation": False,
                "release": False,
            },
        )
        message = self.evidence / f"{scope}.signed-message"
        message.write_bytes(
            _signed_payload("hepta-channel-matrix", scope, receipt.read_bytes())
        )
        signature = self.evidence / f"{name}.sig"
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

    def test_target_receipt_is_verified_but_never_activates(self):
        self.attest("target_qualification")
        row = status.summarize(self.evidence, self.policy)
        self.assertEqual(row["states"]["target_qualification"], "passed")
        self.assertEqual(row["states"]["independent_acceptance"], "not_proved")
        self.assertFalse(row["activation"])
        self.assertFalse(row["release"])
        governed_row = row["governed_attestations"]
        self.assertEqual(
            governed_row["receipts"]["target_qualification"]["principal"],
            "matrix-target-operator",
        )
        spki = governed_row["policy"]["public_key_spki_sha256"]
        self.assertEqual(set(spki), {"target_qualification", "independent_acceptance"})
        self.assertEqual(len(set(spki.values())), 2)

    def test_independent_acceptance_requires_and_verifies_target(self):
        self.attest("target_qualification")
        self.attest("independent_acceptance")
        row = status.summarize(self.evidence, self.policy)
        self.assertEqual(row["states"]["target_qualification"], "passed")
        self.assertEqual(row["states"]["independent_acceptance"], "passed")
        self.assertFalse(row["authority_granted"])

    def test_acceptance_without_target_fails_closed(self):
        self.attest("independent_acceptance")
        with self.assertRaises(ValueError):
            status.summarize(self.evidence, self.policy)

    def test_tampered_or_wrong_candidate_receipt_fails_closed(self):
        receipt = self.attest("target_qualification")
        receipt.write_text(receipt.read_text() + " ")
        with self.assertRaises(ValueError):
            status.summarize(self.evidence, self.policy)

        receipt.unlink()
        (self.evidence / "target-qualification.attestation.json.sig").unlink()
        self.attest(
            "target_qualification",
            candidate={"commit": "d" * 40, "tree": "e" * 40},
        )
        with self.assertRaises(ValueError):
            status.summarize(self.evidence, self.policy)

    def test_same_ed25519_key_with_different_pem_bytes_is_rejected(self):
        target = self.governance / "target_qualification.public.pem"
        acceptance = self.governance / "independent_acceptance.public.pem"
        acceptance.write_bytes(target.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            governed.load_policy(self.policy)

    def test_non_ed25519_public_key_is_rejected(self):
        private = self.governance / "rsa.private.pem"
        public = self.governance / "target_qualification.public.pem"
        self.openssl(
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(private),
        )
        self.openssl(
            "pkey",
            "-in",
            str(private),
            "-pubout",
            "-out",
            str(public),
        )
        with self.assertRaises(ValueError):
            governed.load_policy(self.policy)

    def test_signature_length_and_symlink_directory_fail_closed(self):
        self.attest("target_qualification")
        signature = self.evidence / "target-qualification.attestation.json.sig"
        signature.write_bytes(signature.read_bytes() + b"x")
        with self.assertRaises(ValueError):
            governed.verify_attestations(self.evidence, self.candidate, self.policy)

        signature.write_bytes(signature.read_bytes()[:-1])
        alias = self.root / "evidence-alias"
        alias.symlink_to(self.evidence, target_is_directory=True)
        with self.assertRaises(ValueError):
            governed.verify_attestations(alias, self.candidate, self.policy)


if __name__ == "__main__":
    unittest.main()
