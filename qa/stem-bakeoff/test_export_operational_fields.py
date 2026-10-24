"""Verify source-only exports and native owner orchestration without model weights."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from export_operational_fields import export_baseline, export_native
from long_document_sources import canonical, sha
from operational_field_features import source_only_features
from test_operational_field_plan import fixture


class ExportFieldTests(unittest.TestCase):
    def test_baseline_has_new_identity_exact_rows_and_no_encoder_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, _, _, plan, _, pin = fixture(root)
            first = export_baseline(dataset, plan, root / "hash", expected_plan_sha256=pin, kind="identifier_hash770")
            second = export_baseline(dataset, plan, root / "scalar", expected_plan_sha256=pin, kind="identifier_overlap3")
            self.assertEqual(first["feature_shape"], [2, 770])
            self.assertEqual(second["feature_shape"], [2, 3])
            self.assertNotEqual(first["feature_identity"], second["feature_identity"])
            self.assertEqual((first["encoder_forward_calls"], first["gradient_updates"]), (0, 0))
            with np.load(root / "hash/features.npz", allow_pickle=False) as archive:
                expected = np.stack([source_only_features(r["text"], r["input_regions"])[0]
                                     for r in json.loads(dataset.read_bytes())["rows"]])
                np.testing.assert_array_equal(archive["features"], expected)

    def test_mid_export_source_mutation_cannot_become_a_completed_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, _, _, plan, _, pin = fixture(root)
            def mutate(*args):
                result = source_only_features(*args)
                dataset.write_bytes(dataset.read_bytes() + b" ")
                return result
            with patch("export_operational_fields.source_only_features", side_effect=mutate), self.assertRaisesRegex(ValueError, "changed"):
                export_baseline(dataset, plan, root / "out", expected_plan_sha256=pin, kind="identifier_overlap3")
            self.assertFalse((root / "out/report.json").exists())

    def test_native_adapter_calls_one_owner_and_preserves_all_field_origins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, snapshot, acquired, plan_root, plan, pin = fixture(root)
            def fake_owner(field_dataset, actual_snapshot, actual_acquisition, output, **options):
                self.assertEqual(options, {"candidate": "granite97m", "batch_size": 16, "threads": 4})
                self.assertEqual((actual_snapshot, actual_acquisition), (snapshot, acquired))
                rows = json.loads(Path(field_dataset).read_bytes())["rows"]
                self.assertEqual([r["source_id"] for r in rows], plan["field_source_ids"])
                values = np.zeros((len(rows), 384), np.float32)
                for i in range(len(rows)): values[i, i] = 1
                output.mkdir()
                np.savez_compressed(output / "features.npz", features=values)
                report = {"plan": {"document_plan_sha256": plan["document_plan_sha256"],
                    "source_ids": plan["field_source_ids"], "pooling": "fixture"},
                    "feature_identity": "a" * 64, "feature_shape": [len(rows), 384],
                    "feature_archive_sha256": sha((output / "features.npz").read_bytes()),
                    "feature_tensor_sha256": sha(values.tobytes()), "checkpoint_inventory_sha256": "b" * 64,
                    "source_record_digests": [sha(canonical(row)) for row in rows],
                    "encoding": {"physical_forward_calls": plan["planned_physical_forwards"]}, "load": {"fixture": True}}
                (output / "report.json").write_bytes(canonical(report))
                return report
            with patch("generic_dataset_features.export_generic_features", side_effect=fake_owner) as owner:
                report = export_native(dataset, plan_root, snapshot, acquired, root / "out", expected_plan_sha256=pin)
            self.assertEqual(owner.call_count, 1)
            self.assertEqual(report["feature_shape"], [2, 770])
            self.assertNotEqual(report["feature_identity"], "a" * 64)
            origins = json.loads((root / "out/source-bindings.json").read_bytes())
            self.assertEqual(origins[0]["field_tensor_origins"]["change"], origins[1]["field_tensor_origins"]["change"])
            self.assertNotEqual(origins[0]["source_id"], origins[1]["source_id"])


if __name__ == "__main__":
    unittest.main()
