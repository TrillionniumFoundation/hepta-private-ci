#!/usr/bin/env python3
"""Offline conformance tests: no downloaded weights and no synthetic perf claims."""
import copy
import unittest

from qualified_eval import (audit_dataset, brier_and_ece, evaluate, matrix,
                            ood_results, percentile, resource_results,
                            scale_summary, validate_predictions)
from hf_trial import FrozenStem


def cases():
    splits = ("train", "calibration", "test", "future", "ood")
    dates = ("2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01")
    return [
        {"case_id": f"id-{s}", "group_id": f"g-{s}", "scope_id": "scope-a",
         "task_id": "binary-decision", "split": s,
         "language": ("zh", "en", "cross", "zh", "en")[i],
         "state": f"separate state {s}", "question": "Is the evidence sufficient?",
         "options": ["no", "yes"], "label": i % 2,
         "event_time": f"{dates[i]}T09:00:00Z"}
        for i, s in enumerate(splits)
    ]


def predictions(data, model, probability=.75):
    output = []
    for case in data:
        if case["split"] == "train":
            continue
        confidence = probability
        p = ([confidence, 1 - confidence] if case["label"] == 0
             else [1 - confidence, confidence])
        output.append({"case_id": case["case_id"], "model_id": model,
                       "model_revision": "a" * 40,
                       "encoder_digest": "b" * 64, "head_digest": "c" * 64,
                       "scope_id": case["scope_id"], "runtime_generation": 1,
                       "status": "Succeeded", "probabilities": p,
                       "execution_path": "encoder_warm", "latency_ms": 3.0,
                       "rss_bytes": 4096, "backend_batch_size": 1})
    return output


class DatasetTests(unittest.TestCase):
    def test_audit(self):
        self.assertEqual(audit_dataset(cases())["cases"], 5)

    def test_duplicate_episode_group_leaks(self):
        rows = cases()
        rows[2]["group_id"] = rows[0]["group_id"]
        with self.assertRaisesRegex(ValueError, "group leakage"):
            audit_dataset(rows)

    def test_exact_content_leaks(self):
        rows = cases()
        rows[2]["state"] = rows[0]["state"]
        with self.assertRaisesRegex(ValueError, "identical example"):
            audit_dataset(rows)

    def test_future_overlap(self):
        rows = cases()
        rows[3]["event_time"] = "2026-01-01T09:00:00Z"
        with self.assertRaisesRegex(ValueError, "future"):
            audit_dataset(rows)

    def test_missing_split_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "all train"):
            audit_dataset(cases()[:-1])

    def test_cross_scope_predictions_rejected(self):
        rows = cases()
        ps = predictions(rows, "stem")
        ps[0]["scope_id"] = "another-scope"
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            validate_predictions(ps, rows)


class MetricsTests(unittest.TestCase):
    def test_proper_scoring_and_future(self):
        rows = cases()
        baseline = predictions(rows, "no-change", .5)
        candidate = predictions(rows, "stem", .9)
        receipt = evaluate(rows, baseline, candidate)
        self.assertFalse(receipt["production_promotion_permitted"])
        self.assertFalse(receipt["ndu_independent_signature_verified"])
        self.assertIsNone(receipt["descriptive_ndu_delta"])
        self.assertLess(receipt["metrics"]["future"]["zh"]["delta_brier"], 0)
        self.assertEqual(receipt["dataset"]["cases"], 5)

    def test_calibration_threshold_not_derived_from_ood(self):
        rows = cases()
        ps = predictions(rows, "stem", .9)
        ps[-1]["probabilities"] = [.55, .45]
        lookup = validate_predictions(ps, rows)
        results = ood_results(rows, lookup)
        self.assertAlmostEqual(results["threshold_from_calibration"], .9)
        self.assertEqual(results["ood_false_accept_rate"], 0)

    def test_bad_probabilities_rejected(self):
        rows = cases()
        ps = predictions(rows, "stem")
        ps[0]["probabilities"] = [.4, .5]
        with self.assertRaisesRegex(ValueError, "unnormalized"):
            validate_predictions(ps, rows)

    def test_identical_predictions_have_zero_delta(self):
        rows = cases()
        ps = predictions(rows, "same")
        result = evaluate(rows, ps, copy.deepcopy(ps))
        self.assertEqual(result["metrics"]["test"]["cross"]["delta_brier"], 0)

    def test_multiclass_brier_and_percentile(self):
        row = cases()[0]
        self.assertAlmostEqual(brier_and_ece([row], {row["case_id"]:
            {"probabilities": [1., 0.]}})["brier"], 0)
        self.assertEqual(percentile([1, 2, 3, 4, 5], .95), 4.8)


class ResourceTests(unittest.TestCase):
    def test_cold_cache_disjoint_paths(self):
        sample = [{"execution_path": path, "latency_ms": latency,
                   "rss_bytes": 99, "backend_batch_size": batch}
                  for path, latency, batch in
                  [("encoder_cold", 50, 1), ("encoder_warm", 10, 1),
                   ("cache_hit_head", 1, 0), ("backend_batch", 4, 8)]]
        result = resource_results(sample)
        self.assertEqual(result["cache_hit_head"]["p99_ms"], 1)
        self.assertEqual(result["encoder_cold"]["p99_ms"], 50)
        self.assertEqual(result["backend_batch"]["reported_backend_batch_sizes"], [8])

    def test_scale_rejects_unmeasured_origin(self):
        event = {"logical_cells": 64, "active_fraction": .25,
                 "input_repeat_fraction": .5, "task_similarity": "medium",
                 "measurement_origin": "synthetic",
                 "execution_path": "encoder_warm", "latency_ms": 4}
        with self.assertRaisesRegex(ValueError, "real_backend"):
            scale_summary([event])
        event["measurement_origin"] = "real_backend"
        result = scale_summary([event])
        self.assertFalse(result["production_promotion_permitted"])
        self.assertFalse(result["scales"][0]["backend_batch_verified"])

    def test_matrix_explicit_shadow_only(self):
        result = matrix([{"id": "test"}])
        self.assertEqual(len(result["arms"]), 4 * 6 * 4 * 3)
        self.assertEqual(len(result["scale_arms"]), 4 * 3 * 3 * 3)
        self.assertFalse(result["production_promotion_permitted"])

    def test_revision_pin_precedes_weight_import(self):
        with self.assertRaisesRegex(ValueError, "commit SHA"):
            FrozenStem("mmbert-small", "main", "cpu", 128)
        with self.assertRaisesRegex(ValueError, "explicit opt-in"):
            FrozenStem("jina-v2-base-zh", "a" * 40, "cpu", 128)


if __name__ == "__main__":
    unittest.main()
