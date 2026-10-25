"""Exact cold-process replay and refusal of inconsistent candidate evidence."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_action_control import build_action_model, plan_action
from cell_field_action_replay import deny_withheld_labels, verify_action_replays
from cell_field_control import build_reference
from cell_field_features import file_hash
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, canonical


def save_arrays(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **values)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


class ActionReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(624)
        cls.old_x, cls.current_x = rng.normal(size=(16, 2)), rng.normal(size=(16, 2))
        cls.old_y, cls.current_y = np.arange(16) % 2, np.arange(16) % 2
        cls.state = CellTrainingState(NumpyCellHead(2, 2, "gated", seed=7),
            bindings={"fixture": "synthetic-cold-replay-only"},
            contexts={"old": dataset_digest(cls.old_x, cls.old_y),
                      "current": dataset_digest(cls.current_x, cls.current_y)}, active_context="old")
        for _ in range(8):
            cls.state.advance(cls.old_x, cls.old_y)
        cls.state.select_context("current")
        cls.reference = build_reference(cls.state, cls.current_x, cls.current_y,
            ((cls.current_x, cls.current_y), (cls.old_x, cls.old_y)), horizon=8)
        cls.models = {obs: build_action_model(cls.reference, observation=obs) for obs in ("loss2", "full")}
        cls.source = Path(__file__).parent
        cls.hashes = {name: file_hash(cls.source / name) for name in
            ("cell_field_action_replay.py", "cell_field_action_control.py", "cell_field_state.py")}

    def fixture(self, root):
        protocol = {"evaluation_horizon": 8, "h": 0.02, "action_bound": 1.0}
        write_json(root / "inputs/protocol.json", protocol)
        train = {"old_train_x": self.old_x, "old_train_y": self.old_y,
                 "current_train_x": self.current_x, "current_train_y": self.current_y,
                 "current_probe_x": self.current_x, "current_probe_y": self.current_y,
                 "old_probe_x": self.old_x, "old_probe_y": self.old_y}
        save_arrays(root / "train_inputs.npz", train)
        save_arrays(root / "projected_features.npz", {"features": self.current_x, "projection": np.eye(2)})
        save_arrays(root / "references/anchor.npz", self.reference.arrays())
        initial = {"checkpoint_path": "initial/anchor", "state_sha256": self.state.digest(),
                   "old_probe_anchor": float(self.reference.observations[0, 1]), "model_paths": {}}
        self.state.save(root / initial["checkpoint_path"])
        for obs, model in self.models.items():
            path = f"models/anchor-{obs}.npz"
            save_arrays(root / path, model)
            initial["model_paths"][obs] = path
        options = {"objective": "direct_soft", "lookahead": 8,
                   "old_anchor": initial["old_probe_anchor"], "dt": 0.02,
                   "effort_price": 0.1, "action_bound": 1.0, "current_shift": 0.03,
                   "direct_coefficient": 0.03, "feasibility_tolerance": 1e-9,
                   "gap_tolerance": 1e-9, "max_iterations": 300, "ftol": 1e-13}
        candidate = plan_action(self.models["loss2"], **options)
        self.assertEqual(candidate["status"], "qualified", candidate["record"])
        arrays = {key: value for key, value in candidate.items() if isinstance(value, np.ndarray)}
        arrays.update({"problem__" + key: np.asarray(value) for key, value in candidate["problem"].items()})
        for obs, model in self.models.items():
            arrays["predicted_" + obs + "_fields"] = np.einsum("kij,j->ki", model["loss_maps"], candidate["u"])
        paths = {"reference": "references/anchor.npz", "model": "models/anchor-loss2.npz",
                 "candidate": "candidates/fixture.npz", "candidate_record": "candidates/fixture.json",
                 "trajectory": "trajectories/fixture.npz", "receipts": "receipts/fixture.json",
                 "checkpoint": "checkpoints/fixture", "midpoint": "midpoints/fixture", "head": "heads/fixture"}
        save_arrays(root / paths["candidate"], arrays)
        write_json(root / paths["candidate_record"], {"status": candidate["status"], "record": candidate["record"]})
        current, states, observations, receipts = self.state.clone(), [], [], []
        for k in range(9):
            states.append(current.vector())
            observations.append(self.reference.observe(current.vector())[0])
            if k == 4:
                current.save(root / paths["midpoint"])
            if k < 8:
                receipts.append(current.advance(self.current_x, self.current_y,
                    intervention=0.02 * candidate["actions"][k], mask=np.ones(current.parameter_count, dtype=bool)))
        current.save(root / paths["checkpoint"])
        observations = np.asarray(observations)
        save_arrays(root / paths["trajectory"], {"states": np.asarray(states), "observations": observations,
            "fields": observations[:, :2] - self.reference.observations[:, :2], "actions": candidate["actions"],
            **{name: value for name, value in arrays.items() if name.startswith("predicted_")}})
        write_json(root / paths["receipts"], receipts)
        record = {"run_id": "synthetic-loss2_h8_direct_soft", "method_id": "loss2_h8_direct_soft",
                  "status": "completed", "paths": paths, "planner_options": options,
                  "final_state_sha256": current.digest()}
        return protocol, record, initial

    def test_whole_candidate_recomputation_and_midpoint_complete_state_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol, record, initial = self.fixture(root)
            results = verify_action_replays(root, record, initial, protocol, self.hashes, self.source)
            self.assertEqual([row["segment"] for row in results], ["whole", "midpoint"])
            self.assertEqual([row["start_step"] for row in results], [8, 12])
            self.assertEqual([row["final_step"] for row in results], [16, 16])
            self.assertTrue(all(all(row["matches"].values()) for row in results))
            self.assertTrue(results[0]["candidate_arithmetic_equal_excluding_timing"])
            self.assertFalse(results[1]["candidate_recomputed"])
            detailed = json.loads((root / results[0]["result_path"]).read_bytes())
            self.assertTrue(all(detailed["both_model_predictions_equal"].values()))
            self.assertFalse(detailed["final_labels_opened"])
            self.assertFalse(detailed["validation_labels_opened"])

    def test_inconsistent_candidate_action_is_rejected_and_failure_logs_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol, record, initial = self.fixture(root)
            path = root / record["paths"]["candidate"]
            with np.load(path, allow_pickle=False) as archive:
                arrays = {key: archive[key].copy() for key in archive.files}
            arrays["actions"][0, 0] += 1e-5
            save_arrays(path, arrays)
            with self.assertRaisesRegex(ValueError, "cold replay child failed"):
                verify_action_replays(root, record, initial, protocol, self.hashes, self.source)
            log = root / f"replay/{record['run_id']}-whole.stderr.log"
            self.assertIn("cold candidate arrays or certificate arithmetic differ", log.read_text())
            self.assertTrue((root / f"replay/{record['run_id']}-whole.process.json").exists())

    def test_validation_and_final_payload_names_are_rejected(self):
        for value in ("/tmp/final_labels.json", Path("/tmp/validation_labels.json")):
            with self.assertRaises(PermissionError):
                deny_withheld_labels("open", (value, "r", 0))
        deny_withheld_labels("open", ("/tmp/train_labels.json", "r", 0))


if __name__ == "__main__":
    unittest.main()
