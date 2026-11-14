"""End-to-end fixture checks plus explicit failure and denominator regressions."""

import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from . import contracts as c
from . import experiment as e


class ExperimentTests(unittest.TestCase):
    def test_nested_meters_retain_unique_ids_and_interruption_status(self):
        for error, status in (
            (KeyboardInterrupt(), "cancelled"),
            (SystemExit(9), "failed"),
        ):
            with (
                self.subTest(exception=type(error).__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                recorder = e.Recorder(Path(temporary))
                with self.assertRaises(type(error)) as raised:
                    with recorder.meter("trajectory", "test:arm", "outer"):
                        with recorder.meter("trajectory", "test:arm", "inner"):
                            raise error
                self.assertIs(raised.exception, error)
                self.assertEqual(
                    len({row["operation_id"] for row in recorder.costs}), 2
                )
                self.assertEqual(
                    [(row["kind"], row["status"]) for row in recorder.costs],
                    [("inner", status), ("outer", status)],
                )
                self.assertEqual(
                    e.records(Path(temporary) / "costs.jsonl"), recorder.costs
                )
                self.assertEqual(
                    e.metrics.summarize_costs(recorder.costs)["totals"][
                        "status_counts"
                    ],
                    {status: 2},
                )

    def test_actual_run_freezes_splits_and_fails_closed_on_false_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            result = e.run(output, groups=1)
            self.assertEqual(result["status"], "ENGINEERING_SMOKE_PASS")
            self.assertTrue(all(result["engineering_gates"].values()))
            self.assertEqual(
                (
                    result["planned_attempt_rows"],
                    result["observed_attempt_rows"],
                    result["planned_confirmation_rows"],
                    result["observed_confirmation_rows"],
                ),
                (48, 48, 24, 24),
            )
            plan = json.loads((output / "plan.json").read_text())
            values = [
                {(item["goal"]["left"], item["goal"]["right"]) for item in plan[phase]}
                for phase in ("training", "calibration", "confirmation")
            ]
            self.assertTrue(
                all(
                    not values[left] & values[right]
                    for left, right in ((0, 1), (0, 2), (1, 2))
                )
            )
            calibration = c.parse_record((output / "calibration.json").read_text())
            panel = json.loads((output / "calibration-data.json").read_text())
            self.assertEqual(calibration.data_sha256, c.digest(panel))
            calibration_ids = {case["goal"]["task_id"] for case in plan["calibration"]}
            predictions = [
                c.parse_record(line)
                for line in (output / "predictions.jsonl").read_text().splitlines()
            ]
            self.assertTrue(
                all(
                    record.model == calibration.model
                    for record in predictions
                    if record.scope.task_id in calibration_ids
                )
            )
            costs = e.records(output / "costs.jsonl")
            self.assertEqual(
                {row["arm"].split(":", 1)[0] for row in costs},
                {"train", "calibration", "confirmation"},
            )
            rows = e.records(output / "rows.jsonl")
            history = json.loads((output / "history-model.json").read_text())
            self.assertEqual(
                {
                    row["risk"]
                    for row in rows
                    if row["source_group"].startswith("confirmation/")
                },
                {e.probability(history, [])},
            )
            recorder = e.Recorder(output)
            recorder.costs = costs

            def finish(candidate_rows):
                return e.finish(
                    output,
                    plan,
                    recorder,
                    candidate_rows,
                    [],
                    time.perf_counter_ns(),
                    history,
                    result["frozen_history_model_sha256"],
                )

            all_rejected = finish([{**row, "accepted": False} for row in rows])
            self.assertEqual(all_rejected["status"], "ENGINEERING_SMOKE_FAILED")
            self.assertFalse(
                all_rejected["engineering_gates"][
                    "correct_and_reconciled_trajectories_accepted"
                ]
            )
            omitted = finish(rows[:-1])
            self.assertFalse(omitted["engineering_gates"]["exact_attempt_roster"])
            self.assertEqual(len(omitted["unstarted_planned_attempts"]), 1)
            with patch.object(e, "source_manifest", return_value={}):
                self.assertFalse(finish(rows)["engineering_gates"]["source_unchanged"])
            with patch.object(e, "records", return_value=[]):
                self.assertFalse(
                    finish(rows)["engineering_gates"]["effect_calls_have_log_and_meter"]
                )

    def test_failure_halting_preserves_planned_and_unstarted_denominators(self):
        actual_run = subprocess.run
        for phase, observed, unstarted in (("train", 12, 36), ("calibration", 24, 24)):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "run"

                def worker(command, **kwargs):
                    goal = json.loads(command[command.index("--goal") + 1])
                    selected = (
                        goal["left"] < 10000
                        if phase == "train"
                        else 10000 <= goal["left"] < 20000
                    )
                    if selected:
                        return subprocess.CompletedProcess(
                            command, 17, b"partial\xff", b"failed worker"
                        )
                    return actual_run(command, **kwargs)

                with patch.object(e.subprocess, "run", side_effect=worker):
                    result = e.run(output, groups=1)
                self.assertEqual(
                    (result["status"], result["halted_phase"]),
                    ("ENGINEERING_SMOKE_HALTED", phase),
                )
                self.assertEqual(
                    (
                        result["observed_attempt_rows"],
                        result["observed_confirmation_rows"],
                        len(result["unstarted_planned_attempts"]),
                    ),
                    (observed, 0, unstarted),
                )
                self.assertEqual(
                    json.loads((output / "result.json").read_text()), result
                )
                self.assertEqual(len(result["failed_attempts"]), 12)
                effects = e.records(output / "effects.jsonl")
                failed = [row for row in effects if row["status"] == "failed"]
                self.assertEqual(len(failed), 12)
                self.assertEqual(
                    base64.b64decode(failed[0]["stdout_base64"]), b"partial\xff"
                )
                self.assertTrue(
                    all(
                        row["outcome_error"] is None
                        for row in e.records(output / "rows.jsonl")
                        if row["source_group"].startswith(phase + "/")
                    )
                )

    def test_timeout_retains_unknown_label_partial_bytes_and_single_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = e.Recorder(Path(temporary))
            case = e.cases("confirmation", 1)[0]
            timeout = subprocess.TimeoutExpired(
                "fixture", 20, output=b"partial\xfe", stderr=b"waiting"
            )
            with patch.object(e.subprocess, "run", side_effect=timeout) as worker:
                row, _, failure = e.run_one(recorder, case, "fixed_check_time", {})
            self.assertEqual(worker.call_count, 1)
            self.assertEqual(
                (row["accepted"], row["outcome_error"], failure["type"]),
                (False, None, "TimeoutExpired"),
            )
            effects = e.records(Path(temporary) / "effects.jsonl")
            self.assertEqual(
                (effects[0]["returncode"], effects[0]["status"]), (None, "timed_out")
            )
            self.assertEqual(
                base64.b64decode(effects[0]["stdout_base64"]), b"partial\xfe"
            )
            self.assertEqual(
                [
                    record["status"]
                    for record in e.records(Path(temporary) / "attempts.jsonl")
                ],
                ["started", "failed"],
            )
            self.assertEqual(
                [
                    record["status"]
                    for record in recorder.costs
                    if record["kind"] == "effect_subprocess"
                ],
                ["failed"],
            )

    def test_risk_and_selector_ignore_oracle_fields(self):
        history = {"ack_present": (20, 8), "missing_ack": (4, 1)}
        innocent = [{"ack": True, "fault": "clean", "outcome_error": False}]
        poisoned = [{"ack": True, "fault": "semantic_error", "outcome_error": True}]
        risk = e.probability(history, innocent)
        self.assertEqual(risk, e.probability(history, poisoned))
        for arm in e.ARMS:
            self.assertEqual(
                e.check_selected(arm, risk, innocent, 2, 0.6),
                e.check_selected(arm, risk, poisoned, 2, 0.6),
            )
        intervention = e.intervention_report(history)
        self.assertEqual(
            [row["selection"] for row in intervention["rows"]],
            ["defer", "check", "check", "defer"],
        )
        self.assertEqual(intervention["mandatory_budget_shortfall"], "blocked")


if __name__ == "__main__":
    unittest.main()
