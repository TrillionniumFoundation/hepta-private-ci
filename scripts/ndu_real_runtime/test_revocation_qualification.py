import json
from pathlib import Path
import tempfile
import unittest

from .run_revocation_qualification import run


class RevocationQualificationTests(unittest.TestCase):
    def test_active_post_update_snapshot_and_chain_are_revoked_in_new_readers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaign"
            report = run(root)
            self.assertEqual(
                (report["status"], report["passed_scenarios"]), ("PASS", 14)
            )
            self.assertTrue(all(report["invariants"].values()))
            self.assertEqual(
                (report["fresh_read_processes"], report["exited_writer_processes"]),
                (14, 3),
            )
            rows = {row["scenario"]: row for row in report["rows"]}
            before = rows["snapshot_current_fact"]["receipt"]["view_receipt"]
            after = rows["revoked_snapshot_fact"]["receipt"]["view_receipt"]
            self.assertEqual(
                (before["snapshot_rejections"], after["snapshot_rejections"]), (0, 3)
            )
            self.assertEqual(before["snapshot_sha256"], after["snapshot_sha256"])
            # The same snapshot still physically contains the revoked texts.
            snapshot = json.loads((root / "after-update.json").read_bytes())
            self.assertEqual(len(snapshot["body"]["records"]), 4)
            self.assertEqual(report["scientific_acceptance"], "HOLD")
            self.assertFalse(report["full_owner_cold_recovery"])
            self.assertEqual(report["model_calls"], 0)
            self.assertFalse(rows["snapshot_off"]["receipt"]["store_read"])
            self.assertTrue(rows["snapshot_delivery_off"]["receipt"]["retrieved_ids"])
            self.assertFalse(rows["snapshot_delivery_off"]["receipt"]["delivered_ids"])
            with self.assertRaises(FileExistsError):
                run(root)


if __name__ == "__main__":
    unittest.main()
