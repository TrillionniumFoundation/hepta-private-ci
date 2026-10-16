import json
from pathlib import Path
import tempfile
import unittest

from stem_selection_experiment import (
    DEFAULT_VARIANTS,
    JsonlStemBenchmarkBackend,
    TaskCase,
    ValidationError,
    default_tasks,
    run_experiment,
)


class StemSelectionExperimentTests(unittest.TestCase):
    def test_four_registered_variants_use_same_workload_and_report_required_metrics(self):
        report = run_experiment(default_tasks(8), DEFAULT_VARIANTS, cells=4, training_budget=100)
        self.assertEqual(report["schema"], "hepta.experiment1-stem-selection.v1")
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["model_selection_authority"])
        self.assertEqual(len(report["results"]), 4)
        for result in report["results"]:
            self.assertEqual(result["cells"], 4)
            self.assertEqual(result["active_cells"], 1)
            self.assertIn("utility", result)
            self.assertIn("utility_per_active_flop", result)
            self.assertEqual(set(result["latency_us"]), {"p50", "p95", "p99"})
            self.assertIn("resident_memory_mb", result)
            self.assertIn("negative_transfer_mean", result)
            self.assertIn("capacity_gap_mean", result)
            self.assertIn("incremental_memory_per_cell_mb", result)
        replicated = next(r for r in report["results"] if r["variant_id"] == "replicate_full_421m")
        shared = next(r for r in report["results"] if r["variant_id"] == "small_stem_head")
        self.assertGreater(replicated["resident_memory_mb"], shared["resident_memory_mb"])
        self.assertEqual(shared["incremental_memory_per_cell_mb"], 8.0)
        self.assertEqual(replicated["incremental_memory_per_cell_mb"], 1684.0)
        self.assertLess(replicated["latency_us"]["p95"], 140.0)
        self.assertEqual(report["profile"]["task_ids"], [x.task_id for x in default_tasks(8)])

    def test_external_observations_are_loaded_and_active_workload_is_fair(self):
        tasks = default_tasks(1)
        rows = []
        for variant in DEFAULT_VARIANTS:
            rows.append(
                {
                    "variant_id": variant.variant_id,
                    "task_id": tasks[0].task_id,
                    "cells": 2,
                    "active_cells": 1,
                    "training_budget": 7,
                    "seed": 3,
                    "quality": 0.5,
                    "active_flops_g": 2.0,
                    "latency_us": 10.0,
                    "resident_memory_mb": 20.0,
                }
            )
        backend = JsonlStemBenchmarkBackend(rows)
        report = run_experiment(tasks, DEFAULT_VARIANTS, cells=2, training_budget=7, seed=3, backend=backend)
        self.assertEqual(report["benchmark_mode"], "external_observation")
        self.assertEqual(report["results"][0]["active_flops_per_request_g"], 2.0)
        self.assertEqual(report["results"][0]["resident_memory_mb"], 20.0)
        with self.assertRaises(ValidationError):
            run_experiment(tasks, DEFAULT_VARIANTS, cells=3, training_budget=7, seed=3, backend=backend)

    def test_duplicate_task_and_variant_ids_are_rejected(self):
        task = TaskCase("same", "family")
        with self.assertRaises(ValidationError):
            run_experiment((task, task), DEFAULT_VARIANTS)
        with self.assertRaises(ValidationError):
            run_experiment(default_tasks(2), (DEFAULT_VARIANTS[0], DEFAULT_VARIANTS[0]))

    def test_cli_output_is_new_json_artifact(self):
        import stem_selection_experiment as module

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            self.assertEqual(module.main(["--cells", "2", "--training-budget", "3", "--output", str(path)]), 0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["schema"], "hepta.experiment1-stem-selection.v1")
            with self.assertRaises(FileExistsError):
                module.main(["--output", str(path)])


if __name__ == "__main__":
    unittest.main()
