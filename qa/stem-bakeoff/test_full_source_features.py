"""Complete-source export compatibility and separately measured exact range reads."""

import contextlib
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from full_source_features import export_full_features
from long_document_sources import canonical, sha
from real_cell_features import load_features
from real_encoder import CANDIDATES
import test_long_document_sources as source_fixture
import test_shared_feature_extract as tiny_fixture


class FullSourceFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny_fixture.SharedFeatureExtractTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        tiny_fixture.SharedFeatureExtractTests.tearDownClass()

    def test_actual_export_keeps_complete_source_and_existing_global_loader_contract(self):
        fixture = tiny_fixture.SharedFeatureExtractTests
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, text = source_fixture.FullSourceBankTests().fixture(root, "alpha beta " * 1700 + "tail")
            acquired = root / "acquisition.json"
            acquired.write_bytes(canonical({"candidate": "granite97m",
                "revision": CANDIDATES["granite97m"]["revision"],
                "repository": CANDIDATES["granite97m"]["repository"],
                "inventory_sha256": fixture.inventory["inventory_sha256"]}))
            with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": fixture.weight_hash, "width": 8}), \
                    contextlib.redirect_stdout(io.StringIO()):
                report = export_full_features(*paths[:2], paths[2], fixture.root, acquired, root / "out",
                                              candidate="granite97m", threads=1)
            values, receipt = load_features(root / "out", paths[0])
            self.assertEqual(values.shape, (1, 8))
            self.assertEqual(receipt["feature_identity"], report["feature_identity"])
            self.assertGreater(report["encoding"]["chunks"], 1)
            self.assertEqual(report["encoding"]["physical_forward_calls"],
                             report["plan"]["expected_physical_forward_calls"])
            self.assertEqual(report["retained_native_token_bytes"], 0)
            with np.load(root / "out/chunk-features.npz", allow_pickle=False) as arrays:
                self.assertEqual(arrays["features"].shape, (report["encoding"]["chunks"], 8))
                self.assertTrue((arrays["document_indices"] == 0).all())
                self.assertEqual(arrays["chunk_indices"].tolist(), list(range(len(arrays["features"]))))
            documents = [json.loads(line) for line in gzip.decompress((root / "out/documents.jsonl.gz").read_bytes()).splitlines()]
            self.assertEqual(documents[0]["source_utf8_bytes"], len(text.encode()))
            self.assertGreater(documents[0]["source_utf8_bytes"], 16384)
            self.assertEqual(documents[0]["chunks"][-1]["utf8_span"][1], len(text.encode()))
            reads = json.loads((root / "out/exact-tail-reads.json").read_bytes())
            self.assertEqual((reads["byte_exact_tail_reads"], reads["missing_stale_rejections"]), (1, 3))
            self.assertEqual((reads["encoder_calls"], reads["head_updates"]), (0, 0))
            manifest = json.loads((root / "out/manifest.json").read_bytes())
            for name, identity in manifest.items():
                self.assertEqual(sha((root / "out" / name).read_bytes()), identity["sha256"])
            with self.assertRaisesRegex(ValueError, "new output"):
                export_full_features(*paths[:2], paths[2], fixture.root, acquired, root / "out", candidate="granite97m")

    def test_changed_checkpoint_registration_rejects_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, _ = source_fixture.FullSourceBankTests().fixture(root, "alpha")
            acquired = root / "acquisition.json"
            acquired.write_bytes(canonical({"candidate": "granite97m", "revision": "stale", "repository": "wrong"}))
            with self.assertRaisesRegex(ValueError, "checkpoint acquisition"):
                export_full_features(*paths[:2], paths[2], root / "missing", acquired, root / "out", candidate="granite97m")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
