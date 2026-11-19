"""Tests for the immutable read-only resource observation."""

import unittest

from .audit_snapshot import audit


class SnapshotAuditTest(unittest.TestCase):
    def test_terminal_zero_work_receipt(self):
        report = audit()
        self.assertEqual(report["status"], "PASS_OBSERVATION_HOLD_ADMISSION")
        self.assertTrue(all(value == 0 for value in report["counts"].values()))

    def test_complete_ancestor_chain_and_oom_history(self):
        observation = audit()["observation"]
        self.assertEqual(observation["ancestor_levels"], 6)
        self.assertEqual(observation["app_slice_oom_events"], 315)
        self.assertEqual(observation["app_slice_oom_kills"], 15)
        self.assertEqual(observation["finite_memory_max_levels"], 0)

    def test_snapshot_does_not_admit_n256(self):
        report = audit()
        self.assertFalse(report["allocation_frozen"])
        self.assertFalse(report["calendar_frozen"])
        self.assertFalse(report["resource_admitted"])
        self.assertFalse(report["all_closed"])


if __name__ == "__main__":
    unittest.main()
