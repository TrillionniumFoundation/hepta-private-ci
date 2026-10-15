"""Adversarial, entirely synthetic mechanism tests; no real model claim."""
import copy
import hashlib
import unittest
from e2_semantic_outcomes import ARMS, evaluate

D = hashlib.sha256(b"future-source").hexdigest()

def fixture():
    targets = {"schema": "hepta.e2.semantic-targets.v1", "rows": [
        {"case_id": "a", "group_id": "g1", "condition": "vision_required",
         "label": "yes", "source_sha256": D, "partition": "future1"},
        {"case_id": "b", "group_id": "g2", "condition": "visual_evidence_swapped",
         "label": "no", "source_sha256": D, "partition": "future2"},
    ]}
    predictions = {"schema": "hepta.e2.semantic-predictions.v1", "rows": [
        {"case_id": t["case_id"], "arm": a, "answer": t["label"],
         "source_sha256": D}
        for t in targets["rows"] for a in ARMS
    ]}
    return predictions, targets

class SemanticOutcomeTests(unittest.TestCase):
    def test_valid_outcomes_do_not_authorize(self):
        p, t = fixture()
        out = evaluate(p, t)
        self.assertEqual(out["cases"], 2)
        self.assertEqual(out["authority"], "DENY_ALL")
        self.assertFalse(out["stem_selected"])
        self.assertFalse(out["production_accepted"])
        self.assertEqual(len(out["scores"]), 10)
        self.assertEqual(len(out["paired_vs_text_only"]), 8)

    def test_missing_arm_rejected(self):
        p, t = fixture()
        p["rows"].pop()
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_duplicate_arm_rejected(self):
        p, t = fixture()
        p["rows"].append(copy.deepcopy(p["rows"][0]))
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_predicted_target_leak_rejected(self):
        p, t = fixture()
        p["rows"][0]["label"] = "yes"
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_wrong_source_rejected(self):
        p, t = fixture()
        p["rows"][0]["source_sha256"] = hashlib.sha256(b"other").hexdigest()
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_scoring_train_rejected(self):
        p, t = fixture()
        t["rows"][0]["partition"] = "train"
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_future_group_overlap_rejected(self):
        p, t = fixture()
        t["rows"][1]["group_id"] = "g1"
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_case_identity_collision_rejected(self):
        p, t = fixture()
        t["rows"][1]["case_id"] = "a"
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_correctness_discordance(self):
        p, t = fixture()
        for row in p["rows"]:
            if row["case_id"] == "a" and row["arm"] == "text_only":
                row["answer"] = "no"
            if row["case_id"] == "b" and row["arm"] == "aligned_bridge":
                row["answer"] = "yes"
        out = evaluate(p, t)
        m = {(x["partition"], x["arm"]): x for x in out["paired_vs_text_only"]}
        self.assertEqual(m[("future1", "aligned_bridge")]["rescued"], 1)
        self.assertEqual(m[("future2", "aligned_bridge")]["harmed"], 1)

    def test_invalid_condition_rejected(self):
        p, t = fixture()
        t["rows"][0]["condition"] = "image_is_optional"
        with self.assertRaises(ValueError):
            evaluate(p, t)

    def test_no_predictions_labels_access_needed(self):
        p, t = fixture()
        for row in p["rows"]:
            self.assertNotIn("label", row)
        self.assertEqual(evaluate(p, t)["cases"], 2)

if __name__ == "__main__":
    unittest.main()
