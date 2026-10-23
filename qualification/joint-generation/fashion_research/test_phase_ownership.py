"""Hand-made clocks/intake mocks; no real Fashion file or model training."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import run
from .cost import Budget


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


if __name__ == "__main__":
    unittest.main()
