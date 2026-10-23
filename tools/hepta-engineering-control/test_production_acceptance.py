import json
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import EngineeringStore, WorkEnvelope
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringError
from control_engineering_v2.production_acceptance import (
    _load_owner_state,
    _load_typed_controls,
)


class ProductionAcceptanceInputTests(unittest.TestCase):
    def envelope(self, envelope_id: str, now: int) -> WorkEnvelope:
        return WorkEnvelope(
            envelope_id,
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            2,
            now + 10_000,
        )

    def test_owner_state_is_reconstructed_and_cross_envelope_mix_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "engineering.sqlite3"
            now = 1_000_000
            with EngineeringStore(database) as store:
                first = self.envelope("env-a", now)
                second = self.envelope("env-b", now)
                store.issue_work_envelope(first, now_ns=now)
                store.issue_work_envelope(second, now_ns=now)
                lease = store.acquire_path_lease(
                    "lease-b",
                    second.envelope_id,
                    "worker-b",
                    ("src/b",),
                    authority_epoch=1,
                    expires_unix_ns=now + 5_000,
                    now_ns=now + 1,
                )
                loaded_envelope, loaded_lease = _load_owner_state(
                    store,
                    envelope_id=second.envelope_id,
                    lease_id=lease.lease_id,
                )
                self.assertEqual(loaded_envelope, second)
                self.assertEqual(loaded_lease, lease)
                with self.assertRaisesRegex(
                    EngineeringError, "production_acceptance_owner_binding"
                ):
                    _load_owner_state(
                        store,
                        envelope_id=first.envelope_id,
                        lease_id=lease.lease_id,
                    )

    def test_typed_control_json_normalizes_key_custody_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "typed-controls.json"
            path.write_text(
                json.dumps(
                    {
                        "distributedFence": {
                            "cluster_id": "cluster-a",
                            "leader_id": "leader-a",
                            "leader_term": 1,
                            "lease_id": "lease-a",
                            "holder": "worker-a",
                            "authority_epoch": 1,
                            "fencing_token": 1,
                            "lease_revision": 1,
                            "lease_expires_unix_ns": 2_000_000,
                            "envelope_id": "env-a",
                            "envelope_revision": 1,
                            "paths_digest": "1" * 64,
                            "source_commit": "a" * 40,
                            "source_tree": "b" * 40,
                            "revocation_frontier_sequence": 1,
                            "revocation_frontier_digest": "2" * 64,
                            "issuer": "distributed_lease_authority",
                            "signing_identity": "distributed-key",
                            "observed_unix_ns": 1_000_000,
                            "expires_unix_ns": 1_500_000,
                            "signature": "signature",
                        },
                        "revocationFrontier": {
                            "cluster_id": "cluster-a",
                            "leader_id": "leader-a",
                            "leader_term": 1,
                            "frontier_sequence": 1,
                            "frontier_digest": "2" * 64,
                            "issuer": "distributed_lease_authority",
                            "signing_identity": "distributed-key",
                            "observed_unix_ns": 1_000_000,
                            "expires_unix_ns": 1_500_000,
                            "signature": "signature",
                        },
                        "auditAnchor": {
                            "sequence": 1,
                            "event_digest": "3" * 64,
                            "envelope_id": "env-a",
                            "source_commit": "a" * 40,
                            "source_tree": "b" * 40,
                            "store_snapshot_digest": "4" * 64,
                            "issuer": "external_audit_authority",
                            "signing_identity": "audit-key",
                            "observed_unix_ns": 1_000_000,
                            "expires_unix_ns": 1_500_000,
                            "signature": "signature",
                        },
                        "keyCustody": [
                            {
                                "provider": "kms-provider",
                                "key_id": "key-a",
                                "roles": ["ci_executor"],
                                "hardware_backed": True,
                                "external_to_engineering": True,
                                "issuer": "key_custody_authority",
                                "signing_identity": "custody-key",
                                "observed_unix_ns": 1_000_000,
                                "expires_unix_ns": 1_500_000,
                                "signature": "signature",
                                "subject_signing_identity": "ci-key",
                                "algorithm": "ed25519",
                                "public_key_digest": "5" * 64,
                                "attestation_digest": "6" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            distributed, frontier, audit, custody = _load_typed_controls(path)
            self.assertEqual(distributed.lease_id, "lease-a")
            self.assertEqual(frontier.frontier_sequence, 1)
            self.assertEqual(audit.envelope_id, "env-a")
            self.assertEqual(custody[0].roles, ("ci_executor",))

    def test_typed_control_bundle_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "typed-controls.json"
            path.write_text(
                '{"distributedFence":{},"distributedFence":{},'
                '"revocationFrontier":{},"auditAnchor":{},"keyCustody":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                _load_typed_controls(path)


if __name__ == "__main__":
    unittest.main()
