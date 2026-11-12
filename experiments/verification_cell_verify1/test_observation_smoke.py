"""Real SQLite observation order, retained hard gates and failure denominators."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import runtime
from .observation_smoke import ARMS, run


class ObservationSmokeTests(unittest.TestCase):
    def test_paid_information_precedes_prediction_and_never_replaces_acceptance(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = run(output)
            plan = json.loads((output / "PLAN.json").read_text())
            events = [
                json.loads(line)
                for line in (output / "events.jsonl").read_text().splitlines()
            ]
            diagnostics = json.loads((output / "DIAGNOSTICS.json").read_text())
            self.assertEqual(result["completed_trajectories"], len(plan["roster"]))
            self.assertEqual(result["missing_terminal_labels"], 0)
            self.assertEqual(result["actual_frequency_model_fits"], 1)
            self.assertGreater(result["actual_frequency_predictions"], 0)
            self.assertEqual(result["neural_model_inferences_executed"], 0)
            cohorts = result["information_before_fit"]["cohorts"]
            self.assertEqual(
                cohorts["train/ack"]["information"][
                    "empirical_probability_resolution_known"
                ],
                0,
            )
            self.assertGreater(
                cohorts["train/readback"]["information"][
                    "empirical_probability_resolution_known"
                ],
                0,
            )
            self.assertGreater(
                diagnostics["drift"]["shift/readback"]["brier_change"], 0
            )
            for view in ("ack", "readback"):
                train_identity = diagnostics["cohorts"]["train/" + view]["model_sha256"]
                cal_identity = diagnostics["cohorts"]["cal/" + view]["model_sha256"]
                self.assertNotEqual(train_identity, cal_identity)
            trajectories = {}
            for event in events:
                trajectories.setdefault(event["trajectory_id"], []).append(event)
            for stream in trajectories.values():
                kinds = [event["kind"] for event in stream]
                times = [event["available_monotonic_ns"] for event in stream]
                self.assertEqual(times, sorted(times))
                self.assertLess(
                    kinds.index("mandatory_terminal_check"),
                    kinds.index("terminal_label"),
                )
                if "frequency_prediction" in kinds:
                    self.assertLess(
                        kinds.index("partial_readback"),
                        kinds.index("frequency_prediction"),
                    )
                    self.assertLess(
                        kinds.index("frequency_prediction"),
                        kinds.index("terminal_label"),
                    )
                    snapshot = stream[kinds.index("frequency_prediction")]["value"][
                        "snapshot"
                    ]
                    self.assertEqual(len(snapshot["features"]), 3)
            for arm in ARMS:
                metrics = result["arms"][arm]
                self.assertEqual(
                    (
                        metrics["accepted_known_value_errors"],
                        metrics["rejected_known_clean_terminal_values"],
                    ),
                    (0, 0),
                )
                self.assertIsNone(metrics["causal_false_rejection_rate"])
                self.assertEqual(metrics["known_terminal_labels"], metrics["rows"])
                self.assertGreater(metrics["operations"]["mandatory_terminal_check"], 0)
            self.assertEqual(result["arms"]["no_optional_check"]["optional_checks"], 0)
            self.assertGreater(
                result["arms"]["risk_triggered"]["operations"]["partial_readback"], 0
            )
            self.assertGreater(
                result["arms"]["oracle_information"]["operations"][
                    "oracle_information_read"
                ],
                0,
            )

    def test_failure_keeps_unstarted_and_unknown_labels_without_replay(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "failed"
            with patch.object(
                runtime, "execute_step", side_effect=RuntimeError("observed fault")
            ) as effect:
                with self.assertRaisesRegex(RuntimeError, "observed fault"):
                    run(output)
            failure_bytes = (output / "FAILURE.json").read_bytes()
            failure = json.loads(failure_bytes)
            self.assertEqual(effect.call_count, 1)
            self.assertEqual(failure["completed_trajectories"], 0)
            self.assertEqual(len(failure["missing"]), failure["planned_trajectories"])
            self.assertEqual(
                {row["status"] for row in failure["missing"]},
                {"UNKNOWN", "NOT_STARTED"},
            )
            self.assertTrue(
                all(row["terminal_error"] is None for row in failure["missing"])
            )
            with self.assertRaises(FileExistsError):
                run(output)
            self.assertEqual((output / "FAILURE.json").read_bytes(), failure_bytes)

    def test_failed_label_read_keeps_already_observed_acceptance(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "label-failed"
            with patch.object(
                runtime, "outcome", side_effect=RuntimeError("label unavailable")
            ):
                with self.assertRaisesRegex(RuntimeError, "label unavailable"):
                    run(output)
            failure = json.loads((output / "FAILURE.json").read_text())
            self.assertEqual(failure["accepted_with_unknown_terminal_label"], 1)
            self.assertTrue(
                all(row["terminal_error"] is None for row in failure["missing"])
            )
            self.assertEqual(
                sum(row["accepted"] is True for row in failure["missing"]), 1
            )
