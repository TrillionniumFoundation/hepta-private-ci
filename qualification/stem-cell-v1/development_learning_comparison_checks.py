"""No real-weight claims: deterministic fake backend for composition regressions."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from development_learning import run_shared_learning
from development_learning_comparison import (ARMS, compare_reports, run_comparison,
                                             score_saved_predictions, write_new_json)
from development_pretrained_study import authored_fixture
from shared_encoder_batch import FrozenFeature, SharedStemEngine


class Backend:
    simulated = True
    encoder_digest, preprocessor_digest, runtime_digest = "1" * 64, "2" * 64, "3" * 64

    def __init__(self):
        self.calls, self.rows = 0, 0

    def encode_many(self, texts, representation):
        self.calls += 1
        self.rows += len(texts)
        return [FrozenFeature.from_values([len(text) / 100, sum(map(ord, text)) % 13 / 10,
                                            0.25, 0.75], 4, representation) for text in texts]


def fixture():
    rows, train, gold = authored_fixture("1" * 64, "3" * 64)
    rows = tuple(replace(r, request=replace(r.request, preprocessor_digest="2" * 64)) for r in rows)
    return rows, train, gold


class ComparisonChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.rows, cls.train, cls.gold = fixture()
        cls.backend = Backend()
        cls.result = run_comparison(cls.backend, cls.rows, cls.train, classes=2, steps=3)

    def test_all_arms_execute_independently(self):
        reports = self.result["reports"]
        self.assertEqual(set(reports), {a[0] for a in ARMS})
        self.assertEqual(self.backend.calls, sum(r["encoder_calls"] for r in reports.values()))
        self.assertEqual(self.backend.rows, sum(r["encoded_input_rows"] for r in reports.values()))
        self.assertEqual(reports["singleton"]["encoder_calls"], len(self.rows))
        self.assertEqual(reports["singleton"]["encoded_input_rows"], len(self.rows))
        self.assertEqual(reports["cache"]["encoded_input_rows"], 40)
        self.assertEqual(reports["grouped"]["encoded_input_rows"], 40)
        self.assertTrue(all(r["started_with_empty_feature_cache"] for r in reports.values()))

    def test_matched_work_and_tolerance(self):
        self.assertTrue(self.result["execution_equivalent"])
        self.assertEqual(self.result["distinct_heldout_inputs"], 16)
        self.assertEqual(self.result["distinct_heldout_source_groups"], 1)
        self.assertEqual(self.result["logical_heldout_predictions"], 128)
        self.assertIsNone(self.result["selected_arm"])
        self.assertTrue(self.result["simulated_encoder"])
        self.assertFalse(self.result["production_authorized"])
        self.assertFalse(self.result["scored_heldout_labels"])
        for report in self.result["reports"].values():
            self.assertGreaterEqual(report["whole_call"]["wall_ns"], report["total"]["wall_ns"])

    def test_order_is_seed_rotation(self):
        names = [a[0] for a in ARMS]
        self.assertEqual(self.result["order"], names[2:] + names[:2])

    def test_linear_control_remains_available(self):
        result = run_comparison(Backend(), self.rows, self.train, classes=2, steps=1, head_kind="linear")
        self.assertTrue(result["execution_equivalent"])

    def test_invalid_late_row_before_any_dispatch(self):
        backend = Backend()
        rows = self.rows[:-1] + (replace(self.rows[-1], request=replace(self.rows[-1].request,
                                                                      runtime_digest="9" * 64)),)
        with self.assertRaises(ValueError):
            run_comparison(backend, rows, self.train, classes=2, steps=1)
        self.assertEqual(backend.calls, 0)

    def test_heldout_label_contamination_before_dispatch(self):
        backend = Backend()
        with self.assertRaises(ValueError):
            run_comparison(backend, self.rows, self.train | self.gold, classes=2, steps=1)
        self.assertEqual(backend.calls, 0)

    def test_invalid_options_before_dispatch(self):
        for options in ({"seed": True}, {"steps": 0}, {"head_kind": "other"}, {"head_hidden_size": 0}):
            backend = Backend()
            with self.subTest(options=options), self.assertRaises(ValueError):
                run_comparison(backend, self.rows, self.train, classes=2, **options)
            self.assertEqual(backend.calls, 0)

    def test_encoder_envelope_rejects_bool_zero_and_large(self):
        for batch in (True, 0, 33):
            backend = Backend()
            with self.subTest(batch=batch), self.assertRaises(ValueError):
                run_shared_learning(SharedStemEngine(backend), self.rows, self.train,
                                    classes=2, steps=1, encoder_batch_size=batch)
            self.assertEqual(backend.calls, 0)

    def test_missing_or_duplicate_prediction_rejected(self):
        for duplicate in (False, True):
            reports = deepcopy(self.result["reports"])
            predictions = reports["grouped"]["predictions"]
            if duplicate:
                predictions[-1] = deepcopy(predictions[0])
            else:
                predictions.pop()
            with self.assertRaises(ValueError):
                compare_reports(reports, self.rows, classes=2)

    def test_wrong_prediction_identity_rejected(self):
        reports = deepcopy(self.result["reports"])
        reports["grouped"]["predictions"][0]["cell_id"] = "wrong"
        with self.assertRaises(ValueError):
            compare_reports(reports, self.rows, classes=2)

    def test_changed_initialization_or_work_rejected(self):
        for field in ("initial_sha256", "examples_processed", "steps", "trainable_parameters"):
            reports = deepcopy(self.result["reports"])
            item = reports["grouped"]["cells"]["cell.0"]
            if field == "initial_sha256":
                item[field] = "f" * 64
            else:
                item["training"][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                compare_reports(reports, self.rows, classes=2)

    def test_nonfinite_or_wrong_width_rejected(self):
        for values in ([float("nan"), 0.0], [0.0], [True, 0.0]):
            reports = deepcopy(self.result["reports"])
            reports["grouped"]["predictions"][0]["trained_logits"] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                compare_reports(reports, self.rows, classes=2)

    def test_numeric_failure_is_retained_not_selected_away(self):
        reports = deepcopy(self.result["reports"])
        reports["grouped"]["predictions"][0]["trained_logits"] = [1e6, -1e6]
        result = compare_reports(reports, self.rows, classes=2)
        self.assertFalse(result["execution_equivalent"])
        self.assertIsNone(result["selected_arm"])
        self.assertGreater(result["comparisons"]["grouped"]["fields"]["trained_logits"]["maximum_absolute_error"], 100)

    def test_comparison_does_not_call_scorer(self):
        with patch("development_learning_comparison.score_saved_predictions", side_effect=AssertionError("gold")):
            result = run_comparison(Backend(), self.rows, self.train, classes=2, steps=1)
        self.assertFalse(result["scored_heldout_labels"])

    def test_separate_scoring_exact_label_map_and_counts(self):
        predictions = self.result["reports"]["grouped"]["predictions"]
        scores = score_saved_predictions(predictions, self.rows, self.gold, classes=2)
        self.assertEqual(scores["trained_logits"]["total"], 128)
        with self.assertRaises(ValueError):
            score_saved_predictions(predictions, self.rows, self.gold | self.train, classes=2)
        bad = dict(self.gold)
        bad[next(iter(bad))] = True
        with self.assertRaises(ValueError):
            score_saved_predictions(predictions, self.rows, bad, classes=2)

    def test_create_only_evidence_and_json_roundtrip(self):
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "predictions.json"
            predictions = self.result["reports"]["grouped"]["predictions"]
            digest = write_new_json(path, predictions)
            self.assertEqual(digest, self.result["prediction_sha256"]["grouped"])
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(json.loads(path.read_bytes()), predictions)
            with self.assertRaises(FileExistsError):
                write_new_json(path, predictions)


if __name__ == "__main__":
    unittest.main()
