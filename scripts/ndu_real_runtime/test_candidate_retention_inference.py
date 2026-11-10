import copy
import unittest

from .candidate_retention_inference import source_inference


def pair(source, index, on, off, role="development"):
    return [{"original_operation_id": f"{source}-{index}-{mode}",
             "pair_id": f"{source}-{index}", "case_id": f"{source}-{index}",
             "source_group_id": source, "split": role, "mode": mode,
             "unconditional_success": value}
            for mode, value in (("bounded", on), ("current_only", off))]


class SourceInferenceTests(unittest.TestCase):
    def test_sources_receive_equal_weight_despite_unequal_case_counts(self):
        rows = pair("small", 0, False, True, "retention_validation")
        rows += [r for i in range(9) for r in pair("large", i, True, False)]
        result = source_inference(rows)
        self.assertEqual(result["source_equal_weight_difference"], 0.0)
        self.assertEqual(result["planned_pairs"], 10)
        self.assertFalse(result["numerical_benefit_threshold_met"])

    def test_unknowns_keep_labels_and_use_memory_adverse_bounds(self):
        rows = pair("one", 0, None, False) + pair("two", 0, True, None)
        original = copy.deepcopy(rows)
        result = source_inference(rows)
        self.assertEqual(rows, original)
        self.assertEqual(result["missing_label_bounds"], [0.0, 1.0])
        self.assertIsNone(result["source_equal_weight_difference"])
        self.assertEqual(result["unknown_pairs"], 2)
        self.assertEqual(result["worst_case_unknown_one_sided_95pct_lower"], 0.0)

    def test_numeric_threshold_does_not_grant_scientific_adoption(self):
        rows = [r for i in range(20) for r in pair(
            f"source-{i}", 0, True, False,
            "development" if i < 16 else "retention_validation")]
        result = source_inference(rows)
        self.assertTrue(result["numerical_benefit_threshold_met"])
        self.assertEqual(result["worst_case_unknown_one_sided_95pct_lower"], 1.0)
        self.assertEqual(result["scientific_acceptance"], "HOLD")
        self.assertFalse(result["production_adoption"])

    def test_incomplete_or_reassigned_pairs_are_rejected(self):
        rows = pair("one", 0, True, False)
        with self.assertRaises(ValueError):
            source_inference(rows[:1])
        rows[1]["source_group_id"] = "other"
        with self.assertRaises(ValueError):
            source_inference(rows)


if __name__ == "__main__":
    unittest.main()
