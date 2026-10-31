"""Reject incomplete or mislabeled final results before statistical analysis."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from ...abc_recovery.base_recovery import file_sha
from .analysis import load_cubes
from .evaluate import ALL_ARMS, METRICS


class CensusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.protocol = {"seeds": [17, 29, 43, 59, 71], "count": 256,
            "views": list(range(8)), "scenarios": 2, "source_identity": {"test_identity": "frozen"}, "models": []}
        data = {f"{o}/{m}": np.zeros((256, 8, 2)) for o in ("primary", "secondary") for m in METRICS}
        path = self.directory / "data.npz"
        np.savez_compressed(path, **data)
        rows = []
        for seed in self.protocol["seeds"]:
            for arm in ALL_ARMS:
                model = {"seed": seed, "arm": arm, "sha256": str(seed) + arm}
                self.protocol["models"].append(model)
                rows.append({**model, "data_file": str(path), "data_sha256": file_sha(path)})
        self.execution = {"status": "completed", "protocol_sha256": "frozen",
            "source_identity": self.protocol["source_identity"], "models": rows}
        self.access = {"protocol_sha256": "frozen", "role": "test", "start": 512,
            "count": 256, "source_identity": self.protocol["source_identity"]}
        self.write()

    def tearDown(self):
        self.temporary.cleanup()

    def write(self):
        (self.directory / "result.json").write_text(json.dumps(self.execution))
        (self.directory / "access-registration.json").write_text(json.dumps(self.access))

    def test_full_census_loads_but_missing_seed_arm_fails(self):
        result = load_cubes(self.directory, self.protocol, "frozen")
        self.assertEqual(result["primary"]["risk_success"]["success"].shape, (5, 256, 8, 2))
        self.execution["models"].pop()
        self.write()
        with self.assertRaisesRegex(ValueError, "omitted"):
            load_cubes(self.directory, self.protocol, "frozen")

    def test_duplicate_replay_does_not_replace_a_missing_treatment(self):
        self.execution["models"][-1] = self.execution["models"][0]
        self.write()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_cubes(self.directory, self.protocol, "frozen")

    def test_historical_role_cannot_be_relabelled_as_final(self):
        self.access["role"] = "train"
        self.write()
        with self.assertRaisesRegex(ValueError, "same-protocol"):
            load_cubes(self.directory, self.protocol, "frozen")

    def test_data_identity_change_is_rejected(self):
        (self.directory / "data.npz").write_bytes(b"replaced")
        with self.assertRaisesRegex(ValueError, "data changed"):
            load_cubes(self.directory, self.protocol, "frozen")


if __name__ == "__main__":
    unittest.main()
