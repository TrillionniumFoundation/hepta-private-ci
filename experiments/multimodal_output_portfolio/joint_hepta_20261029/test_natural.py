"""Behavioral checks for natural-source isolation and the evaluation boundary."""

from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

import numpy as np

from .natural_data import (digest, eligible_fresh_events, load_allocation,
                           require_role_access, select_training, write_new)
from .natural_eval import majority_label, normalize_fit, report_accuracy, source_weights


class NaturalContracts(unittest.TestCase):
    def allocation(self):
        return {"allocation_sha256": "allocation", "protocol_sha256": "protocol",
                "protocol": {"candidate_order": ["ridge100"], "adequacy": {"action_accuracy": .6, "sound_accuracy": .6}},
                "ontology": {"action": list(range(5)), "sound": list(range(5))},
                "selected": [{"source_id": str(i), "fold": i, "study_role": "observer_train", "retained_event_count": 1,
                              "events": [{"action_id": i, "sound_id": i}]} for i in range(5)],
                "excluded_source_ids": ["old"]}

    def freeze(self):
        rows = [{"source_id": str(i), "action_id": i, "sound_id": i} for i in range(5)]
        values = {kind: {"candidate": "ridge100", "out_of_fold": report_accuracy(list(range(5)), rows, kind),
                         "majority_control": report_accuracy([1, 0, 0, 0, 0], rows, kind),
                         "folds": [{"fold": i} for i in range(5)]} for kind in ("action", "sound")}
        return {"allocation_sha256": "allocation", "protocol_sha256": "protocol", "development_passed": True,
                "complete_folds": 5, "models_refitted_and_frozen": True,
                "selected": deepcopy(values), "candidates": {kind: [value] for kind, value in values.items()}}

    def test_inadequate_or_incomplete_observer_cannot_open_fresh_media(self):
        allocation = self.allocation()
        valid = self.freeze()
        require_role_access(allocation, "fresh_observer_calibration", valid)
        for key, replacement in (("allocation_sha256", "different"), ("development_passed", False),
                                 ("complete_folds", 4), ("models_refitted_and_frozen", False)):
            bad = {**valid, key: replacement}
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_role_access(allocation, "fresh_observer_calibration", bad)

    def test_success_flags_cannot_overwrite_failed_or_relabelled_predictions(self):
        for kind in ("action", "sound"):
            for field, value in (("predictions", [0] * 5), ("source_uniform_accuracy", float("nan")),
                                 ("labels", [0] * 5)):
                bad = self.freeze()
                bad["candidates"][kind][0]["out_of_fold"][field] = value
                bad["selected"][kind] = deepcopy(bad["candidates"][kind][0])
                with self.subTest(kind=kind, field=field), self.assertRaises(ValueError):
                    require_role_access(self.allocation(), "fresh_observer_calibration", bad)

    def test_original_calibration_and_qualification_always_refused(self):
        for role in ("qualification", "policy_calibration", "observer_calibration", "unknown"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                require_role_access(self.allocation(), role, {"development_passed": True})

    def test_selection_preserves_generator_observer_sources_and_event_counts(self):
        source = {"selected": [{"source_id": f"g{i}", "role": "generator_train", "retained_event_count": 1}
                               for i in range(6)] + [{"source_id": f"o{i}", "role": "observer_train", "retained_event_count": i + 1}
                               for i in range(6)] + [{"source_id": "reserved", "role": "qualification"}]}
        protocol = {"observer_training_sources": 5, "generator_mechanism_sources": 2, "source_folds": 5}
        first = select_training(source, protocol)
        second = select_training({"selected": list(reversed(source["selected"]))}, protocol)
        self.assertEqual(first, second)
        self.assertEqual({r["fold"] for r in first if r["study_role"] == "observer_train"}, set(range(5)))
        self.assertTrue(all(r["role"] == r["study_role"] for r in first))
        self.assertNotIn("reserved", {r["source_id"] for r in first})

    def test_source_weights_do_not_turn_extra_events_into_independent_sources(self):
        rows = [{"source_id": "a", "action_id": 0}] * 9 + [{"source_id": "b", "action_id": 1}]
        score = report_accuracy([0] * 10, rows, "action")
        self.assertAlmostEqual(score["source_uniform_accuracy"], .5)
        self.assertAlmostEqual(score["event_accuracy"], .9)
        self.assertAlmostEqual(source_weights(rows).sum(), 1.)

    def test_train_normalization_is_not_fitted_to_validation(self):
        training = np.asarray([[1., 3.], [3., 7.]])
        mean, scale, normalized = normalize_fit(training, np.asarray([.5, .5]))
        np.testing.assert_array_equal(mean, [2., 5.])
        np.testing.assert_array_equal(scale, [1., 2.])
        np.testing.assert_array_equal(normalized, [[-1., -1.], [1., 1.]])
        validation = np.asarray([[1e6, -1e6]])
        np.testing.assert_array_equal(np.clip((validation - mean) / scale, -8, 8), [[8., -8.]])
        np.testing.assert_array_equal(mean, [2., 5.])

    def test_source_uniform_majority_differs_from_event_majority(self):
        rows = ([{"source_id": "a", "action_id": 0}] * 20
                + [{"source_id": "b", "action_id": 1}, {"source_id": "c", "action_id": 1}])
        self.assertEqual(majority_label(rows, "action", [0, 1, 2]), 1)

    def test_target_alignment_preserves_boundary_event_and_pads_only_context(self):
        action = {"metadata": {"video_id": "v", "num_frames": 80, "frame_rate": 8},
                  "action_localisation": [{"id": 1, "label_id": 0, "label": "a", "timestamps": [0, 300000]}]}
        sound = {"metadata": {"audio_samples": 160000, "audio_sample_rate": 16000},
                 "sound_localisation": [{"id": 2, "label_id": 0, "label": "s", "timestamps": [0, 300000], "is_visible": True}]}
        rows = eligible_fresh_events(action, sound)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_start_seconds"], 0.)
        self.assertEqual(rows[0]["window_start_seconds"], -1.)
        self.assertAlmostEqual(rows[0]["target_label_overlap_seconds"], .3)
        sound["sound_localisation"][0]["is_visible"] = False
        self.assertEqual(eligible_fresh_events(action, sound), [])

    def test_unusable_tail_annotation_does_not_abort_other_eligible_events(self):
        action = {"metadata": {"video_id": "v", "num_frames": 80, "frame_rate": 8},
                  "action_localisation": [{"id": 1, "label_id": 0, "label": "a", "timestamps": [0, 10000000]}]}
        sound = {"metadata": {"audio_samples": 160000, "audio_sample_rate": 16000},
                 "sound_localisation": [{"id": 2, "label_id": 0, "label": "s", "timestamps": [5000000, 6000000], "is_visible": True},
                                        {"id": 3, "label_id": 0, "label": "s", "timestamps": [9850000, 10000000], "is_visible": True}]}
        rejected = []
        rows = eligible_fresh_events(action, sound, rejected)
        self.assertEqual([row["sound_annotation_id"] for row in rows], [2])
        self.assertEqual([row["sound_annotation_id"] for row in rejected], [3])
        self.assertAlmostEqual(rows[0]["target_label_overlap_seconds"], 1.)
        self.assertLess(rejected[0]["target_label_overlap_seconds"], .15)

    def test_role_relabel_and_old_source_freshness_rejected_after_digest_refresh(self):
        value = {"protocol": {}, "protocol_sha256": digest({}), "excluded_source_ids": ["old"],
                 "selected": [{"source_id": "old", "role": "observer_train", "study_role": "generator_train"}]}
        with tempfile.TemporaryDirectory() as directory:
            for i, changed in enumerate((value, {**value, "selected": [{"source_id": "old", "role": "fresh_observer_calibration", "study_role": "fresh_observer_calibration"}]})):
                row = deepcopy(changed); row["allocation_sha256"] = digest(row)
                path = Path(directory) / f"{i}.json"
                write_new(path, row)
                with self.assertRaises(ValueError):
                    load_allocation(path)

    def test_duplicate_source_cannot_inflate_frozen_allocation(self):
        value = {"protocol": {}, "protocol_sha256": digest({}), "excluded_source_ids": [],
                 "selected": [{"source_id": "same", "role": "observer_train", "study_role": "observer_train"}] * 2}
        value["allocation_sha256"] = digest(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "allocation.json"; write_new(path, value)
            with self.assertRaises(ValueError):
                load_allocation(path)


if __name__ == "__main__":
    unittest.main()
