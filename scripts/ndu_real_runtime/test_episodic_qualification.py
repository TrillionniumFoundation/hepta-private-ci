import json
from pathlib import Path
import tempfile
import unittest

from .run_episodic_qualification import run


class FreshProcessQualificationTests(unittest.TestCase):
    def test_exited_writers_new_readers_and_actual_deliveries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            report = run(root)
            self.assertEqual((report["status"], report["passed_scenarios"]), ("PASS", 18))
            self.assertEqual(len(report["producer_receipts"]), 3)
            self.assertTrue(all(r["writer_exited_before_successor"]
                                for r in report["producer_receipts"]))
            self.assertEqual(report["scientific_acceptance"], "HOLD")
            self.assertFalse(report["unseen_task_benefit_evaluated"])
            rows = {r["scenario"]: r for r in report["rows"]}
            self.assertFalse(rows["persistence_off"]["receipt"]["store_read"])
            self.assertEqual(rows["delivery_off"]["receipt"]["delivered_ids"], [])
            self.assertTrue(rows["delivery_off"]["receipt"]["retrieved_ids"])
            for name in ("stale_snapshot", "revoked_fact", "revoked_snapshot",
                         "dependent_fact_invalidated", "other_namespace"):
                delivery = json.loads((root / name / "delivery.json").read_bytes())
                self.assertEqual(delivery["texts"], [])
            # Consumer requests expose no expected result or previous chat.
            for name in rows:
                request = json.loads((root / name / "request.json").read_bytes())
                self.assertNotIn("expected_texts", request)
                self.assertNotIn("history", request)


if __name__ == "__main__":
    unittest.main()
