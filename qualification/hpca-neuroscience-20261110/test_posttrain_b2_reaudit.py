"""Archive-bound real-output arithmetic and mutation negatives."""
import copy
import unittest
from pathlib import Path
from posttrain_b2_reaudit import load_original, audit

ROOT = Path(__file__).resolve().parent

class OriginalB2AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.result = load_original(ROOT)
    def test_archive_exact_540_forwards_and_no_yes_predictions(self):
        data = audit(self.manifest, self.result)
        self.assertEqual(data["nine_model_runs"], 9)
        self.assertEqual(data["observed_forwards"], 540)
        self.assertEqual(data["prediction_counts"], {"no": 540})
        self.assertEqual(data["per_run_accuracy"], [0.5]*9)
        self.assertEqual(data["authority"], "DENY_ALL")
    def rejects(self, change):
        manifest = copy.deepcopy(self.manifest)
        result = copy.deepcopy(self.result)
        change(manifest, result)
        with self.assertRaises(ValueError):
            audit(manifest, result)
    def test_forged_yes_prediction_rejected(self):
        self.rejects(lambda m, r: r["runs"][1]["scores"]["rows"][0].update(prediction="yes"))
    def test_changed_feedback_truth_rejected(self):
        self.rejects(lambda m, r: r["runs"][1]["scores"]["rows"][0].update(truth="no"))
    def test_row_omission_rejected(self):
        self.rejects(lambda m, r: r["runs"][1]["scores"]["rows"].pop())
    def test_missing_seed_rejected(self):
        self.rejects(lambda m, r: r["runs"].pop())
    def test_summary_tamper_rejected(self):
        self.rejects(lambda m, r: r["mean_paired_deltas"].update(mean_brier=0.03))
    def test_relabelled_manifest_rejected(self):
        self.rejects(lambda m, r: m["tasks"][0].update(truth="no"))
    def test_authority_escalation_rejected(self):
        self.rejects(lambda m, r: r.update(authority="ADOPT"))
