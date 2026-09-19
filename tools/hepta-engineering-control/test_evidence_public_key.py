from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringController,
    EngineeringError,
    ExecutionReceipt,
    HmacTrustStore,
    OpenSslTrustStore,
    TrustedPublicKey,
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
            payload = root / "payload"
            signature = root / "signature"
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
            store = OpenSslTrustStore(
                {
                    ("ci_executor", "github-actions-workload"): TrustedPublicKey(
                        public_bytes,
                        hashlib.sha256(public_bytes).hexdigest(),
                    )
                }
            )
            payload.write_bytes(store.payload(receipt))
            subprocess.run(
                [
                    str(openssl),
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(private),
                    "-out",
                    str(signature),
                    str(payload),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            signed = replace(
                receipt,
                signature=base64.b64encode(signature.read_bytes()).decode("ascii"),
            )
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
