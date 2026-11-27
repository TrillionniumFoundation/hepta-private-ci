"""Hand-made clocks/intake mocks; no real Fashion file or model training."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from . import run
from .cost import Budget
from .lifecycle import Progress


class SharedOwnershipTests(unittest.TestCase):
    def test_indices_close_shared_then_transition_belongs_once_to_build(self):
        now = [140 * run.NS]
        metadata = {"rows": [{"fold": i % 3} for i in range(5)]}
        original = run.prepare_policy_indices

        def preparation(*args):
            result = original(*args)
            now[0] = 149 * run.NS
            return result

        with tempfile.TemporaryDirectory() as directory:
            budget = Budget(directory, clock=lambda: now[0], memory=lambda: 0)
            with patch.object(run, "prepare_policy_indices", side_effect=preparation) as operation:
                index, folds, boundary = run.close_shared_preparation(
                    [4, 2], [2, 4], metadata, budget, {"shared_CPU_ns": 150 * run.NS})
            np.testing.assert_array_equal(index, [1, 0])
            np.testing.assert_array_equal(folds, [2, 1])
            self.assertEqual(operation.call_count, 1)
            now[0] = 156 * run.NS  # phase transition and hand-made build work
            budget.row("seed-11-build", boundary)
            self.assertEqual(budget.rows[0]["end_cpu_ns"], budget.rows[1]["start_cpu_ns"])
            self.assertEqual(sum(row["cpu_ns"] for row in budget.rows), now[0])

    def test_indices_cross_shared_cap_before_any_model_construction(self):
        now = [140 * run.NS]
        handmade = {"images": np.zeros((2, 784), dtype=np.uint8),
                    "labels": np.array([0, 1], dtype=np.uint8),
                    "indices": {"FIT": np.array([0, 1]), "POLICY": np.array([0, 1])},
                    "metadata": {"rows": [{"fold": 0}, {"fold": 1}]}}
        original = run.prepare_policy_indices

        def preparation(*args):
            result = original(*args)
            now[0] = 151 * run.NS
            return result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "handmade-output"
            frozen = root / "handmade-freeze.json"
            frozen.write_text("{}")
            budget = Budget(output, clock=lambda: now[0], memory=lambda: 0)
            with (patch.object(run, "preflight"),
                  patch.object(run, "FROZEN", frozen),
                  patch.object(run, "MARKER", root / "handmade-opened.json"),
                  patch.object(run, "Budget", return_value=budget),
                  patch.object(run, "prepare_policy_indices", side_effect=preparation),
                  patch("fashion_research.data.load_train", return_value=handmade),
                  patch("fashion_research.data.noisy_images", return_value=np.zeros((2, 784), dtype=np.float32)),
                  patch("threadpoolctl.threadpool_info", return_value=[{"num_threads": 1}]),
                  patch("fashion_research.model.ContentModel") as model):
                code = run.worker("unused-handmade-path", output)
            terminal = json.loads((output / "result.json").read_text())
            model.assert_not_called()
            self.assertEqual(code, 1)
            self.assertIn("actual phase CPU cap exceeded", terminal["reason"])
            self.assertEqual(terminal["started_seeds"], [])
            self.assertEqual(terminal["unrun_seeds"], [11, 23, 47])
            self.assertEqual(budget.rows[0]["stage"], "shared_intake_noise_and_policy_indices")
            self.assertEqual(budget.rows[0]["cpu_ns"], 151 * run.NS)


class ClosingBoundaryTests(unittest.TestCase):
    def check_closing_failure(self, *, oracle_positive, policy_start_ns, preclose_ns,
                              expected_end_ns, expected_reason):
        now = [0]
        handmade = {"images": np.zeros((2, 784), dtype=np.uint8),
                    "labels": np.array([0, 1], dtype=np.uint8),
                    "indices": {"FIT": np.array([0, 1]), "POLICY": np.array([0, 1])},
                    "metadata": {"rows": [{"fold": 0}, {"fold": 1}]}}
        values = {s: np.full(2, .2) for s in ["", "T", "I", "J"] +
                  [a + b for a in "TIJ" for b in "TIJ"]}
        if oracle_positive:
            values.update(JT=np.array([.6, .1]), JI=np.array([.1, .6]))
        model = Mock()
        model.digest.return_value = "handmade-model"
        model.optimizer_digest.return_value = "handmade-optimizer"
        actor = Mock()
        actor.digest.return_value = "handmade-actor"
        actor.predict.return_value = np.zeros((2, 3))
        complete = Progress.complete_stage

        def train(*args):
            now[0] = policy_start_ns
            return {"mock_only": True}

        def labels(*args):
            now[0] = preclose_ns
            return np.zeros((2, 32)), values, 0

        def flushed(progress, stage, seed=None):
            complete(progress, stage, seed)
            if stage == "policy":
                now[0] += 30_000_000  # hand-made30ms JSON/flush/fsync cost

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "mock-closing-output"
            frozen = root / "mock-freeze.json"
            frozen.write_text("{}")
            budget = Budget(output, clock=lambda: now[0], memory=lambda: 0)
            with (patch.object(run, "preflight"), patch.object(run, "FROZEN", frozen),
                  patch.object(run, "MARKER", root / "mock-opened.json"),
                  patch.object(run, "Budget", return_value=budget),
                  patch.object(run, "cpu_ns", side_effect=lambda: now[0]),
                  patch.object(run, "train_content", side_effect=train),
                  patch.object(run, "labels_and_features", side_effect=labels),
                  patch.object(run, "fit_actor", return_value=(
                      np.array([0, 1]), [], np.zeros((2, 3)), np.zeros((2, 3)), "handmade-actor")) as fit,
                  patch.object(Progress, "complete_stage", new=flushed),
                  patch("fashion_research.data.load_train", return_value=handmade),
                  patch("fashion_research.data.noisy_images", return_value=np.zeros((2, 784), dtype=np.float32)),
                  patch("threadpoolctl.threadpool_info", return_value=[{"num_threads": 1}]),
                  patch("fashion_research.model.ContentModel", return_value=model) as model_class,
                  patch("fashion_research.model.Actor") as actor_class):
                model_class.load.return_value = model
                actor_class.load.return_value = actor
                code = run.worker("unused-mock-path", output)
            terminal = json.loads((output / "result.json").read_text())
            self.assertEqual(code, 1)
            self.assertEqual(terminal["exit_code"], 1)
            self.assertEqual(terminal["status"], "failed")
            self.assertIn(expected_reason, terminal["reason"])
            self.assertEqual(terminal["started_seeds"], [11])
            self.assertEqual(terminal["unrun_seeds"], [23, 47])
            self.assertEqual(fit.call_count, int(oracle_positive))
            row = terminal["cost_before_required_receipt"]["stages"][-1]
            self.assertEqual(row["stage"], "seed-11-complete-build")
            self.assertEqual(row["end_cpu_ns"], expected_end_ns)
            self.assertEqual(row["cpu_ns"], expected_end_ns)

    def test_normal_closing_fsync_crosses_build450_with_policy_still_under150(self):
        self.check_closing_failure(oracle_positive=True, policy_start_ns=300_200_000_000,
                                  preclose_ns=449_990_000_000, expected_end_ns=450_020_000_000,
                                  expected_reason="seed build CPU cap exceeded at closing timestamp")

    def test_oracle_negative_closing_crosses_policy150_with_build_still_under450(self):
        self.check_closing_failure(oracle_positive=False, policy_start_ns=299_970_000_000,
                                  preclose_ns=449_960_000_000, expected_end_ns=449_990_000_000,
                                  expected_reason="policy CPU cap exceeded at closing timestamp")


if __name__ == "__main__":
    unittest.main()
