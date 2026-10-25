"""Real Head/Adam replay plus faults in action, identity and sampler state."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from cell_field_action_io import save_arrays, write_json
from cell_field_mpc_v4 import execute_policy
from cell_field_replay_v4 import CANDIDATE, _mpc_replay
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


class ReplayAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name) / "complete"
        rng = np.random.default_rng(17)
        cls.split = {role: (rng.normal(size=(8, 8)), np.tile(np.arange(4), 2))
                     for role in ("old_train", "old_probe", "current_train", "current_probe")}
        cls.projected = np.vstack([pair[0] for pair in cls.split.values()])
        contexts = {role: dataset_digest(*cls.split[role]) for role in ("old_train", "current_train")}
        bindings = {"task": "engineering-fixture", "seed": 7, "head_mode": "linear"}
        cls.state = CellTrainingState(NumpyCellHead(8, 4, "linear", seed=7), bindings=bindings,
            seed=7, contexts=contexts, active_context="old_train")
        for _ in range(8):
            cls.state.advance(*cls.split["old_train"])
        cls.state.select_context("current_train")
        cls.expected = {"expected_bindings": bindings, "expected_protocol": cls.state.protocol,
                        "expected_contexts": contexts}
        cls.plan = {"h": 0.02, "effort_price": 0.1, "mpc": {"steps": 8,
            "policies": [CANDIDATE], "action_bound": 1.0, "cost": "engineering-fixture"}}
        x, y = cls.split["old_probe"]
        cls.anchor = float(cls.state.head.loss_gradients(normalize_features(x), y, 0.0)[0])
        result = execute_policy(cls.state, cls.split, cls.plan, cls.projected, cls.anchor,
                                CANDIDATE, cls.directory)
        if result["status"] != "completed":
            raise AssertionError(result["error"])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def audit(self, directory, expected=None):
        return _mpc_replay(directory, self.state, expected or self.expected, self.split,
                           self.projected, self.plan, self.anchor)

    def test_midpoint_restores_and_replans_the_real_eight_step_policy(self):
        result = self.audit(self.directory)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["state_receipts_and_probabilities_exact"])
        self.assertEqual(result["replayed_suffix_steps"], 4)

    def test_changed_saved_action_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "changed"
            shutil.copytree(self.directory, target)
            with np.load(target / "trajectory.npz", allow_pickle=False) as archive:
                arrays = {name: archive[name] for name in archive.files}
            arrays["actions"][4, 0] += 1e-5
            save_arrays(target / "trajectory.npz", arrays)
            with self.assertRaisesRegex(ValueError, "saved causal action"):
                self.audit(target)

    def test_seed_and_midpoint_sampler_state_are_bound(self):
        wrong = {**self.expected, "expected_bindings": {**self.expected["expected_bindings"], "seed": 17}}
        with self.assertRaisesRegex(ValueError, "checkpoint identity"):
            self.audit(self.directory, wrong)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "changed"
            shutil.copytree(self.directory, target)
            path = target / "midpoint/manifest.json"
            manifest = json.loads(path.read_bytes())
            manifest["rng"]["state"]["state"] ^= 1
            write_json(path, manifest)
            with self.assertRaisesRegex(ValueError, "complete training state checksum"):
                self.audit(target)


if __name__ == "__main__":
    unittest.main()
