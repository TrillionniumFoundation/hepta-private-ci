"""Behavioral checks for the observed masking, information, and cost boundaries."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from . import cascade_study, video_generator, video_study
from .common import read
from .document_study import score
from .fetch_video import isolated_indices


class NaturalBoundaryTests(unittest.TestCase):
    def test_missing_document_labels_are_masked_without_inventing_success(self):
        truth = {"company": "ACME", "date": "27/10/2026", "address": None, "total": "12.00"}
        answer = {**truth, "address": "An unobserved prediction"}
        observed = score(truth, answer)
        self.assertEqual((observed["observed_reference_fields"], observed["quality"],
            observed["field_exact"], observed["all_fields_exact"]), (3, 1.0, 1.0, False))
        answer["total"] = "13.00"
        self.assertEqual(score(truth, answer)["field_exact"], 2/3)
        self.assertEqual(observed["field_scores"]["address"],
            {"observed_reference": False, "exact": None, "similarity": None, "quality": None})

    def test_video_private_frames_never_appear_in_any_public_endpoint(self):
        for length in (36, 79, 360):
            targets = set(map(int, isolated_indices(2, length-3, 12)))
            endpoints = {i+offset for i in targets for offset in (-2, 2)}
            self.assertEqual((len(targets), targets & endpoints), (12, set()))
            self.assertTrue(all(0 <= i < length for i in endpoints))
        cut = int(.6*360)
        targets = set(map(int, isolated_indices(2, cut-3, 12)))
        targets.update(map(int, isolated_indices(cut+2, 357, 6)))
        self.assertEqual(targets & {i+d for i in targets for d in (-2, 2)}, set())

    def test_private_records_are_rejected_before_inference_or_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"forbidden"
            with self.assertRaisesRegex(ValueError, "public-only"):
                cascade_study.batch(None, None, [{"reference": "SECRET"}], "fixed_base", None, 1, output)
            with self.assertRaisesRegex(ValueError, "Private target"):
                video_study.batch([{"private_target": "SECRET"}], None, None, "fixed_blend", 0, output)
            self.assertFalse(output.exists())

    def test_actual_video_cache_and_budget_preserve_output_and_charge_work(self):
        cv2.setNumThreads(1)
        rng = np.random.default_rng(19)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for i in range(6):
                left = rng.integers(0, 256, (32, 40, 3), dtype=np.uint8)
                right = np.roll(left, i+1, axis=1)
                paths = [root/f"{i}-{name}.png" for name in ("left", "right")]
                for path, pixels in zip(paths, (left, right)):
                    Image.fromarray(pixels).save(path)
                sources.append({"id": str(i), "source": "fixture", "left": str(paths[0]), "right": str(paths[1])})
            row = sources[0]
            weights = np.asarray([1.0, -.3, .2, .1])
            cold = video_generator.render(row["left"], row["right"], weights, True, root/"cold")
            warm = video_generator.render(row["left"], row["right"], weights, True, root/"warm",
                video_generator.endpoints(row["left"], row["right"]))
            self.assertEqual(Path(cold["output_path"]).read_bytes(), Path(warm["output_path"]).read_bytes())
            predictor = {"mean": [0]*4, "scale": [1]*4, "weights": [0, 1, 0, 0, 0]}
            original_motion = video_generator.motion
            for arm in ("learned_budget", "matched_random_budget"):
                destination = root/arm
                def observed_motion(left, right):
                    self.assertTrue((destination/"DECISION.json").exists())
                    return original_motion(left, right)
                with patch.object(video_generator, "motion", side_effect=observed_motion) as motion:
                    delivered = video_study.batch(sources, weights, predictor, arm, .5, destination)
                runtime = read(destination/"BATCH_RUNTIME.json")
                self.assertEqual((motion.call_count, sum(r["expensive_calls"] for r in delivered)), (3, 3))
                self.assertAlmostEqual(sum(r["whole_cpu_seconds"] for r in delivered), runtime["whole_cpu_seconds"])
                self.assertAlmostEqual(sum(r["whole_wall_seconds"] for r in delivered), runtime["whole_wall_seconds"])
                self.assertGreater(runtime["controller_cpu_seconds"], 0)
                self.assertTrue(all(r["reused_public_endpoint_arrays"] for r in delivered))


if __name__ == "__main__":
    unittest.main()
