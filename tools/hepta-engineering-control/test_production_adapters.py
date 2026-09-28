from dataclasses import replace
from pathlib import Path
import base64
import subprocess
import tempfile
import unittest

from control_engineering_v2 import HmacTrustStore
from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2.external_controls import ProductionControlDecision
from control_engineering_v2.production_adapters import (
    ExternalProductionReceipt,
    OpenSslPublicKeyTrustStore,
    ProductionEvidenceDecision,
    PublicKeyBinding,
    REQUIRED_EXTERNAL_ROLES,
    verify_external_production_bundle,
)

_EVIDENCE_CLASSES = {
    "independent_ci_completion": "independent_ci_completion",
    "integration_terminal_observer": "integration_terminal_observation",
    "target_deployment_observer": "target_deployment_observation",
    "backup_restore_rehearsal_observer": "backup_restore_rehearsal",
    "rollback_rehearsal_observer": "rollback_rehearsal",
    "operator_acceptance": "operator_acceptance",
}


class ExternalProductionAdapterTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.commit = "a" * 40
        self.tree = "b" * 40
        self.target = "c" * 64
        self.keys = {
            (f"issuer-{index}", f"identity-{index}"): f"key-{index}".encode()
            for index, _ in enumerate(REQUIRED_EXTERNAL_ROLES)
        }
        self.trust = HmacTrustStore(self.keys)
        self.controls = ProductionControlDecision(True, True, True, "f" * 64)

    def receipts(self):
        result = {}
        for index, role in enumerate(REQUIRED_EXTERNAL_ROLES):
            value = ExternalProductionReceipt(
                role,
                f"provider-{index}",
                f"provider-instance-{index}",
                f"issuer-{index}",
                f"identity-{index}",
                self.commit,
                self.tree,
                self.target,
                f"{index + 1:064x}",
                _EVIDENCE_CLASSES[role],
                self.now,
                self.now + 60_000_000_000,
                f"nonce-{index}",
            )
            result[role] = replace(
                value,
                signature=self.trust.sign(
                    value, value.issuer, value.signing_identity
                ),
            )
        return result

    def verify(self, receipts=None, controls=None):
        return verify_external_production_bundle(
            self.receipts() if receipts is None else receipts,
            self.trust,
            production_controls=self.controls if controls is None else controls,
            expected_source_commit=self.commit,
            expected_source_tree=self.tree,
            expected_target_digest=self.target,
            now_ns=self.now + 1,
        )

    def test_complete_role_separated_bundle_verifies_without_granting_authority(self):
        decision = self.verify()
        self.assertIsInstance(decision, ProductionEvidenceDecision)
        self.assertTrue(decision.production_controls_verified)
        self.assertTrue(decision.production_evidence_complete)
        self.assertTrue(decision.deployment_observed)
        self.assertTrue(decision.backup_restore_rehearsed)
        self.assertFalse(decision.runtime_authority)
        self.assertFalse(decision.release_authority)

    def test_generic_receipts_cannot_replace_typed_owner_state_controls(self):
        with self.assertRaisesRegex(
            EngineeringError, "typed_production_controls_required"
        ):
            self.verify(controls=None)  # type: ignore[arg-type]
        incomplete = ProductionControlDecision(True, False, True, "e" * 64)
        with self.assertRaisesRegex(
            EngineeringError, "typed_production_controls_incomplete"
        ):
            self.verify(controls=incomplete)
        authority_delta = ProductionControlDecision(
            True, True, True, "e" * 64, runtime_authority=True
        )
        with self.assertRaisesRegex(
            EngineeringError, "typed_production_controls_authority_delta"
        ):
            self.verify(controls=authority_delta)

    def test_missing_role_fixture_and_identity_collision_fail_closed(self):
        missing = self.receipts()
        missing.pop(REQUIRED_EXTERNAL_ROLES[-1])
        with self.assertRaisesRegex(
            EngineeringError, "external_evidence_role_set"
        ):
            self.verify(missing)

        fixtures = self.receipts()
        role = REQUIRED_EXTERNAL_ROLES[0]
        fixtures[role] = replace(fixtures[role], provider="mock-provider")
        with self.assertRaisesRegex(
            EngineeringError, "external_evidence_fixture"
        ):
            self.verify(fixtures)

        collision = self.receipts()
        first, second = REQUIRED_EXTERNAL_ROLES[:2]
        collision[second] = replace(
            collision[second],
            provider_instance=collision[first].provider_instance,
            signing_identity=collision[first].signing_identity,
        )
        with self.assertRaisesRegex(
            EngineeringError, "external_evidence_role_collision"
        ):
            self.verify(collision)

    def test_openssl_ed25519_verifier_is_read_only(self):
        if not Path("/usr/bin/openssl").is_file():
            self.skipTest("OpenSSL unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            payload = root / "payload"
            signature = root / "signature"
            value = ExternalProductionReceipt(
                "operator_acceptance",
                "external-provider",
                "provider-instance",
                "operator-authority",
                "operator-key",
                self.commit,
                self.tree,
                self.target,
                "d" * 64,
                "operator_acceptance",
                self.now,
                self.now + 60_000_000_000,
                "nonce",
            )
            from control_engineering_v2.evidence import (
                HmacTrustStore as PayloadCodec,
            )

            payload.write_bytes(PayloadCodec.payload(value))
            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "genpkey",
                    "-algorithm",
                    "ED25519",
                    "-out",
                    str(private_key),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "pkey",
                    "-in",
                    str(private_key),
                    "-pubout",
                    "-out",
                    str(public_key),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "pkeyutl",
                    "-sign",
                    "-inkey",
                    str(private_key),
                    "-rawin",
                    "-in",
                    str(payload),
                    "-out",
                    str(signature),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            signed = replace(
                value,
                signature=base64.b64encode(signature.read_bytes()).decode(),
            )
            trust = OpenSslPublicKeyTrustStore(
                {
                    (
                        "operator-authority",
                        "operator-key",
                    ): PublicKeyBinding(str(public_key), "ed25519")
                }
            )
            self.assertTrue(
                trust.verify(
                    signed,
                    signed.issuer,
                    signed.signing_identity,
                    signed.signature,
                )
            )
            with self.assertRaisesRegex(
                RuntimeError, "external_private_key_unavailable"
            ):
                trust.sign(signed, signed.issuer, signed.signing_identity)


if __name__ == "__main__":
    unittest.main()
