from dataclasses import replace
import unittest

from control_engineering_v2 import HmacTrustStore
from control_engineering_v2.external import (
    AuditAnchorReceipt,
    ExternalFactReceipt,
    KeyCustodyReceipt,
    verify_audit_anchor,
    verify_external_fact_receipts,
    verify_key_custody,
)


class ExternalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.trust = HmacTrustStore(
            {
                ("audit_anchor_authority", "audit-key"): b"audit",
                ("key_custody_authority", "custody-key"): b"custody",
                ("deployment_authority", "deploy-key"): b"deploy",
            }
        )

    def sign(self, value):
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_external_audit_anchor_is_exact_and_authenticated(self):
        receipt = self.sign(
            AuditAnchorReceipt(
                "1" * 64,
                9,
                "2" * 64,
                "audit_anchor_authority",
                "audit-key",
                90,
                1000,
            )
        )
        digest = verify_audit_anchor(
            receipt,
            self.trust,
            expected_store_identity_digest="1" * 64,
            expected_sequence=9,
            expected_head_digest="2" * 64,
            now_ns=self.now,
        )
        self.assertEqual(len(digest), 64)

    def test_key_custody_requires_external_signature_and_roles(self):
        receipt = self.sign(
            KeyCustodyReceipt(
                "hsm-provider",
                "key-1",
                ("source_authority", "engineering_evidence_binder"),
                "3" * 64,
                "key_custody_authority",
                "custody-key",
                90,
                1000,
            )
        )
        digest = verify_key_custody(
            receipt,
            self.trust,
            required_roles=("source_authority",),
            now_ns=self.now,
        )
        self.assertEqual(len(digest), 64)
        with self.assertRaisesRegex(ValueError, "key_custody_role_missing"):
            verify_key_custody(
                receipt,
                self.trust,
                required_roles=("release_authority",),
                now_ns=self.now,
            )

    def test_deployment_facts_cannot_be_fake_booleans(self):
        receipt = ExternalFactReceipt(
            "deployment_observed",
            "4" * 64,
            "deployment_authority",
            "deploy-key",
            90,
            1000,
        )
        signed = self.sign(receipt)
        facts = verify_external_fact_receipts(
            (signed,),
            self.trust,
            subject_digest="4" * 64,
            now_ns=self.now,
        )
        self.assertIn("deployment_observed", facts)
        with self.assertRaisesRegex(ValueError, "external_fact_signature"):
            verify_external_fact_receipts(
                (replace(signed, signature="0" * 64),),
                self.trust,
                subject_digest="4" * 64,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
