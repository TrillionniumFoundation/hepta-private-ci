"""Runner input identity, label isolation and portable evidence I/O checks."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import cell_field_action_io as io


class ActionIOTests(unittest.TestCase):
    def fixture(self, root):
        data, features = root / "data", root / "features"
        data.mkdir()
        features.mkdir()
        specifications = [("old_train", 64, "train", "04"), ("old_probe", 32, "train", "04"),
            ("old_validation", 64, "validation", "04"), ("old_test", 64, "final", "04"),
            ("current_train", 64, "train", "05"), ("current_probe", 32, "train", "05"),
            ("current_validation", 64, "validation", "05"), ("future_june", 48, "final", "06"),
            ("future_july", 128, "final", "07"), ("future_august", 64, "final", "08")]
        roles = [{"role": role, "rows": amount, "access": access, "month": "2014-" + month}
                 for role, amount, access, month in specifications]
        plan = {"source_role_plan": roles, "source_counts": {r["role"]: r["rows"] for r in roles},
                "source_archive_sha256": "fixed-zip", "source_split_salt": "fixed-salt", "prior_experiments": {},
                "optimizer": {"sampler": "full_batch"}, "classes": 4, "encoder_revision": "fixed-revision",
                "projection": {"width": 8, "seed": 20261024}}
        protocol = root / "protocol.json"
        io.write_json(protocol, plan)
        sources, predictors, partitions = [], [], {access: {} for access in ("train", "validation", "final")}
        for spec in roles:
            indices = list(range(len(sources), len(sources) + spec["rows"]))
            for index in indices:
                sources.append({"index": index, "source_id": f"uci-news:{index}", "raw_source_id": str(index),
                    "component_id": f"group-{index}", "month": spec["month"], "role": spec["role"],
                    "timestamp_ms": index, "source_row_sha256": "0" * 64,
                    "normalized_title_sha256": "1" * 64, "publisher_sha256": "2" * 64,
                    "component_member_count": 1, "component_members_sha256": "3" * 64})
                predictors.append({"source_id": f"uci-news:{index}", "source_version": "sha256:" + "0" * 64, "text": f"text {index}"})
            partitions[spec["access"]][spec["role"]] = {"indices": indices, "labels": [i % 4 for i in indices],
                                                         "source_ids": [f"uci-news:{i}" for i in indices]}
        schema = "hepta.cell-action-news.v3"
        io.write_json(data / "sources.json", {"schema": schema, "rows": sources})
        io.write_json(data / "predictors.json", {"schema": schema, "rows": predictors})
        for access, contents in partitions.items():
            io.write_json(data / (access + "_labels.json"), {"schema": schema, "classes": 4, "roles": contents})
        receipt = {"schema": schema, "files": {p.name: {"sha256": io.file_hash(p), "bytes": p.stat().st_size} for p in data.iterdir()},
                   "protocol_sha256": io.file_hash(protocol), "source_archive_sha256": plan["source_archive_sha256"],
                   "salt": plan["source_split_salt"], "prior_experiments": {},
                   "roles": {r["role"]: {"month": r["month"], "rows": r["rows"], "labels_per_class": r["rows"] // 4,
                                          "access": r["access"]} for r in roles}}
        io.write_json(data / "data_receipt.json", receipt)
        feature_plan = {"protocol_sha256": io.file_hash(protocol), "data_receipt_sha256": io.file_hash(data / "data_receipt.json"),
                        "predictors_sha256": io.file_hash(data / "predictors.json"), "source_ids": [s["source_id"] for s in sources],
                        "labels_enter_encoder": False}
        io.write_json(features / "plan.json", feature_plan)
        matrix = np.random.default_rng(91).normal(size=(624, 384)).astype(np.float32)
        io.save_arrays(features / "features.npz", {"features": matrix})
        import hashlib
        report = {"plan": feature_plan, "shape": [624, 384], "dtype": "float32",
                  "feature_sha256": io.file_hash(features / "features.npz"), "tensor_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
                  "encoder_identity": {"checkpoint_revision": "fixed-revision"}, "encoder_updates": 0,
                  "encoder_load": {"model": {"trainable_parameter_count": 0}}}
        io.write_json(features / "report.json", report)
        return data, features, protocol

    def test_complete_input_binding_without_withheld_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            data, features, protocol = self.fixture(Path(directory))
            original = Path.open

            def guarded(path, *args, **kwargs):
                io.deny_withheld_labels("open", (str(path), "r", 0))
                return original(path, *args, **kwargs)

            with patch.object(Path, "open", guarded):
                loaded = io.load_inputs(data, features, protocol)
            self.assertEqual(loaded["features"].shape, (624, 384))
            self.assertEqual(set(loaded["labels"]["roles"]), io.TRAIN_ROLES)
            self.assertEqual(len(loaded["input_hashes"]), 8)
            self.assertTrue(all(Path(key).name not in {"validation_labels.json", "final_labels.json"} for key in loaded["input_paths"]))
            projected, _ = io.project(loaded["features"], loaded["plan"])
            split = io.split_arrays(projected, loaded["labels"])
            self.assertEqual({role: x.shape for role, (x, _) in split.items()},
                             {"old_train": (64, 8), "old_probe": (32, 8), "current_train": (64, 8), "current_probe": (32, 8)})

    def test_changed_predictor_and_reordered_feature_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            data, features, protocol = self.fixture(Path(directory))
            original = (data / "predictors.json").read_bytes()
            (data / "predictors.json").write_bytes(original + b"\n")
            with self.assertRaisesRegex(ValueError, "differs from receipt"):
                io.load_inputs(data, features, protocol)
            (data / "predictors.json").write_bytes(original)
            plan = json.loads((features / "plan.json").read_bytes())
            plan["source_ids"][0], plan["source_ids"][1] = plan["source_ids"][1], plan["source_ids"][0]
            io.write_json(features / "plan.json", plan)
            report = json.loads((features / "report.json").read_bytes())
            report["plan"] = plan
            io.write_json(features / "report.json", report)
            with self.assertRaisesRegex(ValueError, "source order"):
                io.load_inputs(data, features, protocol)

    def test_validation_index_cannot_enter_training_even_if_metadata_is_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            data, features, protocol = self.fixture(Path(directory))
            labels = json.loads((data / "train_labels.json").read_bytes())
            labels["roles"]["old_train"]["indices"][0] = 96
            labels["roles"]["old_train"]["source_ids"][0] = "uci-news:96"
            io.write_json(data / "train_labels.json", labels)
            receipt = json.loads((data / "data_receipt.json").read_bytes())
            path = data / "train_labels.json"
            receipt["files"]["train_labels.json"] = {"sha256": io.file_hash(path), "bytes": path.stat().st_size}
            io.write_json(data / "data_receipt.json", receipt)
            feature_plan = json.loads((features / "plan.json").read_bytes())
            feature_plan["data_receipt_sha256"] = io.file_hash(data / "data_receipt.json")
            io.write_json(features / "plan.json", feature_plan)
            report = json.loads((features / "report.json").read_bytes())
            report["plan"] = feature_plan
            io.write_json(features / "report.json", report)
            with self.assertRaisesRegex(ValueError, "training labels"):
                io.load_inputs(data, features, protocol)

    def test_projection_matches_v2_and_rejects_nonfinite_inputs(self):
        from cell_field_run import _project

        matrix = np.arange(64, dtype=np.float32).reshape(4, 16)
        plan = {"projection": {"width": 8, "seed": 20261024}}
        actual, q = io.project(matrix, plan)
        expected, old_q = _project(matrix, plan)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(q, old_q)
        matrix[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "invalid feature"):
            io.project(matrix, plan)

    def test_failure_json_is_explicit_and_arrays_never_require_pickle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            io.write_json(root / "nested/failure.json", {"count": np.int64(2), "valid": np.bool_(False),
                "raw": np.array([np.nan, np.inf, -np.inf]), "tuple": (np.float64(1.5),)})
            self.assertEqual(json.loads((root / "nested/failure.json").read_bytes()),
                {"count": 2, "valid": False, "raw": [{"__nonfinite__": "nan"}, {"__nonfinite__": "+inf"}, {"__nonfinite__": "-inf"}], "tuple": [1.5]})
            io.save_arrays(root / "arrays/output.bin", {"raw": np.array([1.0, np.nan])})
            with np.load(root / "arrays/output.bin", allow_pickle=False) as arrays:
                np.testing.assert_array_equal(arrays["raw"], np.array([1.0, np.nan]))
            with self.assertRaisesRegex(ValueError, "pickle"):
                io.save_arrays(root / "bad.npz", {"bad": np.array([{}], dtype=object)})
            for name in ("validation_labels.json", "final_labels.json"):
                with self.assertRaises(PermissionError):
                    io.deny_withheld_labels("open", (bytes(root / name), "rb", 0))


if __name__ == "__main__":
    unittest.main()
