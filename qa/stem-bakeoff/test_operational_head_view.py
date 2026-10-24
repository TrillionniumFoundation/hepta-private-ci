import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_calibrated_curve import sha_file, write_json
from operational_head_view import bind_features, build_view, full_normalized_text, verify_view
from run_calibrated_cells import load_inputs


class OperationalHeadViewTests(unittest.TestCase):
    def fixture(self, root):
        rows = []
        for split in ("train", "calibration", "holdout"):
            for i in range(4):
                source = f"{split}-{i}"
                text = f"independent source {source}: " + ("猫"*20000 if i == 0 else "complete code")
                rows.append(dict(source_id=source, group_id=source, text=text,
                    split=split, labels={"diagnostic_test_selection": i % 2}))
        path = root/"original.json"
        write_json(path, dict(rows=rows, selected_tasks=["diagnostic_test_selection"]))
        directory = root/"original-features"
        directory.mkdir()
        values = np.arange(len(rows)*4, dtype=np.float32).reshape(len(rows), 4)+1
        np.savez_compressed(directory/"features.npz", features=values)
        write_json(directory/"report.json", {"plan": {"dataset_sha256": sha_file(path),
            "source_ids": [r["source_id"] for r in rows]}, "feature_identity": "full-source-fixture",
            "feature_archive_sha256": sha_file(directory/"features.npz"),
            "feature_tensor_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
            "feature_shape": list(values.shape)})
        return path, directory, values

    def test_long_multibyte_view_preserves_full_features_and_calibration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, features, values = self.fixture(root)
            original_sha = sha_file(source)
            view = root/"view"
            receipt = build_view(source, view)
            self.assertEqual(receipt, verify_view(source, view))
            original = json.loads(source.read_bytes())
            data = json.loads((view/"dataset.json").read_bytes())
            for before, after, row_receipt in zip(original["rows"], data["rows"], receipt["rows"]):
                self.assertEqual({k: v for k, v in before.items() if k != "text"},
                                 {k: v for k, v in after.items() if k != "text"})
                self.assertLessEqual(len(after["text"].encode()), 32768)
                tail = before["text"].encode()[len(after["text"].encode()):]
                self.assertEqual(row_receipt["discarded_sha256"], hashlib.sha256(tail).hexdigest())
            alias = bind_features(source, view, features, root/"alias")
            _, actual, actual_report, _, _ = load_inputs(view/"dataset.json", root/"alias")
            self.assertTrue(np.array_equal(actual.view(np.uint8), values.view(np.uint8)))
            self.assertEqual(actual_report, alias)
            self.assertEqual(alias["feature_identity"], "full-source-fixture")
            self.assertEqual(sha_file(source), original_sha)
            self.assertEqual(receipt["truncated_rows"], 3)

    def test_prefix_collision_is_rejected_without_changing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, _, _ = self.fixture(root)
            data = json.loads(source.read_bytes())
            data["rows"][0]["text"] = "a"*32768+"first ending"
            data["rows"][-1]["text"] = "a"*32768+"different ending"
            source.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "duplicate equivalence"):
                build_view(source, root/"view")
            self.assertFalse((root/"view").exists())

    def test_changed_source_receipts_and_feature_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, features, _ = self.fixture(root)
            build_view(source, root/"view")
            receipt_path = root/"view/receipt.json"
            value = json.loads(receipt_path.read_bytes())
            value["rows"][0]["discarded_utf8_bytes"] += 1
            receipt_path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "receipts changed"):
                verify_view(source, root/"view")
            build_view(source, root/"clean-view")
            with (features/"features.npz").open("ab") as stream:
                stream.write(b"changed archive")
            with self.assertRaisesRegex(ValueError, "encoder receipt"):
                bind_features(source, root/"clean-view", features, root/"alias")
            with self.assertRaises(ValueError):
                full_normalized_text("x"*131073)

    def test_projection_and_binding_reject_mid_operation_source_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, features, _ = self.fixture(root)
            source_bytes = source.read_bytes()
            changed = False
            def mutate_during_normalization(text):
                nonlocal changed
                if not changed:
                    source.write_bytes(source_bytes+b" ")
                    changed = True
                return full_normalized_text(text)
            with patch("operational_head_view.full_normalized_text", side_effect=mutate_during_normalization):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    build_view(source, root/"view")
            source.write_bytes(source_bytes)
            build_view(source, root/"view")
            comparison = np.array_equal
            def mutate_receipt_during_copy(a, b):
                if a.dtype == np.uint8:
                    path = root/"view/receipt.json"
                    path.write_bytes(path.read_bytes()+b" ")
                return comparison(a, b)
            with patch("operational_head_view.np.array_equal", side_effect=mutate_receipt_during_copy):
                with self.assertRaisesRegex(ValueError, "source changed"):
                    bind_features(source, root/"view", features, root/"alias")


if __name__ == "__main__":
    unittest.main()
