"""Regression checks for the frozen actual-run opportunity audit (no training)."""
import json
import unittest

from cost_opportunity_audit import ARCHIVE, ARCHIVE_SHA256, audit_bytes


class CostOpportunityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = ARCHIVE.read_bytes()
        cls.audit = audit_bytes(cls.raw)

    def test_original_bytes_and_no_authority(self):
        r = self.audit
        self.assertEqual(r["archive_sha256"], ARCHIVE_SHA256)
        self.assertEqual(r["status"], "HOLD_NO_GO")
        self.assertEqual(r["paired_seeds"], 4)
        self.assertEqual(r["authority"], "READ_ONLY_ARCHIVED_OBSERVATION_NOT_OWNER")
        self.assertIn("independent B", r["missing"])
        self.assertIn("energy/network cost", r["missing"])

    def test_total_matching_does_not_mean_equal_group_opportunity(self):
        r = self.audit
        self.assertTrue(r["paired_input_token_equal"])
        self.assertTrue(r["paired_optimizer_parameter_element_equal"])
        expected = {
            11: ((124, 120), (180, 64)),
            17: ((140, 128), (206, 62)),
            23: ((125, 135), (188, 72)),
            29: ((135, 134), (207, 62)),
        }
        for pair in r["pairs"]:
            s = pair["seed"]
            self.assertEqual(tuple(x["tokens"] for x in pair["uniform"]["groups"]),
                             expected[s][0])
            self.assertEqual(tuple(x["tokens"] for x in pair["heterogeneous"]["groups"]),
                             expected[s][1])
            self.assertEqual([g["updates"] for g in pair["uniform"]["groups"]], [6, 6])
            self.assertEqual([g["updates"] for g in pair["heterogeneous"]["groups"]], [9, 3])
            self.assertEqual(pair["arm_order"], ["uniform", "heterogeneous"])
            self.assertEqual(sum(x["tokens"] for x in pair["uniform"]["groups"]),
                             pair["input_tokens"])
            self.assertEqual(sum(x["tokens"] for x in pair["heterogeneous"]["groups"]),
                             pair["input_tokens"])

    def test_order_and_resources_are_descriptive_not_counterbalanced(self):
        r = self.audit
        self.assertFalse(r["arm_execution_counterbalanced"])
        self.assertEqual(r["total_observed_physical_read_bytes"],
                         {"uniform": 1003520, "heterogeneous": 0})
        self.assertAlmostEqual(r["total_cpu_seconds"]["uniform"], 34.658762908, places=7)
        self.assertAlmostEqual(r["total_cpu_seconds"]["heterogeneous"], 35.631212609, places=7)
        self.assertAlmostEqual(r["total_arm_wall_seconds"]["uniform"],
                               9.914990192046389, places=7)
        self.assertAlmostEqual(r["total_arm_wall_seconds"]["heterogeneous"],
                               10.154832913074642, places=7)

    def test_no_mutated_self_report_passes_as_original(self):
        edited = json.loads(self.raw)
        edited["runs"][0]["schedule"][0] = 1
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            audit_bytes(json.dumps(edited).encode())
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            audit_bytes(self.raw + b"\\n")


if __name__ == "__main__":
    unittest.main()
