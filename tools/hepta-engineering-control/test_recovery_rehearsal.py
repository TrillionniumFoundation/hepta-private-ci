from pathlib import Path
import tempfile
import unittest

from control_engineering_v2.clock import ClockPolicy, FixedClock
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
from control_engineering_v2.evidence import HmacTrustStore
from control_engineering_v2.recovery_rehearsal import (
    rehearse_backup_restore,
    verify_recovery_rehearsal,
)


class RecoveryRehearsalTests(unittest.TestCase):
    def test_online_backup_reopens_with_identical_owner_snapshot(self):
        now = 1_000_000
        trust = HmacTrustStore({("recovery_operator", "recovery-key"): b"key"})
        policy = ClockPolicy(10, 10_000, 10_000_000)
        clock = FixedClock(now)
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            backup = Path(temporary) / "backup.sqlite3"
            with EngineeringStore(database) as store:
                store.issue_work_envelope(
                    WorkEnvelope(
                        "env",
                        "a" * 40,
                        "b" * 40,
                        "c" * 64,
                        "d" * 64,
                        "developer-productivity",
                        ("src",),
                        tuple(sorted(DENIED_AUTHORITIES)),
                        1,
                        now + 9_000_000,
                    ),
                    now_ns=now,
                )
            receipt = rehearse_backup_restore(
                database,
                backup,
                source_commit="a" * 40,
                source_tree="b" * 40,
                issuer="recovery_operator",
                signing_identity="recovery-key",
                trust_store=trust,
                clock_policy=policy,
                observed_unix_ns=now,
                expires_unix_ns=now + 5_000_000,
                clock=clock,
            )
            self.assertTrue(receipt.rollback_rehearsed)
            self.assertTrue(
                verify_recovery_rehearsal(
                    receipt,
                    trust,
                    policy,
                    expected_source_commit="a" * 40,
                    expected_source_tree="b" * 40,
                    clock=clock,
                )
            )


if __name__ == "__main__":
    unittest.main()
