"""Actual tiny fits check randomness isolation and numerical state recovery."""

from pathlib import Path
import tempfile
import unittest

from . import crossed_training_fit as C
from .simulator import generate_dataset


def config():
    return {
        "schema": "pred1-crossed-train-dev-v1",
        "data_seeds": [910001, 910003],
        "init_seeds": [920001, 920003],
        "order_seeds": [930001, 930003],
        "variants": ["single_step", "gru"],
        "train_episodes": 16,
        "dev_episodes": 8,
        "history_length": 4,
        "epochs": 2,
        "batch_size": 8,
        "target_parameters": 128,
        "learning_rate": 0.003,
        "base_commit": "a" * 40,
        "expanded_budget": 16.0,
        "expanded_deadline": 20.0,
        "cost_profile": {
            "state_step_work": 0.001,
            "head_work": 0.002,
            "candidate_planning_work": 0.001,
            "state_step_time": 0.001,
            "head_time": 0.001,
            "candidate_planning_time": 0.001,
        },
    }


class CrossedFitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_actual_fit_separates_all_rngs_and_restores_selected_optimizer(self):
        cfg = config()
        samples = {
            seed: (
                generate_dataset(16, seed, "train", 4),
                generate_dataset(8, seed, "dev", 4),
            )
            for seed in cfg["data_seeds"]
        }
        seeds = [
            (910001, 920001, 930001),
            (910001, 920001, 930003),
            (910001, 920003, 930001),
            (910003, 920001, 930001),
            (910001, 920001, 930001),
        ]
        records = []
        for i, factors in enumerate(seeds):
            directory = self.root / str(i)
            directory.mkdir()
            record = C.fit(cfg, "gru", factors, *samples[factors[0]], directory)
            self.assertEqual(record["status"], "COMPLETE", record)
            checkpoint = C.Model.load(directory / record["checkpoint"])
            self.assertEqual(
                C.model_digest(checkpoint, optimizer=True),
                record["selected_optimizer_state_sha256"],
            )
            self.assertEqual(record["training_examples_consumed"], 32)
            self.assertEqual(record["fit_step_calls_consumed"], 4)
            self.assertGreaterEqual(
                record["optimizer_steps_consumed"], record["selected_checkpoint_steps"]
            )
            self.assertEqual(
                record["resource_panels"]["original_resources"]["arms"][
                    "fixed_1_cheap"
                ]["stop_rate"],
                1,
            )
            records.append(record)
        for i in (1, 3, 4):
            self.assertEqual(
                records[0]["initial_parameter_sha256"],
                records[i]["initial_parameter_sha256"],
            )
        self.assertNotEqual(
            records[0]["initial_parameter_sha256"],
            records[2]["initial_parameter_sha256"],
        )
        for i in (2, 3, 4):
            self.assertEqual(
                records[0]["batch_order_sha256"], records[i]["batch_order_sha256"]
            )
        self.assertNotEqual(
            records[0]["batch_order_sha256"], records[1]["batch_order_sha256"]
        )
        self.assertEqual(
            records[0]["selected_optimizer_state_sha256"],
            records[4]["selected_optimizer_state_sha256"],
        )
        self.assertNotEqual(
            samples[910001][0].fingerprint(), samples[910003][0].fingerprint()
        )
        existing = (self.root / "0" / records[0]["checkpoint"]).read_bytes()
        with self.assertRaises(FileExistsError):
            C.fit(cfg, "gru", seeds[0], *samples[910001], self.root / "0")
        self.assertEqual(
            existing, (self.root / "0" / records[0]["checkpoint"]).read_bytes()
        )


if __name__ == "__main__":
    unittest.main()
