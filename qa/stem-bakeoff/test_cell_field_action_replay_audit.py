"""Independent replay evidence checks and failure census preservation."""

from pathlib import Path
import shutil
import tempfile
import unittest

from cell_field_action_replay_audit import arrays, audit_replays
import test_cell_field_action_replay as fixtures


class ActionReplayAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ActionReplayTests.setUpClass()
        cls.fixture = fixtures.ActionReplayTests(
            "test_whole_candidate_recomputation_and_midpoint_complete_state_replay")

    def plan(self):
        return {"evaluation_horizon": 8, "h": 0.02, "action_bound": 1.0,
                "replay": {"method_id": "loss2_h8_direct_soft", "anchor_offset": 16,
                           "heads": ["gated"], "seeds": [7], "whole_steps": 8, "midpoint_steps": 4}}

    def save_execution(self, root, records):
        fixtures.write_json(root / "execution_result_before_replay.json", {
            "records": records, "record_count": len(records),
            "validation_labels_opened": False, "final_labels_opened": False})

    def test_complete_evidence_passes_but_changed_array_is_independently_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, record, initial = self.fixture.fixture(root)
            plan = self.plan()
            fixtures.write_json(root / "inputs/protocol.json", plan)
            record.update(seed=7, head="gated", anchor_offset=16, initial_index=0)
            (root / "source").mkdir()
            for name in self.fixture.hashes:
                shutil.copyfile(self.fixture.source / name, root / "source" / name)
            self.save_execution(root, [record])
            replays = fixtures.verify_action_replays(root, record, initial, plan,
                self.fixture.hashes, self.fixture.source)
            runs = {"records": [record], "initial_order": [initial], "replays": replays,
                    "sourcecode_hashes": self.fixture.hashes}
            audited = audit_replays(root, runs, plan)
            self.assertTrue(audited["all_registered_replays_passed"])
            self.assertEqual(audited["status_census"], {"completed": 2})
            self.assertEqual(audited["registered_segments"], 2)
            changed = arrays(root, replays[0]["arrays_path"])
            changed["states"][2, 0] += 1e-4
            fixtures.save_arrays(root / replays[0]["arrays_path"], changed)
            self.assertTrue(all(replays[0]["matches"].values()))
            with self.assertRaisesRegex(ValueError, "independent replay suffix/identity differs: states"):
                audit_replays(root, runs, plan)

    def test_segment_free_failure_expands_without_changing_scientific_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for status, scientific in (("failed", "completed"), ("unavailable", "solver_failure")):
                with self.subTest(status=status):
                    record = {"run_id": "fixture", "seed": 7, "head": "gated", "anchor_offset": 16,
                              "method_id": "loss2_h8_direct_soft", "status": scientific}
                    self.save_execution(root, [record])
                    runs = {"records": [record], "replays": [{"run_id": "fixture", "status": status,
                                                            "reason": "retained failure"}]}
                    audited = audit_replays(root, runs, self.plan())
                    self.assertEqual(audited["status_census"], {status: 2})
                    self.assertFalse(audited["all_registered_replays_passed"])
                    self.assertTrue(audited["scientific_records_preserved"])
                    self.assertEqual([row["segment"] for row in audited["failures"]], ["whole", "midpoint"])
                    self.assertEqual([row["scientific_execution_status"] for row in audited["failures"]],
                                     [scientific, scientific])
                    self.assertEqual(runs["records"], [record])


if __name__ == "__main__":
    unittest.main()
