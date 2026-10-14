import hashlib
import json
import unittest

from experiments.shared_stem_cell.media_counterfactual import InvalidModalityPair, evaluate

S = "a" * 64


def media():
    records = []
    for label,kind in (("img", "image"), ("aud", "audio"), ("vid", "video")):
        entry = {
            "pair_id": label, "source_group": label, "split": "holdout",
            "modality": kind, "contrast_kind": "media_substitution",
            "prompt_sha256": S, "original_source_sha256": "1" * 64,
            "changed_source_sha256": "2" * 64,
            "original_probabilities": [0.9, 0.1],
            "changed_probabilities": [0.1, 0.9],
            "original_timestamps_us": [0, 10] if kind == "video" else None,
            "changed_timestamps_us": [0, 10] if kind == "video" else None,
            "original_frames": None, "changed_frames": None,
            "pair_wall_ns": 1000, "pair_formula_flops": 200
        }
        records.append(entry)
    return {"schema": "hepta.stem.paired-modality-predictions.v1",
            "scope": "public-media-fixture", "model_sha256": S,
            "preprocessor_sha256": S, "source_sha256": S,
            "classes": 2, "pairs": records}


def truths(p):
    return {"schema": "hepta.stem.paired-modality-labels.v1",
            "prediction_sha256": hashlib.sha256(json.dumps(
                p, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "observer_receipt_sha256": S,
            "labels": [{"pair_id": row["pair_id"], "original_label": 0, "changed_label": 1}
                       for row in p["pairs"]]}


class MediaCounterfactualTests(unittest.TestCase):
    def test_paired_image_audio_video_truth_flips(self):
        p = media()
        result = evaluate(p, truths(p))
        self.assertEqual(len(result["groups"]), 3)
        for row in result["groups"].values():
            self.assertEqual(row["both_correct"], 1)
            self.assertEqual(row["distinct_source_groups"], 1)
        self.assertFalse(result["cross_modal_generalization_proven"])
        self.assertFalse(result["actual_independent_observer_verified"])

    def test_unchanged_prediction_exposes_ignored_modality(self):
        p = media()
        p["pairs"][0]["changed_probabilities"] = [0.9, 0.1]
        result = evaluate(p, truths(p))
        self.assertEqual(result["groups"]["holdout/image/media_substitution"]["unresponsive_to_truth_flip"], 1)
        self.assertEqual(result["groups"]["holdout/image/media_substitution"]["both_correct"], 0)

    def test_predictions_cannot_change_after_truth_binding(self):
        p = media()
        review = truths(p)
        p["pairs"][0]["changed_probabilities"] = [0.5, 0.5]
        with self.assertRaisesRegex(InvalidModalityPair, "bind exact sealed"):
            evaluate(p, review)

    def test_missing_and_repeated_labels_fail(self):
        p,review = media(), truths(media())
        review["labels"].pop()
        with self.assertRaises(InvalidModalityPair):
            evaluate(p, review)
        review = truths(p)
        review["labels"][1] = dict(review["labels"][0])
        with self.assertRaises(InvalidModalityPair):
            evaluate(p, review)

    def test_truth_does_not_change_is_not_a_counterfactual(self):
        p = media()
        label = truths(p)
        label["labels"][0]["changed_label"] = 0
        with self.assertRaisesRegex(InvalidModalityPair, "change the correct answer"):
            evaluate(p, label)

    def test_zeroed_or_same_media_fails(self):
        p = media()
        p["pairs"][0]["changed_source_sha256"] = p["pairs"][0]["original_source_sha256"]
        with self.assertRaises(InvalidModalityPair):
            evaluate(p, truths(p))

    def test_uncounted_flops_stays_null(self):
        p = media()
        p["pairs"][0]["pair_formula_flops"] = None
        output = evaluate(p, truths(p))
        self.assertIsNone(output["groups"]["holdout/image/media_substitution"]["pair_formula_flops"])

    def test_video_reordering_must_preserve_actual_frame_inventory(self):
        p = media()
        v = p["pairs"][2]
        v["contrast_kind"] = "temporal_reordering"
        v["original_frames"] = ["4" * 64, "5" * 64]
        v["changed_frames"] = ["5" * 64, "4" * 64]
        self.assertEqual(evaluate(p, truths(p))["groups"]
                         ["holdout/video/temporal_reordering"]["both_correct"], 1)
        v["changed_frames"] = ["9" * 64, "4" * 64]
        with self.assertRaises(InvalidModalityPair):
            evaluate(p, truths(p))

    def test_future_and_reversed_video_frames_reject(self):
        p = media()
        p["pairs"][2]["changed_timestamps_us"] = [20, 10]
        with self.assertRaises(InvalidModalityPair):
            evaluate(p, truths(p))

    def test_source_family_cannot_cross_holdout_retention(self):
        p = media()
        p["pairs"][1]["source_group"] = "img"
        p["pairs"][1]["split"] = "retention"
        with self.assertRaises(InvalidModalityPair):
            evaluate(p, truths(p))

    def test_missing_media_or_unregistered_temporal_form_rejects(self):
        p = media()
        p["pairs"][0]["contrast_kind"] = "temporal_reordering"
        with self.assertRaises(InvalidModalityPair):
            evaluate(p, truths(p))


if __name__ == "__main__":
    unittest.main()
