import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v3.capacity_study import run_capacity


class CapacityRunnerTests(unittest.TestCase):
    def test_saved_parameter_artifacts_are_read_in_fresh_process_without_pythonpath(
        self,
    ):
        protocol = {
            "capacity": {
                "numeric_domains": [],
                "include_digits": False,
                "synthetic_rows": 24,
                "synthetic_columns": 6,
                "cells": 4,
                "random_mix": [0.0],
                "budget_fractions_int32": [1.0],
                "max_vq_cells": 8,
                "hidden_query_limit": 32,
                "kmeans_iterations": 4,
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ):
                os.environ.pop("PYTHONPATH", None)
                summary = run_capacity(
                    protocol, Path(temporary), "test-unfrozen", [8011], development=True
                )
            self.assertEqual(len(summary["records"]), 5)
            global_result = next(
                r for r in summary["records"] if r["family"] == "global_svd"
            )
            self.assertEqual(global_result["hidden"]["exact_accuracy"], 1.0)
            self.assertEqual(global_result["hidden"]["queries"], 32)
            self.assertGreater(
                summary["actual_total_training_work"]["candidate_fits"], 0
            )
            self.assertGreater(
                summary["actual_encoder_work"]["strong_exact_baselines_seconds"], 0
            )
            for record in summary["records"]:
                self.assertLessEqual(record["artifact_bytes"], record["budget_bytes"])
                self.assertEqual(
                    record["selection"]["budget_bytes"], record["budget_bytes"]
                )
                self.assertGreater(
                    record["complete_parameter_read_bytes"], record["artifact_bytes"]
                )
                self.assertTrue(record["source_free_reload_verified"])


if __name__ == "__main__":
    unittest.main()
