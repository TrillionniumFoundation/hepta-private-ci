"""Reject plausible but invalid complete-census repair evidence."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from ...abc_recovery.base_recovery import file_sha
from ..training.evaluate import METRICS
from .analysis import load_cubes
from .protocol import ALL_ARMS


class EvidenceBoundaryTests(unittest.TestCase):
    def fixture(self, root):
        spec = {"seeds": [17, 29], "count": 3, "views": ["clean", "noise"], "scenarios": 2,
                "source_identity": {"source_role": "unallocated_test", "sha256": "frozen-original-IDs"},
                "role": "repair_test", "origin_role": "unallocated_test",
                "role_assignment_sha256": "explicit-new-allocation", "start": 0, "models": []}
        rows = []
        for seed in spec["seeds"]:
            for arm in ALL_ARMS:
                path = root / f"{seed}-{arm}.npz"
                values = {f"{observer}/{metric}": np.full((3, 2, 2), 1. if metric in ("success", "complete") else .3)
                          for observer in ("primary", "secondary") for metric in METRICS}
                np.savez_compressed(path, **values)
                model_sha = f"same-source-{seed}-{arm}"
                spec["models"].append({"seed": seed, "arm": arm, "sha256": model_sha})
                rows.append({"seed": seed, "arm": arm, "sha256": model_sha,
                             "data_file": str(path), "data_sha256": file_sha(path)})
        execution = {"status": "completed", "protocol_sha256": "protocol", "models": rows,
                     "source_identity": spec["source_identity"]}
        access = {"protocol_sha256": "protocol", "source_identity": spec["source_identity"],
                  "role": "repair_test", "origin_role": "unallocated_test",
                  "role_assignment_sha256": "explicit-new-allocation", "start": 0, "count": 3}
        (root / "result.json").write_text(json.dumps(execution))
        (root / "access-registration.json").write_text(json.dumps(access))
        return spec, execution, access

    def test_complete_census_and_missing_treatment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, result, _ = self.fixture(root)
            cubes = load_cubes(root, spec, "protocol")
            self.assertEqual(cubes["primary"]["matched_floor_warmdual"]["utility"].shape, (2, 3, 2, 2))
            result["models"].pop()
            (root / "result.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                load_cubes(root, spec, "protocol")

    def test_replay_cannot_replace_an_unexecuted_arm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, result, _ = self.fixture(root)
            result["models"][-1] = deepcopy(result["models"][0])
            (root / "result.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_cubes(root, spec, "protocol")

    def test_prior_final_cannot_be_relabelled_as_new_holdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _, access = self.fixture(root)
            access.update(role="test", start=512)
            (root / "access-registration.json").write_text(json.dumps(access))
            with self.assertRaisesRegex(ValueError, "relabeled"):
                load_cubes(root, spec, "protocol")

    def test_array_hash_and_original_model_binding_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, result, _ = self.fixture(root)
            row = result["models"][0]
            row["sha256"] = "another-trained-model"
            (root / "result.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "foreign"):
                load_cubes(root, spec, "protocol")
            row["sha256"] = spec["models"][0]["sha256"]
            (root / "result.json").write_text(json.dumps(result))
            with Path(row["data_file"]).open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "array changed"):
                load_cubes(root, spec, "protocol")


if __name__ == "__main__":
    unittest.main()
