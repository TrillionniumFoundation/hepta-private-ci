"""Independent-family accounting tests (not official future windows)."""
import unittest

from amcn_core import Refused
from amcn_typed_budget import train_typed_budget, type_inventory_digest
from amcn_typed_family_audit import family_paired_audit
from test_amcn_typed_budget import trial


class FamilyPairedAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix, cls.types, cls.train, cls.labels = trial()
        cls.pin = type_inventory_digest(cls.matrix, cls.types)
        cls.output = train_typed_budget(
            cls.matrix, cls.train, cls.types,
            expected_type_digest=cls.pin, steps=3, batch=2, seed=71)

    def audit(self, predictions=None, labels=None):
        return family_paired_audit(
            self.matrix, self.types,
            self.output["predictions"] if predictions is None else predictions,
            self.labels if labels is None else labels,
            pinned_type_sha256=self.pin,
            pinned_predictions_sha256=self.output["receipt"]["metrics"]["prediction_sha256"])

    def test_real_trained_heads_count_families_not_rows(self):
        result = self.audit()
        m = result["metrics"]
        self.assertEqual(m["observed_family_group_count"], 8)
        self.assertEqual(m["family_panel_results"]["future_a"]["family_count"], 4)
        self.assertEqual(m["family_panel_results"]["future_b"]["family_count"], 4)
        self.assertIsNone(m["independently_verified_family_count"])
        self.assertEqual(m["independently_observed_future_calendar_windows"], 0)
        self.assertFalse(result["production_accepted"])

    def test_negative_accuracy_deltas_are_not_suppressed(self):
        result = self.audit()
        m = result["metrics"]
        for v in m["family_panel_results"].values():
            self.assertEqual(v["family_wins"] + v["family_losses"] +
                             v["family_ties"], v["family_count"])
            self.assertLessEqual(v["worst_family_delta"], v["best_family_delta"])

    def test_missing_original_prediction_refused(self):
        with self.assertRaises(Refused):
            self.audit(predictions=self.output["predictions"][:-1])

    def test_missing_label_refused(self):
        labels = dict(self.labels)
        labels.pop(next(iter(labels)))
        with self.assertRaises(Refused):
            self.audit(labels=labels)

    def test_changed_original_source_case_refused(self):
        from copy import deepcopy
        output = deepcopy(self.output["predictions"])
        output[0]["family"] = "different"
        with self.assertRaises(Refused):
            self.audit(predictions=output)


if __name__ == "__main__":
    unittest.main()
