"""Failure accounting with explicit predictors and an actual cold process exit."""

import copy
import subprocess
import sys
import unittest
from unittest.mock import patch

from cell_experiments import adoption as a
from cell_experiments import test_adoption as fixtures
from cell_experiments.test_data import record


class AdoptionCostTests(unittest.TestCase):
    setUp = fixtures.AdoptionTests.setUp
    child = fixtures.AdoptionTests.child

    def add_task(self, phase, number):
        task = record(number, "confirmation")
        metadata = {key: task[key] for key in ("task_id", "source_id")}
        metadata["task_digest"] = a.digest(task)
        self.request["plan"].setdefault(phase, []).append(metadata)
        self.request.setdefault(phase, []).append(dict(**metadata, record=task))
        for name in ("training", "evaluation"):
            self.request[name]["plan_digest"] = a.digest(self.request["plan"])

    def test_failed_hot_call_keeps_previous_cost_and_unknown_remainder(self):
        self.add_task("c_tasks", 4)

        class Failing(fixtures.Predictor):
            def predict(self, task):
                if task["task_id"] == "task-4":
                    raise RuntimeError("injected model failure after dispatch")
                return super().predict(task)

        with patch.object(a, "load_predictor", side_effect=lambda m, r: Failing(m)):
            result = a.execute(self.request, self.root / "hot-failure")
        self.assertEqual(result["status"], "FAILED", result)
        phase = result["execution_costs"]["phases"]["hot_C"]
        self.assertEqual(phase["dispatch_intents"], 2)
        self.assertEqual(phase["observed_complete_predictions"], 1)
        self.assertEqual(phase["unmeasured_dispatch_intents"], 1)
        self.assertIsNone(phase["model_calls"])
        self.assertIsNone(phase["input_tokens"])
        self.assertEqual(phase["observed_complete_prediction_costs"]["input_tokens"], 7)
        self.assertIsNone(
            result["execution_costs"]["phases"]["cold_C_replay"]["model_calls"]
        )

    def test_verifier_failure_still_charges_returned_prediction(self):
        with (
            patch.object(
                a, "load_predictor", side_effect=lambda m, r: fixtures.Predictor(m)
            ),
            patch(
                "cell_experiments.data.verify_answer",
                side_effect=RuntimeError("verifier failed"),
            ),
        ):
            result = a.execute(self.request, self.root / "verifier-failure")
        self.assertEqual(result["status"], "FAILED", result)
        self.assertEqual(result["C"], [])
        phase = result["execution_costs"]["phases"]["hot_C"]
        self.assertEqual(
            (phase["model_calls"], phase["input_tokens"], phase["output_tokens"]),
            (1, 7, 5),
        )

    def test_cold_hard_exit_retains_replay_and_partial_d_costs(self):
        self.add_task("d_tasks", 4)
        self.add_task("d_tasks", 5)
        run = subprocess.run
        code = """
import os, sys
from unittest.mock import patch
from cell_experiments import adoption as a
from cell_experiments.test_adoption import Predictor
class Exiting(Predictor):
    def predict(self, task):
        if task['task_id'] == 'task-5':
            os._exit(9)
        return super().predict(task)
with patch.object(a, 'load_predictor', side_effect=lambda m, r: Exiting(m)):
    a.recover(a.read_json(sys.argv[1]), sys.argv[2])
"""
        output = self.root / "cold-exit"
        with (
            patch.object(
                a, "load_predictor", side_effect=lambda m, r: fixtures.Predictor(m)
            ),
            patch.object(
                a.subprocess,
                "run",
                side_effect=lambda command, **kw: run(
                    [sys.executable, "-c", code, command[4], command[6]], **kw
                ),
            ),
        ):
            result = a.execute(self.request, output)
        self.assertEqual(result["status"], "FAILED", result)
        self.assertEqual(a.read_json(output / "COLD_PROCESS.json")["returncode"], 9)
        phases = result["execution_costs"]["phases"]
        self.assertEqual(phases["hot_C"]["model_calls"], 1)
        self.assertEqual(phases["cold_C_replay"]["model_calls"], 1)
        self.assertEqual(phases["cold_D"]["dispatch_intents"], 2)
        self.assertEqual(phases["cold_D"]["observed_complete_predictions"], 1)
        self.assertEqual(
            phases["cold_D"]["observed_complete_prediction_costs"]["input_tokens"], 7
        )
        self.assertIsNone(phases["cold_D"]["input_tokens"])
        self.assertEqual(
            result["inference_attempts"]["cold_D"][-1]["status"], "DISPATCH_INTENT"
        )
        retained = copy.deepcopy(result)
        with patch.object(a, "load_predictor") as loader:
            self.assertEqual(a.execute(self.request, output)["status"], "INCOMPLETE")
        loader.assert_not_called()
        self.assertEqual(a.read_json(output / "RESULT.json"), retained)

    def test_completed_readback_requires_original_inference_streams(self):
        output = self.root / "readback"
        with (
            patch.object(
                a, "load_predictor", side_effect=lambda m, r: fixtures.Predictor(m)
            ),
            patch.object(a.subprocess, "run", side_effect=self.child),
        ):
            result = a.execute(self.request, output)
        self.assertEqual(result["status"], "ADOPTED", result)
        (output / "C_INFERENCE.json").unlink()
        with patch.object(a, "load_predictor") as loader:
            self.assertEqual(a.execute(self.request, output)["status"], "INCOMPLETE")
        loader.assert_not_called()
        self.assertEqual(a.read_json(output / "RESULT.json"), result)


if __name__ == "__main__":
    unittest.main()
