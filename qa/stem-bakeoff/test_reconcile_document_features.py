"""Actual tiny Transformer checks explicit cache rebind, misses and identity guards."""

import contextlib
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from full_source_features import file_sha
from long_document_encoder import LongDocumentEncoder
from long_document_sources import canonical, sha
from real_cell_features import load_features
from real_encoder import CANDIDATES, FrozenRealEncoder
from reconcile_document_features import reconcile_features
import test_generic_dataset_features as generic_fixture
import test_shared_feature_extract as tiny_fixture


class ReconcileDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generic_fixture.GenericDatasetFeaturesTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        generic_fixture.GenericDatasetFeaturesTests.tearDownClass()

    def fixture(self, root):
        old_dataset, acquired, rows = generic_fixture.GenericDatasetFeaturesTests().fixture(root)
        report = generic_fixture.GenericDatasetFeaturesTests().run_export(old_dataset, acquired, root / "prior")
        current = json.loads(canonical(rows))
        current[1]["source_version"]["candidate"] = "f" * 40
        current[2]["text"] = "alpha beta " * 4
        extra = json.loads(canonical(current[2]))
        extra.update(source_id="operational:new", group_id="new-group", text="beta alpha " * 7)
        current.append(extra)
        for row in current:
            row["text_utf8_bytes"] = len(row["text"].encode())
            row["text_utf8_sha256"] = sha(row["text"].encode())
        dataset = root / "new-dataset.json"
        dataset.write_bytes(canonical({"rows": current}))
        return old_dataset, dataset, acquired, current, report, file_sha(root / "prior/report.json")

    def run_reconcile(self, root, fixture, mode, name="out"):
        old_dataset, dataset, acquired, _, _, pin = fixture
        tiny = tiny_fixture.SharedFeatureExtractTests
        with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": tiny.weight_hash, "width": 8}), \
                contextlib.redirect_stdout(io.StringIO()):
            return reconcile_features(dataset, old_dataset, root / "prior", pin, tiny.root, acquired,
                root / name, candidate="granite97m", reuse_policy=mode, batch_size=1, threads=1)

    def test_rebind_preserves_tensor_origin_but_creates_new_event_and_encodes_changed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root)
            report = self.run_reconcile(root, fixture, "content_rebind")
            cache = report["encoding"]["cache"]
            self.assertEqual((cache["strict_hits"], cache["explicit_content_rebinds"], cache["misses"]), (1, 1, 2))
            self.assertEqual(report["encoding"]["physical_forward_calls"], 2)
            self.assertEqual(report["encoding"]["total_historical_physical_forward_calls"],
                             fixture[4]["encoding"]["physical_forward_calls"] + 2)
            self.assertGreaterEqual(report["reconciliation"]["wall_ns"], report["load"]["wall_ns"] +
                                    report["encoding"]["new_encoding_receipt"]["wall_ns"])
            old_values, _ = load_features(root / "prior", fixture[0])
            values, _ = load_features(root / "out", fixture[1])
            np.testing.assert_array_equal(values[:2], old_values[:2])
            self.assertEqual(report["feature_identity"], fixture[4]["feature_identity"])
            documents = [json.loads(line) for line in gzip.decompress((root / "out/documents.jsonl.gz").read_bytes()).splitlines()]
            rebound = documents[1]
            self.assertEqual(rebound["binding"]["tensor_origin"]["kind"], "cache_rebind")
            self.assertEqual(rebound["binding"]["tensor_origin"]["prior_report_sha256"], fixture[5])
            self.assertNotEqual(rebound["source_version"], rebound["binding"]["tensor_origin"]["prior_source_version"])
            self.assertNotEqual(rebound["source_record_digest"], fixture[4]["source_record_digests"][1])
            self.assertEqual(rebound["binding"]["event"]["source_version"], rebound["source_version"])
            self.assertEqual([d["binding"]["tensor_origin"]["kind"] for d in documents],
                             ["cache_hit", "cache_rebind", "new_forward", "new_forward"])
            logs = [json.loads(line) for line in (root / "out/forwards.jsonl").read_bytes().splitlines()]
            self.assertEqual([r["new_dataset_row_indices"] for r in logs], [[2], [3]])
            for row, doc in zip(fixture[3], documents):
                self.assertEqual(doc["chunks"][-1]["utf8_span"][1], len(row["text"].encode()))
            self.assertEqual(file_sha(root / "prior/report.json"), fixture[5])

    def test_strict_policy_reencodes_changed_versions_and_matches_rebind_numerically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root)
            strict = self.run_reconcile(root, fixture, "strict", "strict")
            rebound = self.run_reconcile(root, fixture, "content_rebind", "rebound")
            self.assertEqual(strict["encoding"]["physical_forward_calls"], 3)
            self.assertEqual(strict["encoding"]["cache"]["explicit_content_rebinds"], 0)
            self.assertEqual(strict["encoding"]["cache"]["misses"], 3)
            a, _ = load_features(root / "strict", fixture[1])
            b, _ = load_features(root / "rebound", fixture[1])
            np.testing.assert_allclose(a, b, atol=2e-6, rtol=2e-6)
            self.assertEqual(strict["feature_identity"], rebound["feature_identity"])

    def test_actual_owner_identity_change_rejects_before_new_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root)
            def changed_owner(**kwargs):
                return FrozenRealEncoder(**(kwargs | {"scope_id": "different-owner-scope"}))
            with patch("reconcile_document_features.FrozenRealEncoder", side_effect=changed_owner), \
                    patch.object(LongDocumentEncoder, "encode") as encode, self.assertRaisesRegex(ValueError, "identity differs"):
                self.run_reconcile(root, fixture, "content_rebind")
            encode.assert_not_called()
            self.assertFalse((root / "out/report.json").exists())

    def test_new_dataset_mutation_during_actual_encoding_cannot_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root)
            original = LongDocumentEncoder.encode
            def change(encoder, *args, **kwargs):
                result = original(encoder, *args, **kwargs)
                fixture[1].write_bytes(fixture[1].read_bytes() + b" ")
                return result
            with patch.object(LongDocumentEncoder, "encode", change), self.assertRaisesRegex(ValueError, "changed"):
                self.run_reconcile(root, fixture, "content_rebind")
            self.assertFalse((root / "out/report.json").exists())
            self.assertFalse((root / "out/features.npz").exists())


if __name__ == "__main__":
    unittest.main()
