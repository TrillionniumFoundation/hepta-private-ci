import unittest

from real_cell_features import predictor_rows


class PredictorBoundaryTests(unittest.TestCase):
    def test_targets_never_enter_feature_request(self):
        row = {"source_id": "repo-1", "source_version": {"commit": "abc", "revision": "def"},
               "text": "Actual bug description", "labels": {"task": 1}, "patch": "secret gold"}
        first = predictor_rows([row])
        row.update(labels={"task": 0}, patch="different gold", split="holdout")
        self.assertEqual(first, predictor_rows([row]))
        row["source_version"]["commit"] = "xyz"
        self.assertNotEqual(first, predictor_rows([row]))

    def test_duplicate_or_over_budget_sources_fail_before_model(self):
        row = {"source_id": "repo-1", "source_version": "abc", "text": "bug"}
        with self.assertRaises(ValueError):
            predictor_rows([row, row])
        with self.assertRaises(ValueError):
            predictor_rows([{**row, "text": "界" * 6000}])


if __name__ == "__main__":
    unittest.main()
