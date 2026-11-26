"""Signature and clock checks for the installed desktop endpoint maintenance tool."""

import base64
import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PATH = Path(__file__).with_name("hepta-renew-native-endpoint")
SPEC = importlib.util.spec_from_loader(
    "endpoint_renewal",
    importlib.machinery.SourceFileLoader("endpoint_renewal", str(PATH)),
)
renewal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renewal)


class EndpointRenewalTests(unittest.TestCase):
    def setUp(self):
        self.seed = bytes(range(32))
        self.key = Ed25519PrivateKey.from_private_bytes(self.seed)
        public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.trust = {
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"endpoint-one": base64.b64encode(public).decode()},
        }
        self.manifest = {
            "schema": "hepta.endpoint-manifest.v1",
            "endpoint_id": "installed-one",
            "address": "127.0.0.1:7374",
            "protocol_version": 2,
            "gateway_credential_account": "read-one",
            "key_id": "endpoint-one",
            "issued_unix_ms": 1000,
            "expires_unix_ms": 2000,
        }
        self.manifest["manifest_digest"] = hashlib.sha256(
            renewal.payload(self.manifest)
        ).hexdigest()
        self.manifest["signature_base64"] = base64.b64encode(
            self.key.sign(renewal.signing_message(self.manifest["manifest_digest"]))
        ).decode()

    def test_expired_authenticated_endpoint_gets_new_bounded_window_and_same_binding(
        self,
    ):
        renewed = renewal.renew_manifest(self.manifest, self.trust, self.seed, 3000)
        self.assertEqual(renewed["issued_unix_ms"], 3000)
        self.assertEqual(renewed["expires_unix_ms"], 3000 + renewal.MAX_LIFETIME_MS)
        preserved = set(renewal.FIELDS) - {"issued_unix_ms", "expires_unix_ms"}
        self.assertEqual(
            {k: renewed[k] for k in preserved}, {k: self.manifest[k] for k in preserved}
        )
        self.key.public_key().verify(
            base64.b64decode(renewed["signature_base64"]),
            renewal.signing_message(renewed["manifest_digest"]),
        )
        self.assertEqual(
            renewal.renew_manifest(renewed, self.trust, self.seed, 3001), renewed
        )

    def test_tampered_endpoint_and_forged_signature_cannot_be_renewed(self):
        changed = dict(self.manifest, address="127.0.0.1:9999")
        with self.assertRaises(ValueError):
            renewal.renew_manifest(changed, self.trust, self.seed, 3000)
        forged = dict(
            self.manifest, signature_base64=base64.b64encode(bytes(64)).decode()
        )
        with self.assertRaises(InvalidSignature):
            renewal.renew_manifest(forged, self.trust, self.seed, 3000)

    def test_clock_rollback_revoked_or_different_key_cannot_be_renewed(self):
        with self.assertRaises(ValueError):
            renewal.renew_manifest(self.manifest, self.trust, self.seed, 999)
        revoked = dict(self.trust, revoked_key_ids=["endpoint-one"])
        with self.assertRaises(ValueError):
            renewal.renew_manifest(self.manifest, revoked, self.seed, 3000)
        with self.assertRaises(ValueError):
            renewal.renew_manifest(
                self.manifest, self.trust, bytes(reversed(range(32))), 3000
            )


if __name__ == "__main__":
    unittest.main()
