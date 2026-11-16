"""Failure retention and the final-label boundary of the scientific runner."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_control import build_reference, fit_controller, run_nonlinear
from cell_field_run import _condition
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class RunnerBoundaryTests(unittest.TestCase):
    def test_finite_trajectory_with_overflowed_cost_is_retained_as_failed(self):
        features = np.random.default_rng(4).normal(size=(12, 2))
        labels = np.arange(12, dtype=np.int64) % 2
        state = CellTrainingState(NumpyCellHead(2, 2), bindings={"fixture": "runner-failure"},
                                 contexts={"train": dataset_digest(features, labels)})
        for _ in range(5):
            state.advance(features, labels)
        reference = build_reference(state, features, labels,
                                    ((features, labels), (features, labels)), horizon=2)
        target = np.zeros((3, 2))
        controller = fit_controller(reference, mask="bias", mode="zero", target=target)
        oracle = fit_controller(reference, mask="bias", mode="full", target=target)

        def overflowing_cost(*args):
            result = run_nonlinear(*args)
            result["cost"]["total"] = float("inf")
            return result

        with tempfile.TemporaryDirectory() as temporary, patch("cell_field_run.run_nonlinear", overflowing_cost):
            record, probability = _condition(Path(temporary), "fixture", 0, state,
                reference, controller, oracle, features, {"feature": "frozen-fixture"})
            self.assertEqual(record["status"], "failed")
            self.assertTrue(np.isnan(probability).all())
            self.assertNotIn("cost", record)
            self.assertTrue((Path(temporary) / record["paths"]["trajectory"]).is_file())
            self.assertTrue((Path(temporary) / "failures/fixture-bias-zero.json").is_file())

    def test_final_label_open_is_blocked_in_the_training_process(self):
        program = """
import sys, tempfile
from pathlib import Path
from cell_field_run import _deny_final_labels
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'final_labels.json'
    path.write_text('{"not_loaded": true}')
    sys.addaudithook(_deny_final_labels)
    try:
        path.read_bytes()
    except PermissionError:
        print('blocked-before-read')
    else:
        raise RuntimeError('final labels were accessible')
"""
        result = subprocess.run([sys.executable, "-c", program], cwd=Path(__file__).parent,
                                text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), "blocked-before-read")


if __name__ == "__main__":
    unittest.main()
