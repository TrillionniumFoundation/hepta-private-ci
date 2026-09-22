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
    admit_distributed_fence,
    distributed_fence_frontier,
    verify_distributed_fence,
    verify_persisted_distributed_fence,
    verify_distributed_revocation_frontier,
    verify_external_audit_anchor,
    verify_external_key_custody,
    verify_production_controls,
    store_snapshot_digest,
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
                self.assertEqual(
                    admit_distributed_fence(
                        lease,
                        self.envelope,
                        receipt,
                        frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    ),
                    digest,
                )
                persisted = distributed_fence_frontier(
                    store,
                    receipt.cluster_id,
                    receipt.holder,
                )
                self.assertEqual(persisted["fenceReceiptDigest"], digest)

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

    def test_persisted_distributed_frontier_rejects_restart_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "store.db"
            with EngineeringStore(database) as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                lease = store.acquire_path_lease(
                    "lease-restart",
                    "env",
                    "worker-restart",
                    ("src/restart",),
                    authority_epoch=9,
                    expires_unix_ns=self.now + 500,
                    now_ns=self.now,
                )
                old_frontier = self.frontier(
                    sequence=10,
                    digest="1" * 64,
                    observed_offset=-1,
                )
                old_fence = self.fence(lease, old_frontier)
                admit_distributed_fence(
                    lease,
                    self.envelope,
                    old_fence,
                    old_frontier,
                    self.trust,
                    store=store,
                    now_ns=self.now,
                )

                new_frontier = self.frontier(
                    sequence=11,
                    digest="2" * 64,
                    observed_offset=0,
                )
                new_fence = self.fence(lease, new_frontier)
                new_digest = admit_distributed_fence(
                    lease,
                    self.envelope,
                    new_fence,
                    new_frontier,
                    self.trust,
                    store=store,
                    now_ns=self.now,
                )
                self.assertEqual(
                    distributed_fence_frontier(
                        store,
                        new_fence.cluster_id,
                        new_fence.holder,
                    )["fenceReceiptDigest"],
                    new_digest,
                )

            with EngineeringStore(database) as reopened:
                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_cluster_frontier_not_current",
                ):
                    verify_persisted_distributed_fence(
                        lease,
                        self.envelope,
                        old_fence,
                        old_frontier,
                        self.trust,
                        store=reopened,
                        now_ns=self.now,
                    )
                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_cluster_frontier_stale",
                ):
                    admit_distributed_fence(
                        lease,
                        self.envelope,
                        old_fence,
                        old_frontier,
                        self.trust,
                        store=reopened,
                        now_ns=self.now,
                    )

    def test_new_cluster_leader_fences_stale_receipts_for_other_holders(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                lease_a = store.acquire_path_lease(
                    "lease-a",
                    "env",
                    "worker-a",
                    ("src/a",),
                    authority_epoch=1,
                    expires_unix_ns=self.now + 500,
                    now_ns=self.now,
                )
                lease_b = store.acquire_path_lease(
                    "lease-b",
                    "env",
                    "worker-b",
                    ("src/b",),
                    authority_epoch=1,
                    expires_unix_ns=self.now + 500,
                    now_ns=self.now,
                )
                old_frontier = self.frontier(
                    sequence=10,
                    digest="1" * 64,
                    leader_term=3,
                )
                stale_b = self.fence(lease_b, old_frontier)
                new_frontier = self.frontier(
                    sequence=11,
                    digest="2" * 64,
                    leader_term=4,
                    observed_offset=0,
                )
                current_a = self.fence(lease_a, new_frontier)
                admit_distributed_fence(
                    lease_a,
                    self.envelope,
                    current_a,
                    new_frontier,
                    self.trust,
                    store=store,
                    now_ns=self.now,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "distributed_cluster_frontier_stale",
                ):
                    admit_distributed_fence(
                        lease_b,
                        self.envelope,
                        stale_b,
                        old_frontier,
                        self.trust,
                        store=store,
                        now_ns=self.now,
                    )

    def test_same_cluster_frontier_allows_newer_local_lease_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                lease = store.acquire_path_lease(
                    "lease-renew",
                    "env",
                    "worker-renew",
                    ("src/renew",),
                    authority_epoch=2,
                    expires_unix_ns=self.now + 400,
                    now_ns=self.now,
                )
                frontier = self.frontier()
                first = self.fence(lease, frontier)
                admit_distributed_fence(
                    lease,
                    self.envelope,
                    first,
                    frontier,
                    self.trust,
                    store=store,
                    now_ns=self.now,
                )
                renewed = store.transition_path_lease(
                    lease.lease_id,
                    expected_revision=lease.revision,
                    authority_epoch=lease.epoch,
                    disposition="renew",
                    new_expiry_unix_ns=self.now + 500,
                    now_ns=self.now,
                )
                second = self.fence(renewed, frontier)
                admit_distributed_fence(
                    renewed,
                    self.envelope,
                    second,
                    frontier,
                    self.trust,
                    store=store,
                    now_ns=self.now,
                )
                persisted = distributed_fence_frontier(
                    store,
                    second.cluster_id,
                    second.holder,
                )
                self.assertEqual(persisted["leaseRevision"], renewed.revision)
                self.assertEqual(persisted["fencingToken"], renewed.fencing_token)
                self.assertEqual(
                    persisted["clusterRevocationFrontierSequence"],
                    frontier.frontier_sequence,
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
                        store_snapshot_digest=store_snapshot_digest(store),
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

    def test_audit_anchor_detects_owner_table_tampering_without_audit_event(self):
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
                        store_snapshot_digest=store_snapshot_digest(store),
                        issuer="audit_anchor_service",
                        signing_identity="audit-key",
                        observed_unix_ns=self.now - 1,
                        expires_unix_ns=self.now + 100,
                    )
                )
                store.connection.execute(
                    "UPDATE work_envelopes SET owner=? WHERE envelope_id=?",
                    ("tampered-owner", self.envelope.envelope_id),
                )
                store.connection.commit()
                with self.assertRaisesRegex(
                    ValueError,
                    "audit_anchor_binding_mismatch",
                ):
                    verify_external_audit_anchor(
                        store,
                        self.envelope,
                        receipt,
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
                        store_snapshot_digest=store_snapshot_digest(store),
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

    def test_production_controls_compose_current_fence_anchor_and_separate_keys(self):
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
                fence = self.fence(lease, frontier)
                admit_distributed_fence(
                    lease,
                    self.envelope,
                    fence,
                    frontier,
                    self.trust,
                    store=store,
                    now_ns=self.now,
                )
                anchor = store.audit_anchor()
                audit = self.sign(
                    AuditAnchorAttestation(
                        sequence=anchor["sequence"],
                        event_digest=anchor["eventDigest"],
                        envelope_id=self.envelope.envelope_id,
                        source_commit=self.envelope.source_commit,
                        source_tree=self.envelope.source_tree,
                        store_snapshot_digest=store_snapshot_digest(store),
                        issuer="audit_anchor_service",
                        signing_identity="audit-key",
                        observed_unix_ns=self.now - 1,
                        expires_unix_ns=self.now + 100,
                    )
                )
                decision = verify_production_controls(
                    lease,
                    self.envelope,
                    fence,
                    frontier,
                    store,
                    audit,
                    self.custody_set(),
                    self.trust,
                    now_ns=self.now,
                )
                self.assertTrue(decision.distributed_fence_verified)
                self.assertTrue(decision.external_audit_anchor_verified)
                self.assertTrue(decision.external_key_custody_verified)
                self.assertEqual(len(decision.evidence_digest), 64)
                self.assertNotEqual(decision.evidence_digest, "0" * 64)
                self.assertFalse(decision.runtime_authority)
                self.assertFalse(decision.merge_authority)
                self.assertFalse(decision.release_authority)

    def custody_receipt(self, role: str, key_id: str) -> KeyCustodyReceipt:
        return self.sign(
            KeyCustodyReceipt(
                "hsm-provider",
                key_id,
                (role,),
                True,
                True,
                "key_custody_authority",
                "custody-key",
                self.now - 1,
                self.now + 100,
                subject_signing_identity=f"subject-{role}",
                algorithm="ed25519",
                public_key_digest=semantic_digest(
                    {"role": role, "keyId": key_id, "kind": "public-key"}
                ),
                attestation_digest=semantic_digest(
                    {"provider": "hsm-provider", "role": role, "keyId": key_id}
                ),
            )
        )

    def custody_set(self) -> tuple[KeyCustodyReceipt, ...]:
        return tuple(
            self.custody_receipt(role, f"key-{index}")
            for index, role in enumerate(
                (
                    "source_authority",
                    "ci_executor",
                    "independent_evaluator",
                    "engineering_evidence_binder",
                ),
                start=1,
            )
        )

    def test_key_custody_requires_hardware_external_boundary_and_roles(self):
        receipts = self.custody_set()
        self.assertEqual(
            len(
                verify_external_key_custody(
                    receipts,
                    self.trust,
                    now_ns=self.now,
                )
            ),
            64,
        )

        weak = (
            self.sign(
                replace(
                    receipts[0],
                    hardware_backed=False,
                    signature="",
                )
            ),
            *receipts[1:],
        )
        with self.assertRaisesRegex(ValueError, "key_custody_boundary"):
            verify_external_key_custody(
                weak,
                self.trust,
                now_ns=self.now,
            )

        missing = receipts[:-1]
        with self.assertRaisesRegex(ValueError, "key_custody_roles"):
            verify_external_key_custody(
                missing,
                self.trust,
                now_ns=self.now,
            )

    def test_key_custody_rejects_one_key_or_receipt_for_separated_roles(self):
        combined = self.sign(
            KeyCustodyReceipt(
                "hsm-provider",
                "omnipotent-key",
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
                subject_signing_identity="subject-omnipotent",
                algorithm="ed25519",
                public_key_digest="a" * 64,
                attestation_digest="b" * 64,
            )
        )
        with self.assertRaisesRegex(ValueError, "key_custody_role_separation"):
            verify_external_key_custody(
                combined,
                self.trust,
                now_ns=self.now,
            )

        receipts = list(self.custody_set())
        receipts[1] = self.sign(
            replace(
                receipts[1],
                key_id=receipts[0].key_id,
                signature="",
            )
        )
        with self.assertRaisesRegex(ValueError, "key_custody_role_separation"):
            verify_external_key_custody(
                tuple(receipts),
                self.trust,
                now_ns=self.now,
            )

        receipts = list(self.custody_set())
        receipts[1] = self.sign(
            replace(
                receipts[1],
                subject_signing_identity=receipts[0].subject_signing_identity,
                signature="",
            )
        )
        with self.assertRaisesRegex(ValueError, "key_custody_role_separation"):
            verify_external_key_custody(
                tuple(receipts),
                self.trust,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
