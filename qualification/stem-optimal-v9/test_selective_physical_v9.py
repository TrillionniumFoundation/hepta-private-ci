"""Source-only failure gates for the future real physical selective execution."""
import copy
import unittest
import selective_physical_v9 as v9


class SelectivePhysicalTests(unittest.TestCase):
    def test_invalid_plan_without_authority_is_rejected_before_loading_model(self):
        source = {"source_plan_sha256": v9.route.SOURCE_SHA,
                  "train": [{"case_id": f"fit:{i}", "label": i % 4} for i in range(64)],
                  "heldout": [{"case_id": f"heldout:{i}", "source_sha256": str(i)} for i in range(32)]}
        cheap = {"rows": [{"case_id": f"heldout:{i}", "source_sha256": str(i),
                 "scores": {"word_12_tfidf_centroid": [0.25] * 4,
                            "char_345_tfidf_centroid": [0.25] * 4}}
                          for i in range(32)]}
        ranked = v9.route.select_unlabelled({
            f"heldout:{i}": [0.25] * 4 for i in range(32)})
        plan = {"schema": v9.route.SCHEMA, "source_plan_sha256": v9.route.SOURCE_SHA,
                "selected_case_ids": ranked, "evidence": {
                    "actual_new_encoder_sequence_forwards": 0,
                    "measured_heldout_encoder_savings": False},
                "authority": "DENY_ALL", "production_authorized": False}
        materials = {"training": {"seed": 17, "steps": 100, "learning_rate": 0.006,
                                  "per_cell_parameters": 6914, "cells": 4}}
        selected = v9.validate_plan(source, cheap, plan, materials, "granite47")
        self.assertEqual(len(selected), 8)
        for change in (
            lambda p: p["selected_case_ids"].reverse(),
            lambda p: p["evidence"].__setitem__("measured_heldout_encoder_savings", True),
            lambda p: p.__setitem__("production_authorized", True),
            lambda p: p["evidence"].__setitem__("actual_new_encoder_sequence_forwards", 8),
            lambda p: p["selected_case_ids"].append("heldout:9"),
        ):
            altered = copy.deepcopy(plan)
            change(altered)
            with self.assertRaises(ValueError):
                v9.validate_plan(source, cheap, altered, materials, "granite47")

    def test_unknown_model_rejected_without_network(self):
        with self.assertRaisesRegex(ValueError, "wrong source/model"):
            v9.validate_plan({"source_plan_sha256": v9.route.SOURCE_SHA}, {}, {}, {}, "fake")

    def test_no_premature_physical_saving_claim(self):
        self.assertEqual(v9.SCHEMA, "hepta.stem.selective.physical.v9")
        self.assertEqual(v9.route.ROUTE_K, 8)


if __name__ == "__main__":
    unittest.main()
