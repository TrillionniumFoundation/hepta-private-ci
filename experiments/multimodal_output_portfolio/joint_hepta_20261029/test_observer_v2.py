"""Source separation, evidence integrity, and real temporal feature regressions."""

import copy
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from .natural_eval import report_accuracy
from .natural_data import cpu_seconds
from .observer_v2 import fit_development, fit_ridge, predict_ridge, registered_sources
from .observer_v2_audit import audit_archive, audit_predictions, support_diagnostics, training_rows


def fixture_rows():
    return [{"source_id": f"s{i}", "fold": i % 5, "action_id": i % 2, "sound_id": i % 2,
             "window_start_seconds": 0., "target_start_seconds": 1., "target_end_seconds": 3.,
             "action_interval_seconds": [1., 3.], "sound_interval_seconds": [1.9, 2.1]}
            for i in range(10)]


class ObserverV2Tests(unittest.TestCase):
    def test_source_weighted_ridge_recovers_separable_classes_with_unseen_class_retained(self):
        rows = fixture_rows()
        features = np.asarray([[r["action_id"] * 2 - 1, i / 100] for i, r in enumerate(rows)])
        state = fit_ridge(features, rows, "action", [0, 1, 2], 1.)
        self.assertEqual(state["classes"].tolist(), [0, 1, 2])
        self.assertEqual(predict_ridge(state, features).tolist(), [r["action_id"] for r in rows])
        before = state["mean"].copy()
        predict_ridge(state, features + 1000)
        np.testing.assert_array_equal(before, state["mean"])

    def test_nonfinite_features_and_invalid_penalty_are_rejected(self):
        for features, penalty in ((np.full((10, 2), np.nan), 1.), (np.ones((10, 2)), 0.)):
            with self.assertRaises(ValueError):
                fit_ridge(features, fixture_rows(), "action", [0, 1], penalty)

    def test_archived_evidence_recomputes_without_media_access(self):
        archive = Path(__file__).parent / "evidence/observer"
        with tempfile.TemporaryDirectory() as directory:
            result = audit_archive(archive, Path(directory) / "audit.json")
        self.assertEqual((result["original_sources"], result["events"], result["fresh_media_read"]), (64, 301, False))
        self.assertFalse(result["original_development_passed"])
        self.assertAlmostEqual(result["modalities"]["action"]["predictions"]["source_uniform_accuracy"], .15755208333333334)

    def test_summary_tampering_and_fake_majority_are_rejected(self):
        rows = fixture_rows()
        ontology = {kind: {"0": "first", "1": "second"} for kind in ("action", "sound")}
        report = report_accuracy([r["action_id"] for r in rows], rows, "action")
        majority = report_accuracy([0] * len(rows), rows, "action")
        self.assertAlmostEqual(audit_predictions(report, majority, rows, "action", ontology)["source_uniform_accuracy"], 1.)
        altered = copy.deepcopy(report)
        altered["source_uniform_accuracy"] = .1
        with self.assertRaises(ValueError):
            audit_predictions(altered, majority, rows, "action", ontology)
        with self.assertRaises(ValueError):
            audit_predictions(report, report, rows, "action", ontology)

    def test_support_counts_do_not_silently_filter_absent_classes(self):
        rows = fixture_rows()
        ontology = {"sound": {"0": "first", "1": "second", "2": "absent"}}
        result = support_diagnostics(rows, ontology, "sound")
        self.assertEqual(result["absent_class_ids"], [2])
        self.assertAlmostEqual(result["target_label_covers_less_than_quarter_source_mass"], 1.)

    def test_source_fold_leakage_is_rejected(self):
        sources = [{"study_role": "observer_train", "source_id": f"s{i}", "fold": i,
                    "events": [{"action_id": 0}], "retained_event_count": 1} for i in range(5)]
        sources.append({**sources[0], "fold": 1})
        with self.assertRaises(ValueError):
            training_rows({"selected": sources})

    def test_unregistered_commit_cannot_start_real_development(self):
        with self.assertRaises(ValueError):
            registered_sources("HEAD")

    def test_complete_development_freezes_models_without_opening_confirmation(self):
        rows = [{**row, "source_sha256": str(i)} for i, row in enumerate(fixture_rows())]
        candidates = {kind: [{"name": "registered", "feature": kind, "ridge": 1.}]
                      for kind in ("action", "sound")}
        protocol = {"candidates": candidates, "adequacy": {"action_accuracy": .6, "sound_accuracy": .6},
                    "budget": {"cpu_seconds": 60, "wall_seconds": 60}}
        allocation = {"protocol": protocol, "allocation_sha256": "test-only", "ontology": {
            kind: {"0": "first", "1": "second"} for kind in ("action", "sound")}, "selected": [
            {"study_role": "observer_train", "source_id": row["source_id"], "fold": row["fold"],
             "events": [row], "retained_event_count": 1} for row in rows]}
        features = {kind: np.asarray([[row[kind + "_id"] * 2 - 1] for row in rows]) for kind in candidates}
        with tempfile.TemporaryDirectory() as directory:
            freeze = fit_development(allocation, rows, features, Path(directory), cpu_seconds(), time.monotonic())
            self.assertTrue(freeze["development_passed"])
            self.assertFalse(freeze["fresh_calibration_media_accessed"])
            self.assertFalse(freeze["semantic_qualification"])
            for kind in candidates:
                with np.load(Path(directory) / freeze["selected"][kind]["checkpoint_file"], allow_pickle=False) as data:
                    self.assertEqual(data["classes"].tolist(), [0, 1])

    def test_temporal_audio_preserves_original_global_block(self):
        import torch
        from scipy.signal import resample_poly
        from experiments.multimodal_output_portfolio.closure_20261028.semantic_backbones import PannMobileNet
        from .observer_v2_features import temporal_audio_features
        torch.manual_seed(43)
        torch.set_num_threads(2)
        model = PannMobileNet().eval()
        model.logmel_extractor.melW.fill_(.01)
        wave = np.random.default_rng(11).normal(0., .1, (1, 32000)).astype(np.float32)
        with torch.no_grad():
            original = model(torch.from_numpy(resample_poly(wave, 2, 1, axis=1).copy())).numpy()
        temporal = temporal_audio_features(model, wave)
        self.assertEqual(temporal.shape, (1, 6204))
        np.testing.assert_array_equal(temporal[:, :1551], original)
        self.assertTrue(np.isfinite(temporal).all())
        with self.assertRaises(ValueError):
            temporal_audio_features(model, wave[:, :100])


if __name__ == "__main__":
    unittest.main()
