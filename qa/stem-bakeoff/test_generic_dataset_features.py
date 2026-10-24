"""Actual small Transformer proves label isolation and full-source export custody."""

import contextlib
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from generic_dataset_features import export_generic_features, read_sources
from long_document_chunks import tokenize_documents
from long_document_encoder import LongDocumentEncoder
from long_document_sources import canonical, sha
from real_cell_features import load_features
from real_encoder import CANDIDATES
import test_shared_feature_extract as tiny_fixture


class GenericDatasetFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny_fixture.SharedFeatureExtractTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        tiny_fixture.SharedFeatureExtractTests.tearDownClass()

    def fixture(self, root):
        rows = []
        for i, text in enumerate(("alpha beta " * 1600 + "最终尾部", "beta alpha", "alpha")):
            rows.append({"source_id": f"operational:{i}", "group_id": f"group-{i}",
                "text": text, "text_utf8_bytes": len(text.encode()), "text_utf8_sha256": sha(text.encode()),
                "source_version": {"base": "0" * 40, "candidate": f"{i:040x}"},
                "split": ("train", "calibration", "holdout")[i],
                "labels": {"OUTCOME_MUST_NEVER_ENTER_TEXT": i % 2}, "provenance": {"gold": "SECRET_RESULT"}})
        dataset, acquired = root / "dataset.json", root / "acquisition.json"
        dataset.write_bytes(canonical({"rows": rows}))
        acquired.write_bytes(canonical({"candidate": "granite97m", "revision": CANDIDATES["granite97m"]["revision"],
            "repository": CANDIDATES["granite97m"]["repository"],
            "inventory_sha256": tiny_fixture.SharedFeatureExtractTests.inventory["inventory_sha256"]}))
        return dataset, acquired, rows

    def run_export(self, dataset, acquired, output):
        fixture = tiny_fixture.SharedFeatureExtractTests
        with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": fixture.weight_hash, "width": 8}), \
                contextlib.redirect_stdout(io.StringIO()):
            return export_generic_features(dataset, fixture.root, acquired, output,
                                           candidate="granite97m", threads=1)

    def test_actual_complete_export_is_source_ordered_and_only_text_enters_tokenization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, acquired, rows = self.fixture(root)
            with patch("generic_dataset_features.tokenize_documents", wraps=tokenize_documents) as tokenizer:
                report = self.run_export(dataset, acquired, root / "out")
            self.assertEqual(tokenizer.call_args.args[1], [r["text"] for r in rows])
            values, receipt = load_features(root / "out", dataset)
            self.assertEqual(values.shape, (3, 8))
            self.assertEqual(receipt["plan"]["source_ids"], [r["source_id"] for r in rows])
            documents = [json.loads(line) for line in gzip.decompress((root / "out/documents.jsonl.gz").read_bytes()).splitlines()]
            for row, doc in zip(rows, documents):
                self.assertEqual(doc["source_version"], "sha256:" + sha(canonical(row["source_version"])))
                self.assertEqual(doc["source_version_input"], row["source_version"])
                self.assertEqual(doc["chunks"][-1]["utf8_span"][1], len(row["text"].encode()))
            self.assertGreater(documents[0]["source_utf8_bytes"], 16384)
            self.assertEqual(report["encoding"]["physical_forward_calls"], report["plan"]["expected_physical_forward_calls"])
            self.assertEqual(report["encoding"]["native_content_tokens_dropped"], 0)
            self.assertEqual(report["retained_native_token_bytes"], 0)
            with np.load(root / "out/chunk-features.npz", allow_pickle=False) as archive:
                chunks = archive["features"]
                for index, doc in enumerate(documents):
                    selected = chunks[archive["document_indices"] == index].astype(np.float64)
                    weights = np.array([c["aggregation_weight"] for c in doc["chunks"]])
                    pooled = (selected * weights[:, None]).sum(0) / doc["content_tokens"]
                    expected = (pooled / np.linalg.norm(pooled)).astype(np.float32)
                    np.testing.assert_array_equal(values[index], expected)
            manifest = json.loads((root / "out/manifest.json").read_bytes())
            for name, record in manifest.items():
                self.assertEqual(sha((root / "out" / name).read_bytes()), record["sha256"])

    def test_stale_text_duplicate_sources_and_missing_versions_fail_before_loading_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, acquired, rows = self.fixture(root)
            for variant in ("hash", "duplicate", "version"):
                changed = json.loads(canonical(rows))
                if variant == "hash": changed[0]["text"] += "silently changed"
                elif variant == "duplicate": changed[1]["source_id"] = changed[0]["source_id"]
                else: changed[0]["source_version"] = {}
                dataset.write_bytes(canonical({"rows": changed}))
                with patch("generic_dataset_features.FrozenRealEncoder") as owner, self.assertRaises(ValueError):
                    self.run_export(dataset, acquired, root / variant)
                owner.assert_not_called()
                self.assertFalse((root / variant).exists())

    def test_source_change_during_actual_encoding_cannot_publish_a_valid_feature_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, acquired, _ = self.fixture(root)
            original = LongDocumentEncoder.encode
            def changing(encoder, *args, **kwargs):
                result = original(encoder, *args, **kwargs)
                dataset.write_bytes(dataset.read_bytes() + b" ")
                return result
            with patch("generic_dataset_features.LongDocumentEncoder.encode", changing), \
                    self.assertRaisesRegex(ValueError, "changed during encoding"):
                self.run_export(dataset, acquired, root / "out")
            self.assertFalse((root / "out/report.json").exists())
            self.assertFalse((root / "out/features.npz").exists())


if __name__ == "__main__":
    unittest.main()
