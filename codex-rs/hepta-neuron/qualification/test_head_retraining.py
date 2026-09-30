"""Check immutable materialization admission without loading any model backbone."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import decision_cell_bakeoff as bakeoff
import head_retraining as training


class FrozenHeadInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = bakeoff.build_dataset()
        _, digest = bakeoff.write_dataset(self.rows, self.root / "dataset")
        self.ids = [row.example_id for row in self.rows]
        self.state = np.zeros((len(self.rows), 8), dtype=np.float32)
        self.targets = np.zeros((len(self.rows), 4, 8), dtype=np.float32)
        self.receipt = {"dataset_sha256": digest}
        self.save()

    def save(self, ids=None):
        self.receipt["embedding_artifact"] = bakeoff.save_embeddings(
            self.root, "test", self.ids if ids is None else ids, self.state, self.targets)

    def load(self):
        return training.load_frozen_features(self.receipt, self.root)

    def test_exact_labels_and_features_are_read(self):
        rows, state, targets = self.load()
        self.assertEqual(rows, self.rows)
        np.testing.assert_array_equal(state, self.state)
        np.testing.assert_array_equal(targets, self.targets)

    def test_changed_feature_bytes_reject(self):
        path = Path(self.receipt["embedding_artifact"]["path"])
        with path.open("ab") as stream:
            stream.write(b"substituted")
        with self.assertRaisesRegex(ValueError, "digest"):
            self.load()

    def test_rehashed_row_permutation_rejects(self):
        self.save(list(reversed(self.ids)))
        with self.assertRaisesRegex(ValueError, "identity/order"):
            self.load()

    def test_rehashed_dataset_label_replacement_rejects(self):
        path = self.root / "dataset" / f"dataset-{self.receipt['dataset_sha256']}.json"
        dataset = json.loads(path.read_text())
        dataset["examples"][0]["action"] = 99
        raw = bakeoff.canonical_json(dataset)
        digest = bakeoff.sha256_bytes(raw)
        (self.root / "dataset" / f"dataset-{digest}.json").write_bytes(raw)
        self.receipt["dataset_sha256"] = digest
        with self.assertRaisesRegex(ValueError, "dataset cannot be reinterpreted"):
            self.load()

    def test_nonfinite_features_and_incompatible_targets_reject(self):
        self.state[0, 0] = np.nan
        self.save()
        with self.assertRaisesRegex(ValueError, "shape, dtype or values"):
            self.load()
        self.state[0, 0] = 0
        self.targets = np.zeros((len(self.rows), 3, 8), dtype=np.float32)
        self.save()
        with self.assertRaisesRegex(ValueError, "shape, dtype or values"):
            self.load()

    def test_metadata_size_substitution_rejects(self):
        self.receipt["embedding_artifact"]["bytes"] += 1
        with self.assertRaisesRegex(ValueError, "size binding"):
            self.load()

    def test_source_receipt_requires_an_explicit_digest(self):
        with self.assertRaisesRegex(ValueError, "source receipt digest"):
            training.retrain(self.root / "missing", "not-a-digest", self.root / "output")


if __name__ == "__main__":
    unittest.main()
