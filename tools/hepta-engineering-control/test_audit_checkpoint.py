from pathlib import Path
import tempfile
import unittest

from control_engineering_v2.audit_checkpoint import (
    build_audit_checkpoint,
    verify_audit_suffix,
    verify_current_audit_checkpoint,
)
from control_engineering_v2.clock import ClockPolicy, FixedClock
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
from control_engineering_v2.evidence import HmacTrustStore


class AuditCheckpointTests(unittest.TestCase):
    def test_checkpoint_verifies_current_state_then_only_appended_suffix(self):
        now = 1_000_000
        trust = HmacTrustStore({("audit_checkpoint_authority", "checkpoint-key"): b"key"})
        policy = ClockPolicy(10, 10_000, 10_000_000)
        clock = FixedClock(now)
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                first = WorkEnvelope(
                    "first",
                    "a" * 40,
                    "b" * 40,
                    "c" * 64,
                    "d" * 64,
                    "developer-productivity",
                    ("src",),
                    tuple(sorted(DENIED_AUTHORITIES)),
                    1,
                    now + 9_000_000,
                )
                store.issue_work_envelope(first, now_ns=now)
                checkpoint, anchor = build_audit_checkpoint(
                    store,
                    source_commit="a" * 40,
                    source_tree="b" * 40,
                    issuer="audit_checkpoint_authority",
                    signing_identity="checkpoint-key",
                    trust_store=trust,
                    clock_policy=policy,
                    observed_unix_ns=now,
                    expires_unix_ns=now + 5_000_000,
                    clock=clock,
                )
                self.assertTrue(
                    verify_current_audit_checkpoint(
                        store,
                        checkpoint,
                        trust,
                        policy,
                        owner_anchor=anchor,
                        clock=clock,
                    )
                )
                second = WorkEnvelope(
                    "second",
                    "a" * 40,
                    "b" * 40,
                    "e" * 64,
                    "f" * 64,
                    "developer-productivity",
                    ("src",),
                    tuple(sorted(DENIED_AUTHORITIES)),
                    1,
                    now + 9_000_000,
                )
                store.issue_work_envelope(second, now_ns=now + 1)
                verified = verify_audit_suffix(
                    store, checkpoint, trust, policy, clock=clock
                )
                self.assertEqual(verified.appended_events, 1)
                self.assertEqual(verified.current_sequence, checkpoint.sequence + 1)


if __name__ == "__main__":
    unittest.main()
