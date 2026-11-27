from pathlib import Path
import tempfile
import unittest

from control_engineering_v2.stress_profile import run_engineering_stress


class StressProfileTests(unittest.TestCase):
    def test_concurrent_growth_crash_and_reopen_profile_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = run_engineering_stress(
                Path(temporary) / "engineering.sqlite3",
                source_commit="a" * 40,
                source_tree="b" * 40,
                workers=2,
                records=12,
                reopen_cycles=3,
            )
            self.assertEqual(report.committed_records, 12)
            self.assertEqual(report.crash_exit_code, 77)
            self.assertTrue(report.crash_transaction_rolled_back)
            self.assertTrue(report.audit_chain_verified)
            self.assertFalse(report.release_authority)


if __name__ == "__main__":
    unittest.main()
