from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from control_engineering_v2 import EngineeringStore, HmacTrustStore, WorkEnvelope, semantic_digest
from control_engineering_v2.audit_checkpoint import (
    AUDIT_CHECKPOINT_ISSUER,
    OWNER_STATE_ANCHOR_ISSUER,
    AuditCheckpointReceipt,
    OwnerStateAnchorReceipt,
    verify_owner_state_anchor,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, ZERO_DIGEST
from control_engineering_v2.external_controls import store_snapshot_digest


class IncrementalOwnerAnchorTests(unittest.TestCase):
    def test_owner_anchor_does_not_rescan_verified_audit_prefix(self):
        now = 1_000_000_000
        source_commit = "a" * 40
        source_tree = "b" * 40
        trust = HmacTrustStore(
            {
                (AUDIT_CHECKPOINT_ISSUER, "checkpoint-key"): b"checkpoint",
                (OWNER_STATE_ANCHOR_ISSUER, "anchor-key"): b"anchor",
            }
        )

        def envelope(identity: str, objective: str) -> WorkEnvelope:
            return WorkEnvelope(
                identity,
                source_commit,
                source_tree,
                objective * 64,
                "e" * 64,
                "developer-productivity",
                (f"src/{identity}",),
                tuple(sorted(DENIED_AUTHORITIES)),
                1,
                now + 10_000_000_000,
            )

        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(envelope("env-a", "c"), now_ns=now)
                prefix = store.audit_anchor()
                checkpoint = AuditCheckpointReceipt(
                    source_commit,
                    source_tree,
                    int(prefix["sequence"]),
                    str(prefix["eventDigest"]),
                    AUDIT_CHECKPOINT_ISSUER,
                    "checkpoint-key",
                    now,
                    now + 5_000_000_000,
                )
                checkpoint = replace(
                    checkpoint,
                    signature=trust.sign(
                        checkpoint,
                        checkpoint.issuer,
                        checkpoint.signing_identity,
                    ),
                )
                store.issue_work_envelope(
                    envelope("env-b", "d"),
                    now_ns=now + 1,
                )
                current = store.audit_anchor()
                snapshot = store_snapshot_digest(store)
                anchor = OwnerStateAnchorReceipt(
                    source_commit,
                    source_tree,
                    1,
                    ZERO_DIGEST,
                    semantic_digest(asdict(checkpoint)),
                    int(current["sequence"]),
                    str(current["eventDigest"]),
                    snapshot,
                    OWNER_STATE_ANCHOR_ISSUER,
                    "anchor-key",
                    now + 1,
                    now + 5_000_000_000,
                )
                anchor = replace(
                    anchor,
                    signature=trust.sign(
                        anchor,
                        anchor.issuer,
                        anchor.signing_identity,
                    ),
                )
                with patch.object(
                    store,
                    "verify_audit_chain",
                    side_effect=AssertionError("full audit scan was invoked"),
                ):
                    digest = verify_owner_state_anchor(
                        store,
                        anchor,
                        checkpoint,
                        trust,
                        expected_source_commit=source_commit,
                        expected_source_tree=source_tree,
                        now_ns=now + 1,
                    )
                self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
