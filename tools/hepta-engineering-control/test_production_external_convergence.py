from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2.control_plane import (
    DENIED_AUTHORITIES,
    EngineeringStore,
    WorkEnvelope,
    semantic_digest,
)
from control_engineering_v2.evidence import HmacTrustStore
from control_engineering_v2.external_controls import (
    AuditAnchorAttestation,
    DistributedFenceReceipt,
    DistributedRevocationFrontierReceipt,
    KeyCustodyReceipt,
    store_snapshot_digest,
)
from control_engineering_v2.external_runtime import (
    ExternalProviderEndpoint,
    ProductionProviderSet,
)
from control_engineering_v2.production_external_composition import (
    ProductionExternalControlClient,
)


class ProductionExternalCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
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
            self.now + 1_000,
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

    @staticmethod
    def endpoint(service: str) -> ExternalProviderEndpoint:
        return ExternalProviderEndpoint(
            service,
            f"https://{service}.example/v1/receipt",
            "a" * 64,
        )

    def providers(self) -> ProductionProviderSet:
        return ProductionProviderSet(
            self.endpoint("distributed-lease-provider"),
            self.endpoint("immutable-audit-provider"),
            self.endpoint("key-custody-provider"),
            self.endpoint("independent-completion-provider"),
            self.endpoint("integration-terminal-provider"),
            self.endpoint("deployment-provider"),
            self.endpoint("operator-acceptance-provider"),
        )

    def test_real_provider_receipts_compose_through_existing_verifiers(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
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
                frontier = self.sign(
                    DistributedRevocationFrontierReceipt(
                        cluster_id="cluster",
                        leader_id="leader",
                        leader_term=3,
                        frontier_sequence=10,
                        frontier_digest="1" * 64,
                        issuer="distributed_lease_authority",
                        signing_identity="lease-key",
                        observed_unix_ns=self.now - 1,
                        expires_unix_ns=self.now + 600,
                    )
                )
                fence = self.sign(
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
                        observed_unix_ns=self.now - 2,
                        expires_unix_ns=self.now + 100,
                    )
                )

                outer = self

                class Transport:
                    counter = 0

                    def post(self, endpoint, body):
                        request = json.loads(body)
                        operation = request["operation"]
                        if operation == "revocation-frontier":
                            receipt = frontier
                        elif operation == "distributed-fence":
                            receipt = fence
                        elif operation == "audit-anchor":
                            anchor = store.audit_anchor()
                            receipt = outer.sign(
                                AuditAnchorAttestation(
                                    sequence=anchor["sequence"],
                                    event_digest=anchor["eventDigest"],
                                    envelope_id=outer.envelope.envelope_id,
                                    source_commit=outer.envelope.source_commit,
                                    source_tree=outer.envelope.source_tree,
                                    store_snapshot_digest=store_snapshot_digest(store),
                                    issuer="audit_anchor_service",
                                    signing_identity="audit-key",
                                    observed_unix_ns=outer.now - 1,
                                    expires_unix_ns=outer.now + 100,
                                )
                            )
                        elif operation == "key-custody":
                            role = request["payload"]["role"]
                            subject = request["payload"]["subjectSigningIdentity"]
                            receipt = outer.sign(
                                KeyCustodyReceipt(
                                    "hsm-provider",
                                    f"key-{role}",
                                    (role,),
                                    True,
                                    True,
                                    "key_custody_authority",
                                    "custody-key",
                                    outer.now - 1,
                                    outer.now + 100,
                                    subject_signing_identity=subject,
                                    algorithm="ed25519",
                                    public_key_digest=semantic_digest(
                                        {"role": role, "subject": subject, "kind": "public"}
                                    ),
                                    attestation_digest=semantic_digest(
                                        {"role": role, "subject": subject, "kind": "hsm"}
                                    ),
                                )
                            )
                        else:
                            raise AssertionError(f"unexpected provider operation: {operation}")
                        self.counter += 1
                        payload = json.loads(json.dumps(asdict(receipt)))
                        response = {
                            "schema": "hepta.control-engineering-provider-response.v1",
                            "service": request["service"],
                            "operation": operation,
                            "nonce": request["nonce"],
                            "requestDigest": request["requestDigest"],
                            "providerObservationId": f"observation-{self.counter}",
                            "providerObservedUnixNs": outer.now,
                            "providerExpiresUnixNs": outer.now + 100,
                            "payload": payload,
                            "payloadDigest": semantic_digest(payload),
                        }
                        return json.dumps(response).encode()

                client = ProductionExternalControlClient(
                    self.providers(),
                    self.trust,
                    transport=Transport(),
                )
                subjects = {
                    "source_authority": "subject-source",
                    "ci_executor": "subject-ci",
                    "independent_evaluator": "subject-review",
                    "engineering_evidence_binder": "subject-evidence",
                }
                decision, evidence = client.verify_controls(
                    store,
                    lease,
                    self.envelope,
                    key_subjects=subjects,
                    now_ns=self.now,
                )
                self.assertTrue(decision.distributed_fence_verified)
                self.assertTrue(decision.external_audit_anchor_verified)
                self.assertTrue(decision.external_key_custody_verified)
                self.assertEqual(len(evidence.provider_observation_digests), 7)
                self.assertEqual(len(evidence.key_custody_receipt_digests), 4)
                self.assertFalse(evidence.runtime_authority)
                self.assertFalse(evidence.merge_authority)
                self.assertFalse(evidence.deployment_authority)
                self.assertFalse(evidence.release_authority)

    def test_missing_or_colliding_key_subjects_fail_before_transport(self):
        class NoTransport:
            def post(self, endpoint, body):
                raise AssertionError("transport must not run")

        client = ProductionExternalControlClient(
            self.providers(),
            self.trust,
            transport=NoTransport(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
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
                with self.assertRaisesRegex(ValueError, "production_key_subject_roles"):
                    client.verify_controls(
                        store,
                        lease,
                        self.envelope,
                        key_subjects={"source_authority": "one"},
                        now_ns=self.now,
                    )
                colliding = {
                    "source_authority": "shared",
                    "ci_executor": "shared",
                    "independent_evaluator": "review",
                    "engineering_evidence_binder": "evidence",
                }
                with self.assertRaisesRegex(
                    ValueError, "production_key_subject_collision"
                ):
                    client.verify_controls(
                        store,
                        lease,
                        self.envelope,
                        key_subjects=colliding,
                        now_ns=self.now,
                    )


if __name__ == "__main__":
    unittest.main()
