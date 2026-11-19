"""Adversarial contract checks for a recorded, *non-independent* CPU replay."""
import copy
import json
import unittest
from pathlib import Path

from verify_hpca_process_replay import verified_compare


class ReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path(__file__).resolve().parent
        cls.a = json.loads((base / "ACTUAL_OOD_FORWARD_RESULT.json").read_text())
        cls.b = json.loads((base / "HPCA_V2_PROCESS_REPLAY_RESULT.json").read_text())

    def test_full_nine_condition_reexecution(self):
        x = verified_compare(self.a, self.b)
        self.assertEqual((x["model_forwards"], x["bit_exact_score_fields"]), (216, 648))
        self.assertFalse(x["owner_attested"])
        self.assertEqual(x["authority"], "DENY_ALL")

    def test_forged_identity_rejected(self):
        b = copy.deepcopy(self.b)
        b["plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "plan pin"):
            verified_compare(self.a, b)

    def test_forged_probability_rejected(self):
        b = copy.deepcopy(self.b)
        b["runs"][2]["predictions"][0]["p_yes"] += .000001
        with self.assertRaisesRegex(ValueError, "distinct CPU score"):
            verified_compare(self.a, b)

    def test_forged_label_rejected(self):
        b = copy.deepcopy(self.b)
        b["runs"][3]["predictions"][2]["prediction"] = "tampered"
        with self.assertRaisesRegex(ValueError, "task or decision"):
            verified_compare(self.a, b)

    def test_dropped_row_rejected(self):
        b = copy.deepcopy(self.b)
        b["runs"][4]["predictions"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete task panel"):
            verified_compare(self.a, b)

    def test_forged_cost_rejected(self):
        b = copy.deepcopy(self.b)
        b["full_run_cost"]["process_cpu_seconds"] = -1
        with self.assertRaisesRegex(ValueError, "cost"):
            verified_compare(self.a, b)


if __name__ == "__main__":
    unittest.main()
