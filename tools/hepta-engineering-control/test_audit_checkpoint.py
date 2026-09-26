from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringStore,
    HmacTrustStore,
    WorkEnvelope,
    semantic_digest,
)
from control_engineering_v2.audit_checkpoint import (
    AUDIT_CHECKPOINT_ISSUER,
    OWNER_STATE_ANCHOR_ISSUER,
    AuditCheckpointReceipt,
    OwnerStateAnchorReceipt,
    verify_audit_suffix,
    verify_owner_state_anchor,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, ZERO_DIGEST
from control_engineering_v2.external_controls import store_snapshot_digest


class AuditCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.commit = "a" * 40
        self.tree = "b" * 40
        self.trust = HmacTrustStore(
            {
                (AUDIT_CHECKPOINT_ISSUER, "checkpoint-key"): b"checkpoint",
                (OWNER_STATE_ANCHOR_ISSUER, "anchor-key"): b"anchor",
            }
        )

    def envelope(self, identity):
        return WorkEnvelope(
            identity,
            self.commit,
            self.tree,
            ("c" if identity.endswith("a") else "d") * 64,
            "e" * 64,
            "developer-productivity",
            (f"src/{identity}",),
            tuple(sorted(DENIED_AUTHORITIES)),
            1,
            self.now + 10_000_000_000,
        )

    def checkpoint(self, anchor):
        value = AuditCheckpointReceipt(
            self.commit,
            self.tree,
            int(anchor["sequence"]),
            str(anchor["eventDigest"]),
            AUDIT_CHECKPOINT_ISSUER,
            "checkpoint-key",
            self.now,
            self.now + 5_000_000_000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_signed_checkpoint_verifies_suffix_and_owner_anchor(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope("env-a"), now_ns=self.now)
                checkpoint = self.checkpoint(store.audit_anchor())
                store.issue_work_envelope(
                    self.envelope("env-b"),
                    now_ns=self.now + 1,
                )
                decision = verify_audit_suffix(
                    store,
                    checkpoint,
                    self.trust,
                    expected_source_commit=self.commit,
                    expected_source_tree=self.tree,
                    now_ns=self.now + 1,
                )
                self.assertEqual(decision.verified_suffix_rows, 1)
                current = store.audit_anchor()
                value = OwnerStateAnchorReceipt(
                    self.commit,
                    self.tree,
                    1,
                    ZERO_DIGEST,
                    semantic_digest(asdict(checkpoint)),
                    int(current["sequence"]),
                    str(current["eventDigest"]),
                    store_snapshot_digest(store),
                    OWNER_STATE_ANCHOR_ISSUER,
                    "anchor-key",
                    self.now + 1,
                    self.now + 5_000_000_000,
                )
                value = replace(
                    value,
                    signature=self.trust.sign(
                        value,
                        value.issuer,
                        value.signing_identity,
                    ),
                )
                digest = verify_owner_state_anchor(
                    store,
                    value,
                    checkpoint,
                    self.trust,
                    expected_source_commit=self.commit,
                    expected_source_tree=self.tree,
                    now_ns=self.now + 1,
                )
                self.assertEqual(len(digest), 64)

    def test_suffix_tamper_and_wrong_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope("env-a"), now_ns=self.now)
                checkpoint = self.checkpoint(store.audit_anchor())
                store.issue_work_envelope(
                    self.envelope("env-b"),
                    now_ns=self.now + 1,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "audit_checkpoint_source_mismatch",
                ):
                    verify_audit_suffix(
                        store,
                        checkpoint,
                        self.trust,
                        expected_source_commit="f" * 40,
                        expected_source_tree=self.tree,
                        now_ns=self.now + 1,
                    )
                store.connection.execute(
                    "UPDATE audit_events SET payload_json=? WHERE sequence=?",
                    (b"{}", 2),
                )
                store.connection.commit()
                with self.assertRaisesRegex(ValueError, "audit_chain_broken"):
                    verify_audit_suffix(
                        store,
                        checkpoint,
                        self.trust,
                        expected_source_commit=self.commit,
                        expected_source_tree=self.tree,
                        now_ns=self.now + 1,
                    )


if __name__ == "__main__":
    unittest.main()
