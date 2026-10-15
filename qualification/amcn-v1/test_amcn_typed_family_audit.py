"""Actual CPU Head training and adversarial source-lineage alias checks."""
import unittest
from dataclasses import replace
from copy import deepcopy

from amcn_core import Refused
from amcn_learning import FeatureMatrix
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

    def audit(self, *, matrix=None, predictions=None, labels=None, types=None, pin=None):
        matrix = self.matrix if matrix is None else matrix
        types = self.types if types is None else types
        pin = self.pin if pin is None else pin
        output = self.output["predictions"] if predictions is None else predictions
        return family_paired_audit(
            matrix, types, output, self.labels if labels is None else labels,
            pinned_type_sha256=pin,
            pinned_predictions_sha256=(self.output["receipt"]["metrics"]["prediction_sha256"]
                                       if predictions is None else __import__('amcn_core').digest(output)))

    def altered(self, change):
        rows = list(self.matrix.rows)
        future = [i for i, row in enumerate(rows) if row.split == "future_a"]
        change(rows, future)
        matrix = FeatureMatrix(rows, self.matrix.x.clone(), encoder_sha256=self.matrix.encoder_sha256,
                               scope=self.matrix.scope, generation=self.matrix.generation,
                               backend_profile=self.matrix.backend_profile,
                               encoder_execution_receipt=self.matrix.encoder_execution_receipt)
        typed = {r.row_id: self.types[r.row_id] for r in matrix.rows}
        pin = type_inventory_digest(matrix, typed)
        output = train_typed_budget(matrix, self.train, typed,
                                    expected_type_digest=pin, steps=3, batch=2, seed=71)
        return self.audit(matrix=matrix, types=typed, pin=pin, predictions=output["predictions"])

    def test_original_heads_count_components_not_training_rows(self):
        m = self.audit()["metrics"]
        self.assertEqual(m["observed_source_component_count"], 8)
        self.assertEqual(m["family_panel_results"]["future_a"]["source_component_count"], 4)
        self.assertEqual(m["family_panel_results"]["future_b"]["source_component_count"], 4)
        self.assertEqual(m["family_panel_results"]["future_b"]["distinct_family_labels"], 4)
        self.assertIsNone(m["independently_verified_family_count"])
        self.assertEqual(m["independently_observed_future_calendar_windows"], 0)
        self.assertFalse(self.audit()["production_accepted"])

    def test_renaming_same_source_root_does_not_multiply_independent_families(self):
        def change(rows, ids):
            rows[ids[1]] = replace(rows[ids[1]], source_root=rows[ids[0]].source_root)
        m = self.altered(change)["metrics"]
        self.assertEqual(m["observed_source_component_count"], 7)
        self.assertEqual(m["family_panel_results"]["future_a"]["distinct_family_labels"], 4)
        self.assertEqual(m["family_panel_results"]["future_a"]["source_component_count"], 3)
        self.assertEqual(m["family_panel_results"]["future_a"]["merged_family_aliases"], 1)

    def test_transitive_root_and_family_aliases_collapse(self):
        def change(rows, ids):
            rows[ids[1]] = replace(rows[ids[1]], source_root=rows[ids[0]].source_root)
            rows[ids[2]] = replace(rows[ids[2]], family=rows[ids[1]].family)
        m = self.altered(change)["metrics"]
        self.assertEqual(m["family_panel_results"]["future_a"]["source_component_count"], 2)
        self.assertEqual(m["observed_source_component_count"], 6)

    def test_negative_accuracy_deltas_are_not_suppressed(self):
        m = self.audit()["metrics"]
        for v in m["family_panel_results"].values():
            self.assertEqual(v["family_wins"] + v["family_losses"] +
                             v["family_ties"], v["source_component_count"])
            self.assertLessEqual(v["worst_family_delta"], v["best_family_delta"])
        self.assertIsNone(m["lower_confidence_bound_for_promotion"])

    def test_missing_original_prediction_refused(self):
        with self.assertRaises(Refused):
            self.audit(predictions=self.output["predictions"][:-1])

    def test_missing_label_refused(self):
        labels = dict(self.labels)
        labels.pop(next(iter(labels)))
        with self.assertRaises(Refused):
            self.audit(labels=labels)

    def test_changed_original_source_case_refused(self):
        output = deepcopy(self.output["predictions"])
        output[0]["family"] = "different"
        with self.assertRaises(Refused):
            self.audit(predictions=output)

    def test_large_transitive_alias_chain_cannot_overflow_python_stack(self):
        from types import SimpleNamespace
        from amcn_typed_family_audit import _components
        rows = []
        for i in range(1300):
            rows.append(SimpleNamespace(row_id=f"a-{i}", source_root=f"r-{i}",
                                        family=f"f-{1301-i:04d}"))
            rows.append(SimpleNamespace(row_id=f"b-{i}", source_root=f"r-{i}",
                                        family=f"f-{1300-i:04d}"))
        components = _components(rows)
        self.assertEqual(len(components), 1)
        self.assertEqual(len(components[0]), 2600)

    def test_contradictory_cross_panel_root_cannot_fake_independence(self):
        rows = list(self.matrix.rows)
        i = next(i for i, r in enumerate(rows) if r.split == "future_a")
        j = next(j for j, r in enumerate(rows) if r.split == "future_b")
        rows[j] = replace(rows[j], source_root=rows[i].source_root)
        with self.assertRaises(Refused):
            FeatureMatrix(rows, self.matrix.x, encoder_sha256=self.matrix.encoder_sha256,
                          scope=self.matrix.scope, generation=self.matrix.generation,
                          backend_profile=self.matrix.backend_profile)


if __name__ == "__main__":
    unittest.main()
