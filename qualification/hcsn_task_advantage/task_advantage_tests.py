"""Paired task loss, causal continuous derivatives, and holdout/resume contracts."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from qualification.hcsn_adaptive.batched_flow import FlowConfig
from qualification.hcsn_adaptive.datasets import load_split, make_synthetic
from .campaign import finalize_trial, freeze, seal_selection_set, summary
from .model import TaskBoundaryModel, gradient_diagnostic
from .train import train_trial


class TaskAdvantageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)

    def fixture(self):
        torch.manual_seed(642803)
        model = TaskBoundaryModel(FlowConfig(input_size=2, bins=4, content_size=2,
                                             stages=2, upper_mode="reflecting"), length=8, horizon=4)
        x = torch.randn(10, 8, 2, dtype=torch.float64)*.3
        y = -.2-(x[:, -1, :1]-.5).square()
        dt = np.full((10, 8), .1)
        model.fit_readout(x[:5], dt[:5], y[:5])
        return model, x[5:], dt[5:], y[5:]

    def test_teacher_matches_same_clock_full_counterfactuals(self):
        model, x, dt, y = self.fixture()
        teacher = model.teacher(x, dt, y, split="train", event_cost=.01)
        for side, value in (("low", -.25), ("high", .25)):
            predicted = model.predict(x, dt, {"kind": "fixed", "value": value})
            torch.testing.assert_close(teacher[side]["prediction"], predicted["prediction"])
            torch.testing.assert_close(teacher[side]["events"], predicted["events"])
            self.assertEqual(predicted["state"].time_micros, 800000)
            torch.testing.assert_close(predicted["state"].boundary, torch.zeros_like(predicted["state"].boundary))
        expected = teacher["low"]["loss"]-teacher["high"]["loss"]-.01*(
            teacher["high"]["events"]-teacher["low"]["events"])
        torch.testing.assert_close(teacher["advantage"], expected[:, None])
        self.assertEqual(teacher["decision_clock_micros"], 400000)
        with self.assertRaises(ValueError):
            model.teacher(x, dt, y, split="dev", event_cost=.01)
        with self.assertRaises(ValueError):
            model.teacher(x, dt, y, split="train", event_cost=float("nan"))

    def test_causal_boundary_population_input_fd_ad(self):
        model, x, dt, _ = self.fixture()
        with torch.no_grad():
            model.critic.weight.zero_()
            model.critic.bias.zero_()
            model.critic.weight[0, :model.encoder.config.bins] = torch.linspace(-.6, .8, model.encoder.config.bins)
            state_width = (1+model.encoder.config.content_size)*(model.encoder.config.bins+model.encoder.config.stages+1)
            model.critic.weight[0, state_width] = .7
        diagnostic = gradient_diagnostic(model, x)
        for row in diagnostic["directions"].values():
            self.assertTrue(row["passed"])
            self.assertGreater(abs(row["ad"]), 1e-8)
        policy = {"kind": "task", "temperature_multiplier": 1., "offset_multiplier": 0.}
        changed = x.clone()
        changed[:, model.decision_step+1:] += 5
        original = model.predict(x, dt, policy)["pulse"]
        torch.testing.assert_close(original, model.predict(changed, dt, policy)["pulse"])
        self.assertTrue(bool(((original > -.25) & (original < .25)).all()))

    def test_pause_resume_complete_seal_and_single_final_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_synthetic(root / "data", seed=846310, train=8, dev=4, test=4, length=6)
            config = {"experiment_id": "task-advantage-fixture", "data_dir": str(root / "data"),
                      "seeds": [164], "train_limit": 8, "horizon": 2,
                      "shared_budget": {"wall_seconds": 120}, "budget": {"wall_seconds": 120}}
            (root / "config.json").write_text(json.dumps(config))
            allowed, seen = {"train", "dev"}, []

            def guarded(directory, split, expected):
                self.assertIn(split, allowed)
                seen.append(split)
                return load_split(directory, split, expected)

            with patch("qualification.hcsn_task_advantage.campaign.load_split", side_effect=guarded), \
                 patch("qualification.hcsn_task_advantage.train.load_split", side_effect=guarded):
                manifest = freeze(root / "config.json", root / "manifest.json")
                output = root / "output"
                fixed = manifest["trials"][1]
                paused = train_trial(manifest, fixed, output, stop_after=1)
                self.assertEqual(paused["status"], "paused")
                with self.assertRaises((FileNotFoundError, ValueError)):
                    seal_selection_set(manifest, output)
                records = [train_trial(manifest, trial, output, resume=trial == fixed) for trial in manifest["trials"]]
                self.assertEqual(len({record["readout_sha256"] for record in records}), 1)
                self.assertNotIn("test", seen)
                records, _ = seal_selection_set(manifest, output)
                allowed.add("test")
                for trial, record in zip(manifest["trials"], records):
                    result = finalize_trial(manifest, trial, output, record)
                    self.assertEqual(result["final_evaluation_count"], 1)
                    self.assertEqual(finalize_trial(manifest, trial, output, record), result)
                self.assertEqual(seen.count("test"), 4)
                costs = summary(manifest, output)
                self.assertEqual(costs["unavailable_or_uncertain_costs"], [])
                self.assertEqual(costs["total_reserved_work_deduplicated"]["development_queries"], 28)
                with self.assertRaises(ValueError):
                    train_trial(manifest, fixed, output, resume=True)
                other = output / "trials" / manifest["trials"][-1]["id"] / "training.json"
                other.write_text(other.read_text()+" ")
                with self.assertRaises(ValueError):
                    finalize_trial(manifest, manifest["trials"][0], output, records[0])


if __name__ == "__main__":
    unittest.main()
