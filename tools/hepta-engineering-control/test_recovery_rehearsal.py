from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import EngineeringStore, WorkEnvelope
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
from control_engineering_v2.recovery_rehearsal import run_recovery_rehearsal


class RecoveryRehearsalTests(unittest.TestCase):
    def test_backup_restore_rehearsal_binds_snapshot_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "engineering.sqlite3"
            backup = root / "backup.sqlite3"
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
                        10_000_000_000,
                    ),
                    now_ns=1,
                )
            report = run_recovery_rehearsal(
                database,
                backup,
                source_commit="a" * 40,
                source_tree="b" * 40,
                predecessor_artifact_digest="e" * 64,
                now_ns=2,
            )
            self.assertTrue(report.passed)
            self.assertEqual(
                report.source_snapshot_digest,
                report.restored_snapshot_digest,
            )
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertFalse(report.deployment_accepted)
            with self.assertRaisesRegex(
                ValueError,
                "recovery_rehearsal_backup_exists",
            ):
                run_recovery_rehearsal(
                    database,
                    backup,
                    source_commit="a" * 40,
                    source_tree="b" * 40,
                    predecessor_artifact_digest="e" * 64,
                    now_ns=3,
                )


if __name__ == "__main__":
    unittest.main()
