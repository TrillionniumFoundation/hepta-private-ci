import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from cell_learning_models import canonical
from cell_runtime_bundle import (MANIFEST_SCHEMA, MODES, SCHEMA, array_digest, inventory,
    load_serving_inputs, load_training_inputs, member, sha_file, verify_bundle)


class RuntimeBundleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)/"bundle"
        self.root.mkdir()
        self.x = np.arange(64*770, dtype=np.float32).reshape(64, 770)/10000
        self.y = np.array([0, 1]*16, dtype=np.int64)
        rows, sources = [], {}
        for i in range(64):
            source_id, text = f"source-{i}", f"original source {i}"
            binding = {"source_id": source_id, "version": i}
            text_sha = hashlib.sha256(text.encode()).hexdigest()
            row = {"source_id": source_id, "group_id": f"bug-{i}", "text_utf8_sha256": text_sha,
                "source_record_digest": hashlib.sha256(canonical(binding)).hexdigest(),
                "feature_row_sha256": hashlib.sha256(self.x[i].tobytes()).hexdigest()}
            rows.append(row)
            sources[source_id] = {"binding": binding, "input": {"source_id": source_id,
                "group_id": row["group_id"], "text": text, "text_utf8_sha256": text_sha,
                "split": "train" if i < 32 else "holdout", "labels": {"action_usefulness": None}}}
        self.write("sources.json", sources)
        self.write("training-rows.json", rows[:32])
        self.write("serving-rows.json", rows)
        np.savez_compressed(self.root/"training.npz", features=self.x[:32], labels=self.y)
        np.savez_compressed(self.root/"serving.npz", features=self.x)
        states = []
        for seed in (7, 17, 29):
            for budget in (8, 32, 64):
                for mode in MODES:
                    artifact = f"heads/{seed}-{budget}-{mode}"
                    path = self.root/artifact
                    path.mkdir(parents=True)
                    # These stand-ins exercise input readers, not Head loading.
                    (path/"weights.npz").write_bytes(b"not loaded by input-only readers")
                    self.write(artifact+"/manifest.json", {})
                    self.write(artifact+"/calibration.json", {})
                    states.append({"seed": seed, "budget": budget, "mode": mode, "artifact": artifact,
                        "calibration": artifact+"/calibration.json", "predictor_sha256": "a"*64,
                        "calibration_sha256": hashlib.sha256(b"{}").hexdigest()})
        self.meta = {"schema": SCHEMA, "feature_identity": "a"*64, "calibration_context_sha256": "b"*64,
            "task_id": "action_usefulness", "width": 770, "classes": 2, "generation": 1,
            "states": states, "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "quality_qualified": False,
            "training": {"archive": "training.npz", "rows": "training-rows.json", "role": "train",
                "budget": 32, "seed": 7, "source_ids": [r["source_id"] for r in rows[:32]],
                "feature_array_sha256": array_digest(self.x[:32]), "label_array_sha256": array_digest(self.y)},
            "serving": {"archive": "serving.npz", "rows": "serving-rows.json", "labels_included": False,
                "feature_array_sha256": array_digest(self.x)}}
        self.write("bundle.json", self.meta)
        self.pin = self.seal()

    def write(self, name, value):
        (self.root/name).write_bytes(canonical(value)+b"\n")

    def seal(self):
        self.write("manifest.json", {"schema": MANIFEST_SCHEMA, "files": inventory(self.root)})
        return sha_file(self.root/"manifest.json")

    def test_source_bound_inputs_and_relocation(self):
        meta, x, y, rows = load_training_inputs(self.root, expected_manifest_sha256=self.pin)
        self.assertEqual(meta, self.meta)
        np.testing.assert_array_equal(x, self.x[:32])
        np.testing.assert_array_equal(y, self.y)
        self.assertEqual(len({r["group_id"] for r in rows}), 32)
        moved = self.root.with_name("relocated")
        self.root.rename(moved)
        _, served, source_rows = load_serving_inputs(moved, expected_manifest_sha256=self.pin)
        np.testing.assert_array_equal(served, self.x)
        self.assertEqual(len(source_rows), 64)

    def test_external_pin_and_omitted_member_prevent_self_blessing(self):
        self.write("unexpected.json", {"extra": True})
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify_bundle(self.root, expected_manifest_sha256=self.pin)
        new_pin = self.seal()
        self.assertNotEqual(new_pin, self.pin)
        with self.assertRaisesRegex(ValueError, "external"):
            verify_bundle(self.root, expected_manifest_sha256=self.pin)
        verify_bundle(self.root, expected_manifest_sha256=new_pin)

    def test_unchanged_manifest_rejects_modified_numeric_payload(self):
        np.savez_compressed(self.root/"training.npz", features=self.x[:32]+1, labels=self.y)
        with self.assertRaisesRegex(ValueError, "member differs"):
            load_training_inputs(self.root, expected_manifest_sha256=self.pin)

    def test_semantic_source_and_label_checks_after_authorized_reseal(self):
        sources = json.loads((self.root/"sources.json").read_bytes())
        sources["source-0"]["input"]["text"] = "changed original bytes"
        self.write("sources.json", sources)
        with self.assertRaisesRegex(ValueError, "preserved"):
            load_serving_inputs(self.root, expected_manifest_sha256=self.seal())
        sources["source-0"]["input"]["text"] = "original source 0"
        sources["source-0"]["input"]["labels"]["action_usefulness"] = 1
        self.write("sources.json", sources)
        with self.assertRaisesRegex(ValueError, "pre-outcome"):
            load_training_inputs(self.root, expected_manifest_sha256=self.seal())

    def test_duplicate_training_groups_and_wrong_role_reject(self):
        rows = json.loads((self.root/"training-rows.json").read_bytes())
        rows[1]["group_id"] = rows[0]["group_id"]
        self.write("training-rows.json", rows)
        with self.assertRaises(ValueError):
            load_training_inputs(self.root, expected_manifest_sha256=self.seal())
        self.meta["training"]["role"] = "holdout"
        self.write("bundle.json", self.meta)
        with self.assertRaisesRegex(ValueError, "TRAIN"):
            load_training_inputs(self.root, expected_manifest_sha256=self.seal())

    def test_metadata_cannot_promote_a_preserved_holdout_source_to_train(self):
        sources = json.loads((self.root/"sources.json").read_bytes())
        sources["source-0"]["input"]["split"] = "holdout"
        self.write("sources.json", sources)
        with self.assertRaisesRegex(ValueError, "preserved"):
            load_training_inputs(self.root, expected_manifest_sha256=self.seal())

    def test_paths_symlinks_and_missing_state_members_reject(self):
        for name in ("../escape", "/absolute", "a/../b", "a\\b", "./file", "a//b", "C:/escape", "a:x"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                member(self.root, name)
        alias = self.root.with_name("alias")
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            verify_bundle(alias, expected_manifest_sha256=self.pin)
        (self.root/self.meta["states"][0]["artifact"]/"weights.npz").unlink()
        with self.assertRaisesRegex(ValueError, "state member"):
            verify_bundle(self.root, expected_manifest_sha256=self.seal())

    def test_huge_npy_header_rejects_before_loading_arrays(self):
        stream = io.BytesIO()
        np.lib.format.write_array_header_1_0(stream, {"descr": "<f4", "fortran_order": False,
                                                    "shape": (2**40, 770)})
        with zipfile.ZipFile(self.root/"serving.npz", "w") as archive:
            archive.writestr("features.npy", stream.getvalue())
        with patch("cell_runtime_bundle.np.load", side_effect=AssertionError("must reject before allocation")):
            with self.assertRaisesRegex(ValueError, "before allocation"):
                load_serving_inputs(self.root, expected_manifest_sha256=self.seal())


if __name__ == "__main__":
    unittest.main()
