from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import EngineeringStore
from control_engineering_v2.capacity_policy import (
    DatabaseCapacityPolicy,
    enforce_database_capacity,
    evaluate_database_capacity,
)
from control_engineering_v2.control_plane import EngineeringError


class DatabaseCapacityPolicyTests(unittest.TestCase):
    def test_default_policy_measures_empty_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                decision = evaluate_database_capacity(store)
                self.assertFalse(decision.hard_limit_exceeded)
                self.assertFalse(decision.runtime_authority)
                self.assertGreater(decision.database_bytes, 0)

    def test_hard_limit_blocks_admission_and_low_trigger_recommends_migration(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                tiny = DatabaseCapacityPolicy(
                    maximum_database_bytes=1,
                    maximum_wal_bytes=1,
                    maximum_audit_events=1,
                    maximum_active_leases=1,
                    maximum_active_claims=1,
                    maximum_active_reservations=1,
                    migration_trigger_q16=1,
                )
                decision = evaluate_database_capacity(store, tiny)
                self.assertTrue(decision.hard_limit_exceeded)
                self.assertTrue(decision.migration_recommended)
                with self.assertRaisesRegex(EngineeringError, "database_capacity_exceeded"):
                    enforce_database_capacity(store, tiny)


if __name__ == "__main__":
    unittest.main()
