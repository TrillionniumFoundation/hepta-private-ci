from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    DistributedRevocationFrontierReceipt,
    EngineeringStore,
    HmacTrustStore,
    WorkEnvelope,
    semantic_digest,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
from control_engineering_v2.external_controls import (
    AuditAnchorAttestation,
    DistributedFenceReceipt,
    KeyCustodyReceipt,
    verify_distributed_fence,
    verify_distributed_revocation_frontier,
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

    def sign(self, value):
        return replace(
            value,
            signature=self.trust.sign(
                value,
                value.issuer,
                value.signing_identity,
            ),
        )

    def frontier(
        self,
        *,
        sequence=10,
        digest="1" * 64,
        leader_term=3,
        observed_offset=-1,
        expires_offset=600,
    ):
        return self.sign(
            DistributedRevocationFrontierReceipt(
                cluster_id="cluster",
                leader_id="leader",
                leader_term=leader_term,
                frontier_sequence=sequence,
                frontier_digest=digest,
                issuer="distributed_lease_authority",
                signing_identity="lease-key",
                observed_unix_ns=self.now + observed_offset,
                expires_unix_ns=self.now + expires_offset,
            )
        )

    def fence(self, lease, frontier, *, observed_offset=-2, expires_offset=100):
        return self.sign(
            DistributedFenceReceipt(
                cluster_id=frontier.cluster_id,
                leader_id=frontier.leader_id,
                leader_term=frontier.leader_term,
                lease_id=lease.lease_id,
                holder=lease.holder,
                authority_epoch=lease.epoch,
                fencing_token=lease.fencing_token,
                lease_revision=lease.revision,
                lease_expires_unix_ns=lease.expires_unix_ns,
                envelope_id=self.envelope.envelope_id,
                envelope_revision=self.envelope.revision,
                paths_digest=semantic_digest(lease.paths),
                source_commit=self.envelope.source_commit,
                source_tree=self.envelope.source_tree,
                revocation_frontier_sequence=frontier.frontier_sequence,
                revocation_frontier_digest=frontier.frontier_digest,
                issuer="distributed_lease_authority",
                signing_identity="lease-key",
                observed_unix_ns=self.now + observed_offset,
                expires_unix_ns=self.now + expires_offset,
            )
        )

    def test_external_fence_binds_current_local_and_distributed_frontiers(self):
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
                frontier = self.frontier()
                receipt = self.fence(lease, frontier)
                digest = verify_distributed_fence(
                    lease,
                    self.envelope,
                    receipt,
                    frontier,
                    self.trust,
                    store=store,
                    now_ns=self.now,
                )
                self.assertEqual(len(digest), 64)

                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_fence_binding_mismatch",
                ):
                    verify_distributed_fence(
                        lease,
                        self.envelope,
                        replace(
                            receipt,
                            fencing_token=lease.fencing_token + 1,
                        ),
                        frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    )

                widened = self.sign(
                    replace(
                        receipt,
                        expires_unix_ns=lease.expires_unix_ns + 1,
                        signature="",
                    )
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_fence_window_exceeds_owner",
                ):
                    verify_distributed_fence(
                        lease,
                        self.envelope,
                        widened,
                        frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    )

                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_fence_envelope_mismatch",
                ):
                    verify_distributed_fence(
                        replace(lease, envelope_id="other"),
                        self.envelope,
                        receipt,
                        frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    )

                newer_frontier = self.frontier(
                    sequence=11,
                    digest="2" * 64,
                    observed_offset=0,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_fence_revocation_frontier_mismatch",
                ):
                    verify_distributed_fence(
                        lease,
                        self.envelope,
                        receipt,
                        newer_frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    )

                older_frontier = self.frontier(observed_offset=-3)
                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_fence_revocation_frontier_older",
                ):
                    verify_distributed_fence(
                        lease,
                        self.envelope,
                        receipt,
                        older_frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    )

                store.transition_path_lease(
                    lease.lease_id,
                    expected_revision=lease.revision,
                    authority_epoch=lease.epoch,
                    disposition="revoke",
                    now_ns=self.now,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_fence_local_lease_stale",
                ):
                    verify_distributed_fence(
                        lease,
                        self.envelope,
                        receipt,
                        frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    )

    def test_revocation_frontier_requires_order_freshness_and_signature(self):
        frontier = self.frontier()
        self.assertEqual(
            len(
                verify_distributed_revocation_frontier(
                    frontier,
                    self.trust,
                    now_ns=self.now,
                )
            ),
            64,
        )
        with self.assertRaisesRegex(
            ValueError,
            "distributed_revocation_frontier_order",
        ):
            verify_distributed_revocation_frontier(
                replace(frontier, frontier_sequence=0),
                self.trust,
                now_ns=self.now,
            )
        with self.assertRaisesRegex(
            ValueError,
            "distributed_revocation_frontier_signature",
        ):
            verify_distributed_revocation_frontier(
                replace(frontier, signature="0" * 64),
                self.trust,
                now_ns=self.now,
            )

    def test_audit_anchor_must_match_current_store_head_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                anchor = store.audit_anchor()
                receipt = self.sign(
                    AuditAnchorAttestation(
                        sequence=anchor["sequence"],
                        event_digest=anchor["eventDigest"],
                        envelope_id=self.envelope.envelope_id,
                        source_commit=self.envelope.source_commit,
                        source_tree=self.envelope.source_tree,
                        issuer="audit_anchor_service",
                        signing_identity="audit-key",
                        observed_unix_ns=self.now - 1,
                        expires_unix_ns=self.now + 100,
                    )
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
                drifted = self.sign(
                    replace(
                        receipt,
                        source_tree="f" * 40,
                        signature="",
                    )
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "audit_anchor_binding_mismatch",
                ):
                    verify_external_audit_anchor(
                        store,
                        self.envelope,
                        drifted,
                        self.trust,
                        now_ns=self.now,
                    )

    def test_empty_audit_chain_cannot_be_externally_attested_as_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                receipt = self.sign(
                    AuditAnchorAttestation(
                        sequence=0,
                        event_digest="0" * 64,
                        envelope_id=self.envelope.envelope_id,
                        source_commit=self.envelope.source_commit,
                        source_tree=self.envelope.source_tree,
                        issuer="audit_anchor_service",
                        signing_identity="audit-key",
                        observed_unix_ns=self.now - 1,
                        expires_unix_ns=self.now + 100,
                    )
                )
                with self.assertRaisesRegex(ValueError, "audit_anchor_empty"):
                    verify_external_audit_anchor(
                        store,
                        self.envelope,
                        receipt,
                        self.trust,
                        now_ns=self.now,
                    )

    def test_key_custody_requires_hardware_external_boundary_and_roles(self):
        receipt = self.sign(
            KeyCustodyReceipt(
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
        )
        self.assertEqual(
            len(
                verify_external_key_custody(
                    receipt,
                    self.trust,
                    now_ns=self.now,
                )
            ),
            64,
        )
        with self.assertRaisesRegex(ValueError, "key_custody_boundary"):
            verify_external_key_custody(
                replace(receipt, hardware_backed=False),
                self.trust,
                now_ns=self.now,
            )
        duplicate = self.sign(
            replace(
                receipt,
                roles=receipt.roles + ("source_authority",),
                signature="",
            )
        )
        with self.assertRaisesRegex(ValueError, "key_custody_roles"):
            verify_external_key_custody(
                duplicate,
                self.trust,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
