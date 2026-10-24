"""Verify actual exported tensors, immutable cache ownership and external pins."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from document_feature_cache import verify_prior
from full_source_features import file_sha
from long_document_sources import canonical
from real_cell_features import load_features
import test_generic_dataset_features as generic_fixture


class DocumentCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generic_fixture.GenericDatasetFeaturesTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        generic_fixture.GenericDatasetFeaturesTests.tearDownClass()

    def fixture(self, root):
        dataset, acquired, rows = generic_fixture.GenericDatasetFeaturesTests().fixture(root)
        report = generic_fixture.GenericDatasetFeaturesTests().run_export(dataset, acquired, root / "prior")
        return dataset, acquired, rows, report, file_sha(root / "prior/report.json")

    def test_verified_cache_replays_global_pooling_and_owns_immutable_arrays(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, _, rows, report, pin = self.fixture(root)
            cached = verify_prior(root / "prior", dataset, pin)
            self.assertEqual(cached.feature_shape, (len(rows), 8))
            self.assertEqual(cached.chunk_shape[0], report["encoding"]["chunks"])
            with self.assertRaises(ValueError): cached.features().setflags(write=True)
            with self.assertRaises(ValueError): cached.chunks()[0, 0] = 7
            exposed = cached.metadata()
            exposed["records"][0]["text"] = "caller changed its copy"
            self.assertEqual(cached.metadata()["records"][0]["text"], rows[0]["text"])
            with np.load(root / "prior/features.npz", allow_pickle=False) as archive:
                np.testing.assert_array_equal(cached.features(), archive["features"])
            cached.verify_files()

    def test_report_pin_and_chunk_archive_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, _, _, _, pin = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "report"):
                verify_prior(root / "prior", dataset, "0" * 64)
            path = root / "prior/chunk-features.npz"
            raw = path.read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                verify_prior(root / "prior", dataset, pin)

    def test_changed_dataset_or_extra_artifact_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, _, rows, _, pin = self.fixture(root)
            cache = verify_prior(root / "prior", dataset, pin)
            dataset.write_bytes(canonical({"rows": list(reversed(rows))}))
            with self.assertRaisesRegex(ValueError, "changed"):
                cache.verify_files()
            with self.assertRaisesRegex(ValueError, "corpus"):
                verify_prior(root / "prior", dataset, pin)
            (root / "prior/unlisted.json").write_text(json.dumps({"extra": True}))
            with self.assertRaisesRegex(ValueError, "inventory"):
                verify_prior(root / "prior", dataset, pin)

    def test_late_source_mutation_cannot_be_adopted_as_the_expected_cache_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, _, _, _, pin = self.fixture(root)
            def changing(*args):
                result = load_features(*args)
                dataset.write_bytes(dataset.read_bytes() + b" ")
                return result
            with patch("document_feature_cache.load_features", side_effect=changing), \
                    self.assertRaisesRegex(ValueError, "changed"):
                verify_prior(root / "prior", dataset, pin)


if __name__ == "__main__":
    unittest.main()
