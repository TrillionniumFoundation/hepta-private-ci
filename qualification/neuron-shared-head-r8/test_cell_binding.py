"""Cell-binding fixtures with tiny untrained arrays, no model training/inference."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import r8_experiments as lib


class CellBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.head = lib.Head("linear", 2, 2, 2048, 7)
        self.train = self.features("train", 1, labelled=True)
        self.valid = self.features("valid", 3, labelled=True)
        self.record = {
            "train_file_sha256": "1" * 64,
            "valid_file_sha256": "2" * 64,
            "train_groups": ["train"],
            "valid_groups": ["valid"],
            "valid_time_max": 4,
            "steps": 0,
        }
        self.model = self.root / "untrained-fixture.npz"

    def features(self, group, start, *, labelled=False, cells=("cell:a", "cell:a")):
        data = {
            "x": np.zeros((2, 2), dtype=np.float32),
            "id": np.array([group + "-0", group + "-1"]),
            "group": np.array([group, group]),
            "time": np.array([start, start + 1], dtype=np.int64),
            "cell": np.array(cells),
            "encoder_digest": np.array("fixture-encoder"),
            "scope_digest": np.array("fixture-scope"),
        }
        if labelled:
            data["y"] = np.array([0, 1], dtype=np.int64)
        return data

    def save(self):
        lib.save_head(self.head, self.train, self.valid, self.record, self.model)

    def predict(self, cells=("cell:a", "cell:a")):
        feature_path = self.root / "future.npz"
        np.savez_compressed(feature_path, **self.features("future", 5, cells=cells))
        output = self.root / "prediction.json"
        lib.cmd_predict(argparse.Namespace(model=str(self.model),
                         input=str(feature_path), output=str(output)))
        return output

    def test_cell_identity_survives_model_serialization(self):
        self.save()
        _, metadata = lib.load_head(self.model)
        self.assertEqual(metadata["cell_id"], "cell:a")
        self.assertTrue(metadata["shadow_only"])

    def test_same_cell_prediction_retains_identity_and_no_promotion(self):
        self.save()
        with patch.object(lib.Head, "probs",
                          return_value=np.array([[0.5, 0.5], [0.5, 0.5]])) as infer:
            output = self.predict()
        self.assertEqual(infer.call_count, 1)
        report = json.loads(output.read_text())
        self.assertEqual(report["cell_id"], "cell:a")
        self.assertFalse(report["production_admitted"])

    def test_cross_cell_prediction_rejected_before_inference(self):
        self.save()
        with patch.object(lib.Head, "probs",
                          side_effect=AssertionError("must not infer")) as infer:
            with self.assertRaisesRegex(ValueError, "Cell identity"):
                self.predict(("cell:b", "cell:b"))
            infer.assert_not_called()
        self.assertFalse((self.root / "prediction.json").exists())

    def test_mixed_cell_prediction_rejected_before_inference(self):
        self.save()
        with patch.object(lib.Head, "probs",
                          side_effect=AssertionError("must not infer")) as infer:
            with self.assertRaisesRegex(ValueError, "single-Cell"):
                self.predict(("cell:a", "cell:b"))
            infer.assert_not_called()

    def test_save_rejects_different_train_validation_cell(self):
        self.valid["cell"] = np.array(["cell:b", "cell:b"])
        with self.assertRaisesRegex(ValueError, "across cells"):
            self.save()
        self.assertFalse(self.model.exists())

    def test_save_rejects_mixed_or_invalid_cell_identifiers(self):
        for cells in (["cell:a", "cell:b"], ["", ""], [" ", " "], [1, 1]):
            with self.subTest(cells=cells):
                self.train["cell"] = np.array(cells)
                with self.assertRaisesRegex(ValueError, "single-Cell"):
                    self.save()
                self.assertFalse(self.model.exists())

    def test_unbound_or_invalid_legacy_metadata_is_not_inferred(self):
        self.save()
        with np.load(self.model, allow_pickle=False) as archive:
            payload = {key: archive[key].copy() for key in archive.files}
        original = json.loads(str(payload["meta"].item()))
        for value in (None, "", " ", 1, True):
            with self.subTest(cell_id=value):
                metadata = dict(original)
                if value is None:
                    del metadata["cell_id"]
                else:
                    metadata["cell_id"] = value
                altered = {**payload, "meta": np.array(json.dumps(metadata))}
                np.savez_compressed(self.model, **altered)
                with self.assertRaisesRegex(ValueError, "Cell identity"):
                    lib.load_head(self.model)


if __name__ == "__main__":
    unittest.main()
