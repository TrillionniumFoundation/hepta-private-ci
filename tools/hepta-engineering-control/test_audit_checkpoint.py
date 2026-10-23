from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import EngineeringStore, WorkEnvelope
from control_engineering_v2.audit_checkpoint import (
    advance_audit_checkpoint,
    create_audit_checkpoint,
    verify_audit_checkpoint,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringError


class AuditCheckpointTests(unittest.TestCase):
    def envelope(self, now):
        return WorkEnvelope(
            "checkpoint-envelope",
            "a" * 40,
            "b" * 40,
            hashlib.sha256(b"objective").hexdigest(),
            hashlib.sha256(b"contract").hexdigest(),
            "developer-productivity",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            1,
            now + 10_000,
        )

    def test_full_then_incremental_checkpoint_is_current(self):
        now = 1_000_000
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                first = create_audit_checkpoint(
                    store,
                    source_commit="a" * 40,
                    source_tree="b" * 40,
                    observed_unix_ns=now,
                )
                self.assertEqual(first.sequence, 0)
                store.issue_work_envelope(self.envelope(now), now_ns=now + 1)
                second = advance_audit_checkpoint(
                    store,
                    first,
                    source_commit="a" * 40,
                    source_tree="b" * 40,
                    observed_unix_ns=now + 2,
                )
                self.assertEqual(second.sequence, 1)
                self.assertEqual(second.previous_checkpoint_digest, first.checkpoint_digest)
                verify_audit_checkpoint(store, second)

    def test_owner_state_tamper_and_checkpoint_tamper_are_rejected(self):
        now = 2_000_000
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope(now), now_ns=now)
                checkpoint = create_audit_checkpoint(
                    store,
                    source_commit="c" * 40,
                    source_tree="d" * 40,
                    observed_unix_ns=now + 1,
                )
                store.connection.execute(
                    "UPDATE work_envelopes SET owner='tampered' WHERE envelope_id='checkpoint-envelope'"
                )
                with self.assertRaisesRegex(EngineeringError, "audit_checkpoint_state_drift"):
                    verify_audit_checkpoint(store, checkpoint)
                with self.assertRaisesRegex(EngineeringError, "audit_checkpoint_digest"):
                    verify_audit_checkpoint(
                        store,
                        replace(checkpoint, sequence=checkpoint.sequence + 1),
                        require_current_state=False,
                    )


if __name__ == "__main__":
    unittest.main()
