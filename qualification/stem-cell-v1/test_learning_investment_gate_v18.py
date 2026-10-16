import copy
import unittest
from learning_investment_gate_v18 import SCHEMA, ARMS, PHASES, Invalid, audit

D = "0" * 64

def packet():
    observations = []
    for case, cohort, old in (("c1", "future", False), ("c2", "future", False), ("c3", "train", True)):
        for arm in ARMS:
            observations.append({"arm": arm, "case_id": case, "root_id": "root-" + case, "cohort": cohort, "old_task": old, "correct": (case == "c1" and arm != "no_change") or (case == "c3" and arm != "split_router")})
    return {"schema": SCHEMA, "source_sha256": D, "model_sha256": D, "registration_sha256": D, "observations": observations, "costs": {a: {p: 0.0 for p in PHASES} for a in ARMS}, "authority": {"production_authorized": False, "source_attested": False, "final_use_authorized": False}}

class Tests(unittest.TestCase):
    def test_non_authorizing(self):
        result = audit(packet())
        self.assertEqual(result["decision"], "DENY_ALL_UNATTESTED_RESEARCH")
        self.assertFalse(result["cell_split_authorized"])
        self.assertEqual(result["root_counts"]["future"], 2)
        self.assertEqual(result["comparisons"]["split_router"]["old_task_lost_correct"], 1)
    def test_missing_arm(self):
        p = packet(); p["observations"].pop(); self.assertRaises(Invalid, audit, p)
    def test_duplicate(self):
        p = packet(); p["observations"].append(copy.deepcopy(p["observations"][0])); self.assertRaises(Invalid, audit, p)
    def test_attribution(self):
        p = packet(); p["observations"][1]["root_id"] = "forged"; self.assertRaises(Invalid, audit, p)
    def test_attestation(self):
        p = packet(); p["authority"]["source_attested"] = True; self.assertRaises(Invalid, audit, p)
    def test_digest(self):
        p = packet(); p["source_sha256"] = "wrong"; self.assertRaises(Invalid, audit, p)
    def test_missing_cost(self):
        p = packet(); p["costs"]["linear"].pop("recovery"); self.assertRaises(Invalid, audit, p)
    def test_nan(self):
        p = packet(); p["costs"]["linear"]["encoder"] = float("nan"); self.assertRaises(Invalid, audit, p)
    def test_boolean_cost(self):
        p = packet(); p["costs"]["linear"]["encoder"] = True; self.assertRaises(Invalid, audit, p)
    def test_drift(self):
        p = packet(); p["observations"][1]["cohort"] = "calibration"; self.assertRaises(Invalid, audit, p)
    def test_no_future(self):
        p = packet()
        for r in p["observations"]:
            if r["cohort"] == "future": r["cohort"] = "calibration"
        self.assertEqual(audit(p)["future_case_count"], 0)
        self.assertFalse(audit(p)["model_selection_authorized"])

if __name__ == "__main__":
    unittest.main()
