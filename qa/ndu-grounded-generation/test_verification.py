import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from verification import Verifier, visible_features


def generated(confidence, boxes=None):
    return {"tokens": [2, 0, 10, 2], "termination": "eos",
            "boxes": boxes if boxes is not None else [[0.1, 0.1, 0.4, 0.5]],
            "controls": [{"base_logprob": confidence, "controlled_logprob": confidence}]}


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"generated": generated(-0.1 - index),
                      "quality": 1 - index / 19, "severe": float(index >= 10), "split": "train"}
                     for index in range(20)]
        self.verifier = Verifier.fit(self.rows)

    def test_learns_from_train_labels_and_ignores_reference_extras(self):
        good, bad = generated(-0.1), generated(-19.1)
        a, b = self.verifier.predict(good), self.verifier.predict(bad)
        self.assertGreater(a["quality"], b["quality"])
        self.assertLess(a["severe_probability"], b["severe_probability"])
        reversed_labels = Verifier.fit([
            {**row, "quality": 1 - row["quality"], "severe": 1 - row["severe"]}
            for row in self.rows
        ])
        self.assertLess(reversed_labels.predict(good)["quality"], reversed_labels.predict(bad)["quality"])
        self.assertGreater(reversed_labels.predict(good)["severe_probability"], reversed_labels.predict(bad)["severe_probability"])
        contaminated = {**good, "reference_boxes": [[0, 0, 1, 1]], "quality": -999,
                        "source_id": "secret-label", "image_path": "/gold/path", "severe": 1}
        c = self.verifier.predict(contaminated)
        for key in ("quality", "severe_probability", "features"):
            self.assertEqual(a[key], c[key])
        with self.assertRaises(ValueError):
            Verifier.fit([{**self.rows[0], "split": "test"}])

    def test_calibration_changes_probability_only_and_preserves_ordering(self):
        probes = [generated(-0.2 - index) for index in range(20)]
        before = [self.verifier.predict(value) for value in probes]
        weights = self.verifier.severe_weights.copy()
        rows = [{"generated": value, "severe": float(index >= 5), "split": "calibration"}
                for index, value in enumerate(probes)]
        self.verifier.calibrate(rows)
        after = [self.verifier.predict(value) for value in probes]
        self.assertEqual([r["quality"] for r in before], [r["quality"] for r in after])
        np.testing.assert_array_equal(weights, self.verifier.severe_weights)
        self.assertEqual(np.argsort([r["severe_probability"] for r in before]).tolist(),
                         np.argsort([r["severe_probability"] for r in after]).tolist())
        self.assertNotEqual(before[0]["severe_probability"], after[0]["severe_probability"])

    def test_duplicate_boxes_do_not_create_extra_quality(self):
        single = generated(-1)
        duplicate = copy.deepcopy(single)
        duplicate["boxes"] *= 4
        a, b = self.verifier.predict(single), self.verifier.predict(duplicate)
        self.assertEqual(a["features"]["unique_box_count"], b["features"]["unique_box_count"])
        self.assertLessEqual(b["quality"], a["quality"])
        malformed = generated(-1, [[0.5, 0.2, 0.1, 0.7], [float("nan"), 0, 1, 1]])
        self.assertTrue(np.isfinite(visible_features(malformed)).all())

    def test_saved_model_replays_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verifier.json"
            self.verifier.save(path)
            loaded = Verifier.load(path)
            a, b = self.verifier.predict(generated(-4)), loaded.predict(generated(-4))
            a.pop("wall_seconds")
            b.pop("wall_seconds")
            self.assertEqual(a, b)
            payload = json.loads(path.read_text())
            payload["quality_weights"][0] += 1
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                Verifier.load(path)


if __name__ == "__main__":
    unittest.main()
