"""Synthetic receipt-contract tests; these fixtures contain no learned model."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from .bank_integrity_audit import digest, object_hash, local_hash, optimizer_hash, expected_resources, verify_phase


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def fixture(root):
    study, pilot_root, directory = root / "study", root / "pilot", root / "fit-17"
    study.mkdir(); pilot_root.mkdir(); directory.mkdir()
    (root / "source.py").write_text("# synthetic fixture only\n")
    sources = {"source.py": digest(root / "source.py")}
    recipe = {"name": "synthetic", "steps": 16, "learning_rate": .2}
    pilot = {"candidates": [recipe], "batch_size": 64, "conditions": ["a", "b", "c", "d"],
             "response_panel": {"pairs": 128, "conditions": ["a", "b", "c", "d"]},
             "clean_probe": {"pairs": 128, "conditions": ["a"]}}
    parameters = {"synthetic": torch.tensor([1.0, 2.0])}
    optimizer = {"param_groups": [{"lr": .2, "params": [0]}], "state": {0: {"momentum_buffer": torch.tensor([.5, .25])}}}
    lh, oh, output = local_hash(parameters), optimizer_hash(optimizer), "f" * 64
    pilot_result = {"selected": {"index": 0}, "results": {"17": {"action": 4,
                    "candidates": [{"history": [{"local_sha256": lh}]}]}}}
    put(pilot_root / "PILOT_RESULT.json", pilot_result)
    protocol = {"selected_recipe": "synthetic", "macro_steps": 8, "multipliers": [0, .25, 1, 2],
                "fit_trajectory_ids": list(range(8)), "audit_trajectory_ids": list(range(8, 16)),
                "actuator_pilot_result_sha256": digest(pilot_root / "PILOT_RESULT.json")}
    put(study / "PILOT_PROTOCOL.json", pilot); put(study / "BANK_PROTOCOL.json", protocol)
    records, predictions = [], []
    clock = 100
    for trajectory in range(8):
        rng = np.random.default_rng(271028 + 17 * 1009 + trajectory * 7919)
        schedule_id = 0 if trajectory < 4 else trajectory
        for step in (0, 8):
            schedule = [{"batch_seed": 17 * 100003 + 600000 + schedule_id * 1009 + s,
                         "noise_seed": 107 + s, "condition": pilot["conditions"][s % 4]}
                        for s in range(step, step + 8)]
            row = {"seed": 17, "trajectory": trajectory, "step": step, "partition": "fit",
                   "state": [.5, 0, 0, 0, 0, 0, 0], "state_sha256": lh, "optimizer_sha256": oh,
                   "schedule_sha256": object_hash(schedule), "current_value": .5, "before_output_sha256": output}
            prediction = {**row, "committed_monotonic_ns": clock}
            predictions.append(prediction)
            row.update(prediction_commit_sha256=object_hash(prediction), action_values=[.5] * 4,
                       branches=[{"action": a, "model_sha256": lh, "optimizer_sha256": oh,
                                  "output_sha256": output, "semantic_change_fraction": 0.,
                                  "measured_monotonic_ns": clock + a + 1} for a in range(4)],
                       trajectory_action=trajectory if trajectory < 4 else int(rng.integers(4)),
                       outcomes_completed_monotonic_ns=clock + 5)
            records.append(row); clock += 10
        np.savez_compressed(directory / f"trajectory-{trajectory}-values.npz", values=np.full((2, 4, 512), .5))
        torch.save({"parameters": parameters, "optimizer": optimizer, "local_sha256": lh,
                    "optimizer_sha256": oh, "recipe": recipe,
                    "metadata": {"trajectory": trajectory, "seed": 17, "phase": "fit"}},
                   directory / f"trajectory-{trajectory}-terminal.pt")
    with (directory / "PREDICTIONS_BEFORE_OUTCOMES.jsonl").open("w") as out:
        for prediction in predictions:
            out.write(json.dumps(prediction) + "\n")
    resources = expected_resources(16, 4, pilot, protocol)
    bank = {"records": records, "source_files": sources, "registered_commit": "synthetic",
            "phase": "fit", "seed": 17, "recipe": recipe, "fixed_action": 4, "resources": resources,
            "gradient_steps": 512, "gradient_examples": 32768, "audit_observer_loaded": False,
            "test_retention_scored": False, "same_fixed_training_value_panel": True}
    put(directory / "BANK.json", bank)
    put(directory / "SOURCE_FREEZE.json", {"files": sources, "registered_commit": "synthetic"})
    put(directory / "COMPLETE.json", {"bank_sha256": digest(directory / "BANK.json"), "rows": 16, "source_files": sources})
    return directory, study, pilot_root


def mutate_bank(directory, change):
    path = directory / "BANK.json"
    bank = json.loads(path.read_text()); change(bank); put(path, bank)
    complete_path = directory / "COMPLETE.json"
    complete = json.loads(complete_path.read_text()); complete["bank_sha256"] = digest(path); put(complete_path, complete)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-bank-check-")
        self.directory, self.study, self.pilot = fixture(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def check(self):
        return verify_phase(self.directory, "fit", 17, self.study, self.pilot)

    def test_complete_consistent_receipts(self):
        self.assertEqual(self.check()["individual_hard_values_checked"], 32768)

    def test_changed_value_array_rejected(self):
        values = np.full((2, 4, 512), .5); values[0, 1, 2] = .8
        np.savez_compressed(self.directory / "trajectory-0-values.npz", values=values)
        with self.assertRaisesRegex(ValueError, "reconstruct recorded means"):
            self.check()

    def test_changed_terminal_momentum_rejected(self):
        path = self.directory / "trajectory-0-terminal.pt"
        data = torch.load(path, weights_only=True)
        data["optimizer"]["state"][0]["momentum_buffer"].add_(1)
        torch.save(data, path)
        with self.assertRaisesRegex(ValueError, "Terminal stored"):
            self.check()

    def test_claimed_gradient_cost_cannot_be_reduced(self):
        mutate_bank(self.directory, lambda bank: bank["resources"].update(candidate_backward_calls=0))
        with self.assertRaisesRegex(ValueError, "workload counts"):
            self.check()

    def test_post_outcome_prediction_rejected(self):
        mutate_bank(self.directory, lambda bank: bank["records"][0]["branches"][0].update(measured_monotonic_ns=99))
        with self.assertRaisesRegex(ValueError, "predates"):
            self.check()

    def test_changed_executed_source_rejected(self):
        (self.study.parent / "source.py").write_text("# changed\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.check()


if __name__ == "__main__":
    unittest.main()
