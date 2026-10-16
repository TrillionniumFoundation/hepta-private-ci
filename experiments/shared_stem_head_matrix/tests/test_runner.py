import unittest

from experiments.shared_stem_head_matrix.runner import ARMS, ExperimentError, run


class HeadMatrixTests(unittest.TestCase):
    def test_all_heads_share_workload_and_report_costs(self):
        report = run(cells=4, active_cells=1, training_budget=100)
        self.assertEqual([row["arm_id"] for row in report["results"]], list(ARMS))
        self.assertTrue(all(row["active_cells"] == 1 for row in report["results"]))
        self.assertTrue(all("p95" in row["latency_us"] for row in report["results"]))
        self.assertFalse(report["production_accepted"])

    def test_external_observations_are_complete_and_bound(self):
        tasks = ("task-000",)
        rows = [{"arm_id": arm, "task_id": tasks[0], "cells": 2, "active_cells": 1, "training_budget": 3, "seed": 9, "utility": .5, "active_flops_g": 1., "latency_us": 2., "resident_memory_mb": 3.} for arm in ARMS]
        self.assertEqual(run(tasks=tasks, cells=2, active_cells=1, training_budget=3, seed=9, observations=rows)["benchmark_mode"], "external_observation")
        with self.assertRaises(ExperimentError):
            run(tasks=tasks, cells=3, active_cells=1, training_budget=3, seed=9, observations=rows)


if __name__ == "__main__":
    unittest.main()
