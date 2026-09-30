from __future__ import annotations

from dataclasses import asdict, replace
import unittest

from control_engineering_v2 import HmacTrustStore
from control_engineering_v2.control_plane import EngineeringError, semantic_digest
from control_engineering_v2.key_custody_continuity import (
    CustodiedKeyBinding,
    KeyCustodyContinuityReceipt,
    key_set_digest,
    verify_key_custody_continuity,
)


class KeyCustodyContinuityTests(unittest.TestCase):
    now = 1_000_000
    repository = "TrillionniumFoundation/hepta-private-ci"
    source_sha = "1" * 40
    merge_sha = "2" * 40

    def setUp(self) -> None:
        self.trust = HmacTrustStore(
            {("key_custody_authority", "custody-attestor-v1"): b"custody-secret"}
        )

    @staticmethod
    def keys(prefix: str) -> tuple[CustodiedKeyBinding, ...]:
        roles = (
            "source_authority",
            "ci_executor",
            "independent_evaluator",
            "engineering_evidence_binder",
        )
        return tuple(
            CustodiedKeyBinding(
                role=role,
                provider="kms-prod",
                key_id=f"{prefix}-{index}",
                algorithm="ed25519",
                subject_signing_identity=f"{prefix}-identity-{index}",
                public_key_digest=f"{index + 1:x}" * 64,
                attestation_digest=f"{index + 5:x}" * 64,
                hardware_backed=True,
                external_to_engineering=True,
            )
            for index, role in enumerate(roles)
        )

    def sign(self, value: KeyCustodyContinuityReceipt) -> KeyCustodyContinuityReceipt:
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def genesis(self) -> KeyCustodyContinuityReceipt:
        return self.sign(
            KeyCustodyContinuityReceipt(
                repository=self.repository,
                source_sha=self.source_sha,
                merge_sha=self.merge_sha,
                rotation_epoch=1,
                rotation_state="active",
                previous_set_digest="0" * 64,
                revocation_frontier_digest="a" * 64,
                external_audit_anchor_digest="b" * 64,
                current_keys=self.keys("epoch-one"),
                retiring_keys=(),
                dual_window_expires_unix_ns=0,
                issuer="key_custody_authority",
                signing_identity="custody-attestor-v1",
                observed_unix_ns=self.now - 100,
                expires_unix_ns=self.now + 10_000,
            )
        )

    def test_genesis_epoch_is_exact_candidate_bound(self) -> None:
        receipt = self.genesis()
        digest = verify_key_custody_continuity(
            receipt,
            self.trust,
            expected_repository=self.repository,
            expected_source_sha=self.source_sha,
            expected_merge_sha=self.merge_sha,
            now_ns=self.now,
        )
        self.assertEqual(digest, semantic_digest(asdict(receipt)))
        self.assertEqual(
            key_set_digest(receipt.current_keys, rotation_epoch=1),
            key_set_digest(tuple(reversed(receipt.current_keys)), rotation_epoch=1),
        )

    def test_dual_window_binds_predecessor_and_distinct_keys(self) -> None:
        previous = self.genesis()
        value = KeyCustodyContinuityReceipt(
            repository=self.repository,
            source_sha=self.source_sha,
            merge_sha=self.merge_sha,
            rotation_epoch=2,
            rotation_state="dual_window",
            previous_set_digest=semantic_digest(asdict(previous)),
            revocation_frontier_digest="c" * 64,
            external_audit_anchor_digest="d" * 64,
            current_keys=self.keys("epoch-two"),
            retiring_keys=tuple(sorted(previous.current_keys, key=lambda row: row.role)),
            dual_window_expires_unix_ns=self.now + 500,
            issuer="key_custody_authority",
            signing_identity="custody-attestor-v1",
            observed_unix_ns=self.now - 10,
            expires_unix_ns=self.now + 1_000,
        )
        receipt = self.sign(value)
        self.assertRegex(
            verify_key_custody_continuity(
                receipt,
                self.trust,
                expected_repository=self.repository,
                expected_source_sha=self.source_sha,
                expected_merge_sha=self.merge_sha,
                previous_receipt=previous,
                now_ns=self.now,
            ),
            r"^[0-9a-f]{64}$",
        )

    def test_non_genesis_epoch_requires_exact_predecessor(self) -> None:
        previous = self.genesis()
        value = KeyCustodyContinuityReceipt(
            repository=self.repository,
            source_sha=self.source_sha,
            merge_sha=self.merge_sha,
            rotation_epoch=2,
            rotation_state="active",
            previous_set_digest="e" * 64,
            revocation_frontier_digest="c" * 64,
            external_audit_anchor_digest="d" * 64,
            current_keys=self.keys("epoch-two"),
            retiring_keys=(),
            dual_window_expires_unix_ns=0,
            issuer="key_custody_authority",
            signing_identity="custody-attestor-v1",
            observed_unix_ns=self.now - 10,
            expires_unix_ns=self.now + 1_000,
        )
        receipt = self.sign(value)
        with self.assertRaisesRegex(EngineeringError, "key_custody_previous_receipt_required"):
            verify_key_custody_continuity(
                receipt,
                self.trust,
                expected_repository=self.repository,
                expected_source_sha=self.source_sha,
                expected_merge_sha=self.merge_sha,
                now_ns=self.now,
            )
        with self.assertRaisesRegex(EngineeringError, "key_custody_previous_set_mismatch"):
            verify_key_custody_continuity(
                receipt,
                self.trust,
                expected_repository=self.repository,
                expected_source_sha=self.source_sha,
                expected_merge_sha=self.merge_sha,
                previous_receipt=previous,
                now_ns=self.now,
            )

    def test_rotation_rejects_reused_keys_and_identity(self) -> None:
        previous = self.genesis()
        value = KeyCustodyContinuityReceipt(
            repository=self.repository,
            source_sha=self.source_sha,
            merge_sha=self.merge_sha,
            rotation_epoch=2,
            rotation_state="dual_window",
            previous_set_digest=semantic_digest(asdict(previous)),
            revocation_frontier_digest="c" * 64,
            external_audit_anchor_digest="d" * 64,
            current_keys=previous.current_keys,
            retiring_keys=tuple(sorted(previous.current_keys, key=lambda row: row.role)),
            dual_window_expires_unix_ns=self.now + 500,
            issuer="key_custody_authority",
            signing_identity="custody-attestor-v1",
            observed_unix_ns=self.now - 10,
            expires_unix_ns=self.now + 1_000,
        )
        receipt = self.sign(value)
        with self.assertRaisesRegex(EngineeringError, "key_custody_rotation_reuse"):
            verify_key_custody_continuity(
                receipt,
                self.trust,
                expected_repository=self.repository,
                expected_source_sha=self.source_sha,
                expected_merge_sha=self.merge_sha,
                previous_receipt=previous,
                now_ns=self.now,
            )

    def test_candidate_drift_and_signature_tampering_fail_closed(self) -> None:
        receipt = self.genesis()
        with self.assertRaisesRegex(EngineeringError, "key_custody_source_mismatch"):
            verify_key_custody_continuity(
                receipt,
                self.trust,
                expected_repository=self.repository,
                expected_source_sha="3" * 40,
                expected_merge_sha=self.merge_sha,
                now_ns=self.now,
            )
        tampered = replace(receipt, external_audit_anchor_digest="f" * 64)
        with self.assertRaisesRegex(EngineeringError, "key_custody_continuity_signature"):
            verify_key_custody_continuity(
                tampered,
                self.trust,
                expected_repository=self.repository,
                expected_source_sha=self.source_sha,
                expected_merge_sha=self.merge_sha,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
