from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from control_engineering_v2 import (
    EngineeringController,
    EngineeringError,
    ExecutionReceipt,
    HmacTrustStore,
    OpenSslTrustStore,
    TrustedPublicKey,
    WorkerIdentityReceipt,
)


class OpenSslTrustStoreTests(unittest.TestCase):
    def test_verification_only_store_accepts_pinned_key_and_rejects_tamper(self) -> None:
        openssl = Path("/usr/bin/openssl")
        if not openssl.is_file():
            self.skipTest("/usr/bin/openssl is unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                [
                    str(openssl),
                    "genpkey",
                    "-algorithm",
                    "RSA",
                    "-pkeyopt",
                    "rsa_keygen_bits:2048",
                    "-out",
                    str(private),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    str(openssl),
                    "pkey",
                    "-in",
                    str(private),
                    "-pubout",
                    "-out",
                    str(public),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            receipt = ExecutionReceipt(
                "run",
                "exact_source",
                "a" * 40,
                "b" * 40,
                ("c" * 40,),
                "d" * 64,
                True,
                "ci_executor",
                "github-actions-workload",
                10,
                20,
            )
            public_bytes = public.read_bytes()
            pinned_key = TrustedPublicKey(
                public_bytes,
                hashlib.sha256(public_bytes).hexdigest(),
            )
            store = OpenSslTrustStore(
                {
                    ("ci_executor", "github-actions-workload"): pinned_key,
                    ("engineering_worker_authority", "worker-authority"): pinned_key,
                    ("engineering_audit_witness", "audit-witness"): pinned_key,
                }
            )

            def sign(value, name: str):
                payload_file = root / f"{name}.payload"
                signature_file = root / f"{name}.signature"
                payload_file.write_bytes(store.payload(value))
                subprocess.run(
                    [
                        str(openssl),
                        "dgst",
                        "-sha256",
                        "-sign",
                        str(private),
                        "-out",
                        str(signature_file),
                        str(payload_file),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return replace(
                    value,
                    signature=base64.b64encode(signature_file.read_bytes()).decode("ascii"),
                )
            signed = sign(receipt, "execution")
            self.assertTrue(
                store.verify(
                    signed,
                    signed.issuer,
                    signed.signing_identity,
                    signed.signature,
                )
            )
            tampered = replace(signed, checks_digest="e" * 64)
            self.assertFalse(
                store.verify(
                    tampered,
                    tampered.issuer,
                    tampered.signing_identity,
                    tampered.signature,
                )
            )
            self.assertFalse(hasattr(store, "sign"))

            database = root / "engineering.db"
            with EngineeringController(
                database,
                root,
                "TrillionniumFoundation/hepta-private-ci",
                store,
                writer_instance_id="github-actions:engineering-control",
                writer_credential_chain_digest="9" * 64,
            ) as controller:
                events = controller.audit_projection()
                self.assertTrue(
                    any(event["eventType"] == "engineering_writer_bound" for event in events)
                )

                now = time.time_ns()
                identity = WorkerIdentityReceipt(
                    worker_id="worker-signed",
                    principal="github-actions:engineering-worker",
                    credential_chain_digest="6" * 64,
                    capabilities=("git", "python"),
                    maximum_concurrency=2,
                    authority_epoch=11,
                    observed_unix_ns=now,
                    lease_expires_unix_ns=now + 1_000_000_000,
                    expires_unix_ns=now + 5_000_000_000,
                    issuer="engineering_worker_authority",
                    signing_identity="worker-authority",
                )
                worker = controller.register_worker(
                    sign(identity, "worker"),
                    now_ns=now + 1,
                )
                self.assertEqual(worker.state, "active")
                self.assertEqual(worker.principal, identity.principal)
                renewed = controller.heartbeat_worker(
                    worker.worker_id,
                    expected_revision=worker.revision,
                    authority_epoch=worker.authority_epoch,
                    new_expiry_unix_ns=now + 2_000_000_000,
                    now_ns=now + 2,
                )
                self.assertEqual(
                    renewed.lease_expires_unix_ns,
                    now + 2_000_000_000,
                )
                with self.assertRaisesRegex(EngineeringError, "invalid_worker_expiry"):
                    controller.heartbeat_worker(
                        worker.worker_id,
                        expected_revision=renewed.revision,
                        authority_epoch=renewed.authority_epoch,
                        new_expiry_unix_ns=now + 6_000_000_000,
                        now_ns=now + 3,
                    )

                anchor = controller.prepare_audit_anchor(
                    signing_identity="audit-witness",
                    observed_unix_ns=now + 2,
                    expires_unix_ns=now + 5_000_000_000,
                )
                signed_anchor = sign(anchor, "audit")
                controller.verify_audit_anchor(
                    signed_anchor,
                    minimum_sequence=anchor.sequence,
                    now_ns=now + 3,
                )
                with self.assertRaisesRegex(EngineeringError, "audit_anchor_sequence"):
                    controller.verify_audit_anchor(
                        signed_anchor,
                        minimum_sequence=anchor.sequence + 1,
                        now_ns=now + 3,
                    )

            with self.assertRaisesRegex(EngineeringError, "writer_binding_conflict"):
                EngineeringController(
                    database,
                    root,
                    "TrillionniumFoundation/hepta-private-ci",
                    store,
                    writer_instance_id="different-writer",
                    writer_credential_chain_digest="8" * 64,
                )

            with self.assertRaisesRegex(EngineeringError, "fixture_verifier_forbidden"):
                EngineeringController(
                    root / "fixture.db",
                    root,
                    "TrillionniumFoundation/hepta-private-ci",
                    HmacTrustStore({("ci_executor", "fixture"): b"fixture"}),
                    writer_instance_id="fixture-writer",
                    writer_credential_chain_digest="7" * 64,
                )


if __name__ == "__main__":
    unittest.main()
