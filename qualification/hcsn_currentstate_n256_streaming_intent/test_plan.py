import copy
import json
import unittest
from pathlib import Path

from .plan import EXPECTED, compile_plan, read_bound, validate_records


ROOT = Path(__file__).resolve().parents[2]
ROSTER = (
    ROOT
    / "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001"
)
AUDIT = (
    ROOT
    / "qualification/hcsn_currentstate_n256_engineering/evidence"
    / "source-8b0d340/attempt001/AUDIT.json"
)


class StreamingPlanTest(unittest.TestCase):
    def records(self):
        summary = json.loads(read_bound(ROSTER / "SUMMARY.json", EXPECTED["summary"]))
        capsules = json.loads(read_bound(ROSTER / "CAPSULES.json", EXPECTED["capsules"]))
        packets = [
            json.loads(line)
            for line in read_bound(
                ROSTER / "PACKET_ROSTER.jsonl", EXPECTED["packets"]
            ).splitlines()
        ]
        audit = json.loads(read_bound(AUDIT, EXPECTED["engineering_audit"]))
        return summary, capsules, packets, audit

    def test_exact_static_plan(self):
        result = compile_plan(ROSTER, AUDIT)
        self.assertEqual(result["status"], "PASS_STREAM_STORAGE_HOLD_DYNAMIC")
        self.assertTrue(result["preservation"]["storage_caps_satisfied"])
        self.assertEqual(result["conceptual_fp64_coordinates"], 18_225_028)
        self.assertEqual(result["execution_counts"], {
            "dynamic_runs": 0,
            "matrix_exponentials": 0,
            "oracle_numeric_calls": 0,
            "serializer_numeric_calls": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
            "training_runs": 0,
        })
        self.assertFalse(result["largegrid_qualification"])
        self.assertFalse(result["all_closed"])

    def test_rejects_packet_reorder(self):
        summary, capsules, packets, audit = self.records()
        broken = copy.deepcopy(packets)
        broken[0]["packet_order"] = 1
        with self.assertRaisesRegex(ValueError, "packet order"):
            validate_records(summary, capsules, broken, audit)

    def test_rejects_coordinate_denominator_change(self):
        summary, capsules, packets, audit = self.records()
        broken = copy.deepcopy(packets)
        broken[0]["coordinate_count"] += 1
        with self.assertRaisesRegex(ValueError, "packet coordinate count"):
            validate_records(summary, capsules, broken, audit)

    def test_rejects_old_red_reclassification(self):
        summary, capsules, packets, audit = self.records()
        broken = copy.deepcopy(audit)
        broken["status"] = "PASS"
        with self.assertRaisesRegex(ValueError, "#6295 RED dependency"):
            validate_records(summary, capsules, packets, broken)


if __name__ == "__main__":
    unittest.main()
