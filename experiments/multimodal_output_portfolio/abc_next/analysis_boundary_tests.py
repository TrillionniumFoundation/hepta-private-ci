"""Synthetic files verify source/seed axes and fixed development references."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ..abc_recovery.base_recovery import file_sha
from ..abc_recovery.control import PLANS
from ..abc_recovery.statistics import crossed_bootstrap, paired_comparison
from ..abc_recovery.trees import METRICS
from ..v7.data import VIEWS
from . import analysis
from .execute import POLICIES
from .settings import ARMS, SEEDS


class AnalysisBoundaryTests(unittest.TestCase):
    def fixture(self, directory):
        directory = Path(directory)
        start, count, scenarios = 7, 3, 2
        ids = [f"synthetic-original:{i}" for i in range(2 * (start + count))]
        manifest = directory / "synthetic-manifest.json"
        manifest.write_text(json.dumps({"roles": {"test": {"source_ids": ids}}}))
        controllers = directory / "synthetic-controllers"
        controllers.mkdir()
        choices = [{"seed": seed, "arm": arm, "selection": {"selected_nonfeedback": ("fixed", "static", "one_shot")[(s + a) % 3]}}
                   for s, seed in enumerate(SEEDS) for a, arm in enumerate(ARMS)]
        (controllers / "result.json").write_text(json.dumps({"controllers": choices}))
        interval = {"role": "test", "start": start, "count": count, "scenarios": scenarios}
        protocol = {"source_ranges": {"test": interval}, "resources": {"manifest_sha256": file_sha(manifest)},
                    "controllers_directory": str(controllers), "controllers_result_sha256": file_sha(controllers / "result.json")}
        census = [(case, view, scenario) for view in VIEWS for case in range(start, start + count) for scenario in range(scenarios)]
        models = []
        for s, seed in enumerate(SEEDS):
            for a, arm in enumerate(ARMS):
                path = directory / f"seed-{seed}" / arm
                path.mkdir(parents=True)
                utility = torch.tensor([[.001 * s + .01 * a + .02 * p + .0001 * (case - start)
                    + .00001 * VIEWS.index(view) + .000001 * scenario for p in range(len(POLICIES))]
                    for case, view, scenario in census], dtype=torch.float64)
                plans = torch.tensor([[(s + a + p + case + VIEWS.index(view) + scenario) % len(PLANS)
                                      for p in range(len(POLICIES))] for case, view, scenario in census])
                metrics = {name: {m: (utility.clone() if m == "utility" else (1 - utility) / 2 if m == "joint_loss"
                                     else torch.ones_like(utility) if m == "required_output_complete" else torch.zeros_like(utility))
                                  for m in METRICS} for name in ("primary", "secondary")}
                data = {"cases": [r[0] for r in census], "views": [r[1] for r in census],
                    "scenarios": [r[2] for r in census], "source_ids": [ids[2 * r[0]:2 * r[0] + 2] for r in census],
                    "policies": list(POLICIES), "paths": plans, "metrics": metrics}
                torch.save(data, path / "data.pt")
                models.append({"seed": seed, "arm": arm, "directory": str(path), "data_sha256": file_sha(path / "data.pt")})
        result = {"phase": "test", "source_range": interval, "models": models}
        (directory / "result.json").write_text(json.dumps(result))
        return manifest, protocol, result

    def test_full_source_view_scenario_axis_and_per_seed_development_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, protocol, _ = self.fixture(directory)
            with patch.object(analysis, "MANIFEST", manifest):
                cubes, plan_counts = analysis.load_cubes(Path(directory), protocol)
            for observer in ("primary", "secondary"):
                for s, seed in enumerate(SEEDS):
                    for a, arm in enumerate(ARMS):
                        for p, policy in enumerate(POLICIES):
                            expected = np.array([[[.001 * s + .01 * a + .02 * p + .0001 * case + .00001 * view + .000001 * scenario
                                                   for scenario in range(2)] for view in range(8)] for case in range(3)])
                            actual = cubes[observer][arm, policy]["utility"][s]
                            np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-14)
                            path_ids = np.array([[[(s + a + p + case + 7 + view + scenario) % 21
                                                   for scenario in range(2)] for view in range(8)] for case in range(3)])
                            lengths = np.array([len(plan) for plan in PLANS])[path_ids]
                            np.testing.assert_allclose(cubes[observer][arm, policy]["net_utility"][s], expected - .002 * lengths, atol=1e-14)
                            np.testing.assert_array_equal(cubes[observer][arm, policy]["semantic_then_stop"][s], path_ids == 1)
                            self.assertEqual(sum(plan_counts[f"{seed}/{arm}/{policy}"]), 48)
                        chosen = ("fixed", "static", "one_shot")[(s + a) % 3]
                        for metric in (*METRICS, *analysis.ADDED):
                            np.testing.assert_array_equal(cubes[observer][arm, analysis.BASELINE][metric][s], cubes[observer][arm, chosen][metric][s])
                        # Legacy has the largest synthetic utility. The selected
                        # reference still comes from frozen development choices.
                        self.assertTrue(np.all(cubes[observer][arm, analysis.BASELINE]["utility"][s] < cubes[observer][arm, "legacy"]["utility"][s]))

    def test_task_source_and_column_corruption_is_rejected_even_with_new_file_hash(self):
        mutations = ("missing_row", "duplicate_task", "duplicate_source", "wrong_columns", "metric_width", "nonfinite")
        with tempfile.TemporaryDirectory() as directory:
            manifest, protocol, result = self.fixture(directory)
            path = Path(result["models"][0]["directory"]) / "data.pt"
            original = path.read_bytes()
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    path.write_bytes(original)
                    data = torch.load(path, weights_only=True)
                    if mutation == "missing_row":
                        data["cases"] = data["cases"][:-1]
                    elif mutation == "duplicate_task":
                        data["scenarios"][1] = data["scenarios"][0]
                    elif mutation == "duplicate_source":
                        data["source_ids"][2] = data["source_ids"][0]
                    elif mutation == "wrong_columns":
                        data["policies"][0], data["policies"][1] = data["policies"][1], data["policies"][0]
                    elif mutation == "metric_width":
                        data["metrics"]["primary"]["utility"] = data["metrics"]["primary"]["utility"][:, :-1]
                    else:
                        data["metrics"]["primary"]["utility"][0, 0] = float("nan")
                    torch.save(data, path)
                    result["models"][0]["data_sha256"] = file_sha(path)
                    (Path(directory) / "result.json").write_text(json.dumps(result))
                    with patch.object(analysis, "MANIFEST", manifest), self.assertRaises(ValueError):
                        analysis.load_cubes(Path(directory), protocol)

    def test_missing_or_duplicate_trained_seed_arm_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, protocol, result = self.fixture(directory)
            original = list(result["models"])
            for changed in (original[:-1], [*original, original[0]]):
                result["models"] = changed
                (Path(directory) / "result.json").write_text(json.dumps(result))
                with patch.object(analysis, "MANIFEST", manifest), self.assertRaises(ValueError):
                    analysis.load_cubes(Path(directory), protocol)

    def test_source_only_bootstrap_never_resamples_the_five_fitted_seeds(self):
        crossed = crossed_bootstrap(5, 3, replicates=128, seed=9917)
        original = crossed.seed_indices.copy()
        fixed = analysis.source_only_plan(crossed)
        np.testing.assert_array_equal(fixed.seed_indices, np.tile(np.arange(5), (128, 1)))
        np.testing.assert_array_equal(fixed.source_indices, crossed.source_indices)
        np.testing.assert_array_equal(crossed.seed_indices, original)
        self.assertFalse(np.shares_memory(fixed.source_indices, crossed.source_indices))
        values = np.broadcast_to(np.arange(5)[:, None, None, None] / 10, (5, 3, 8, 2)).copy()
        reference = np.zeros_like(values)
        conditional = paired_comparison(values, reference, bootstrap=fixed)
        population = paired_comparison(values, reference, bootstrap=crossed)
        np.testing.assert_allclose(conditional["interval"], [.2, .2], atol=1e-14)
        self.assertGreater(population["interval"][1] - population["interval"][0], .1)
        values += np.arange(3)[None, :, None, None] / 10
        source_varies = paired_comparison(values, reference, bootstrap=fixed)
        self.assertGreater(source_varies["interval"][1] - source_varies["interval"][0], .05)


if __name__ == "__main__":
    unittest.main()
