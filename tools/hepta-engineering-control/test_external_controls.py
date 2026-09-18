from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import EngineeringStore, HmacTrustStore, WorkEnvelope
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
from control_engineering_v2.external_controls import (
    AuditAnchorAttestation,
    DistributedFenceReceipt,
    KeyCustodyReceipt,
    verify_distributed_fence,
    verify_external_audit_anchor,
    verify_external_key_custody,
)


class ExternalControlTests(unittest.TestCase):
    def setUp(self):
        self.now = 9_000_000
        self.trust = HmacTrustStore(
            {
                ("distributed_lease_authority", "lease-key"): b"lease",
                ("audit_anchor_service", "audit-key"): b"audit",
                ("key_custody_authority", "custody-key"): b"custody",
            }
        )
        self.envelope = WorkEnvelope(
            "env",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "owner",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            2,
            self.now + 1000,
        )

    def test_external_fence_binds_local_token_epoch_paths_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                lease = store.acquire_path_lease(
                    "lease",
                    "env",
                    "worker",
                    ("src/a",),
                    authority_epoch=7,
                    expires_unix_ns=self.now + 500,
                    now_ns=self.now,
                )
                from control_engineering_v2 import semantic_digest

                receipt = DistributedFenceReceipt(
                    "cluster",
                    "leader",
                    lease.lease_id,
                    lease.holder,
                    lease.epoch,
                    lease.fencing_token,
                    semantic_digest(lease.paths),
                    self.envelope.source_commit,
                    self.envelope.source_tree,
                    "1" * 64,
                    "distributed_lease_authority",
                    "lease-key",
                    self.now - 1,
                    self.now + 100,
                )
                receipt = replace(
                    receipt,
                    signature=self.trust.sign(
                        receipt, receipt.issuer, receipt.signing_identity
                    ),
                )
                digest = verify_distributed_fence(
                    lease, self.envelope, receipt, self.trust, now_ns=self.now
                )
                self.assertEqual(len(digest), 64)
                with self.assertRaisesRegex(ValueError, "distributed_fence_binding_mismatch"):
                    verify_distributed_fence(
                        lease,
                        self.envelope,
                        replace(receipt, fencing_token=lease.fencing_token + 1),
                        self.trust,
                        now_ns=self.now,
                    )

    def test_audit_anchor_must_match_current_store_head(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                anchor = store.audit_anchor()
                receipt = AuditAnchorAttestation(
                    anchor["sequence"],
                    anchor["eventDigest"],
                    self.envelope.source_commit,
                    "audit_anchor_service",
                    "audit-key",
                    self.now - 1,
                    self.now + 100,
                )
                receipt = replace(
                    receipt,
                    signature=self.trust.sign(
                        receipt, receipt.issuer, receipt.signing_identity
                    ),
                )
                self.assertEqual(
                    len(
                        verify_external_audit_anchor(
                            store,
                            self.envelope,
                            receipt,
                            self.trust,
                            now_ns=self.now,
                        )
                    ),
                    64,
                )

    def test_key_custody_requires_hardware_external_boundary_and_roles(self):
        receipt = KeyCustodyReceipt(
            "hsm-provider",
            "key-1",
            (
                "source_authority",
                "ci_executor",
                "independent_evaluator",
                "engineering_evidence_binder",
            ),
            True,
            True,
            "key_custody_authority",
            "custody-key",
            self.now - 1,
            self.now + 100,
        )
        receipt = replace(
            receipt,
            signature=self.trust.sign(receipt, receipt.issuer, receipt.signing_identity),
        )
        self.assertEqual(
            len(verify_external_key_custody(receipt, self.trust, now_ns=self.now)),
            64,
        )
        with self.assertRaisesRegex(ValueError, "key_custody_boundary"):
            verify_external_key_custody(
                replace(receipt, hardware_backed=False),
                self.trust,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
