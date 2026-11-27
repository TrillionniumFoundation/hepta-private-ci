from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import EngineeringStore, WorkEnvelope
from control_engineering_v2.capacity_policy import (
    ControlCapacityPolicy,
    evaluate_control_capacity,
    require_new_work_capacity,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


class CapacityPolicyTests(unittest.TestCase):
    def envelope(self):
        return WorkEnvelope(
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
        )

    def test_migration_signal_and_hard_new_work_gate_are_distinct(self):
        policy = ControlCapacityPolicy(
            migration_database_bytes=1,
            hard_database_bytes=1 << 30,
            migration_wal_bytes=1,
            hard_wal_bytes=1 << 30,
            migration_audit_events=1,
            hard_audit_events=2,
            migration_active_claims=1,
            hard_active_claims=2,
            migration_active_leases=1,
            hard_active_leases=2,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope(), now_ns=1)
                decision = evaluate_control_capacity(store, policy, now_ns=1)
                self.assertTrue(decision.migration_recommended)
                self.assertTrue(decision.write_admitted)
                store._append_audit("capacity-test", {"bounded": True}, 2)
                store.connection.commit()
                blocked = evaluate_control_capacity(store, policy, now_ns=2)
                self.assertFalse(blocked.write_admitted)
                with self.assertRaisesRegex(ValueError, "control_capacity_hard_limit"):
                    require_new_work_capacity(store, policy, now_ns=2)

    def test_invalid_threshold_order_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_capacity_policy_audit_events"):
            ControlCapacityPolicy(1, 2, 1, 2, 3, 2, 1, 2, 1, 2)


if __name__ == "__main__":
    unittest.main()
