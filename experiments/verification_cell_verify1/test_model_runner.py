import json
from pathlib import Path
import tempfile
import unittest

from .model_protocol import ARMS, Journal, cases, frozen_plan
from .model_policy import Pilot
from .model_summary import control_acceptance, summarize
from .test_model_policy import UnitOnlyScore, dependencies


class SummaryTests(unittest.TestCase):
    def test_reject_everything_cannot_pass_positive_controls(self):
        planned = cases("confirmation")
        rows = [{"case_id": case["goal"]["task_id"], "arm": arm, "status": "completed",
                 "accepted": case["fault"] in ("clean", "missing_receipt"),
                 "outcome_error": case["fault"] not in ("clean", "missing_receipt")}
                for case in planned for arm in ARMS]
        self.assertTrue(all(all(gate.values()) for gate in control_acceptance(rows, planned).values()))
        for row in rows:
            row["accepted"] = False
        rejected = control_acceptance(rows, planned)
        self.assertTrue(all(not gate["positive_controls_accepted"] for gate in rejected.values()))
        self.assertTrue(all(gate["known_wrong_controls_rejected"] for gate in rejected.values()))

    def test_failed_inference_and_not_run_case_stay_in_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = frozen_plan()
            selected = cases("confirmation")[:2]
            plan["planned_trajectories"] = [{"case_id": case["goal"]["task_id"], "arm": "single"} for case in selected]
            journal = Journal(Path(temporary) / "pilot", plan)
            pilot = Pilot(journal, dependencies(), UnitOnlyScore(fail=True), plan)
            with self.assertRaises(RuntimeError):
                pilot.trajectory(selected[0], "single")
            result = summarize(journal.directory, {"type": "RuntimeError"}, 1, 1)
            arm = result["arms"]["single"]
            self.assertEqual((arm["planned"], arm["attempted"], arm["failed"], arm["not_run"], arm["missing_initial_scores"]), (2, 1, 1, 1, 2))
            self.assertIsNone(arm["actual_policy_accepted"]["known_error_rate"])
            self.assertEqual(result["status"], "INCOMPLETE_OR_FAILED")

    def test_acceptance_needs_actual_effect_and_host_readback_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = frozen_plan()
            case = next(case for case in cases("confirmation") if case["fault"] == "clean")
            plan["planned_trajectories"] = [{"case_id": case["goal"]["task_id"], "arm": "single"}]
            journal = Journal(Path(temporary) / "pilot", plan)
            Pilot(journal, dependencies(), UnitOnlyScore(), plan).trajectory(case, "single")
            self.assertTrue(summarize(journal.directory, None, 1, 1)["engineering_gates"]["host_effect_label_and_acceptance_provenance"])
            path = journal.directory / "operations.jsonl"
            operations = [json.loads(line) for line in path.read_text().splitlines()]
            operations = [row for row in operations if not (row["kind"] == "host_effect" and row["context"]["tick"] == 2)]
            path.write_text("\n".join(json.dumps(row) for row in operations) + "\n")
            self.assertFalse(summarize(journal.directory, None, 1, 1)["engineering_gates"]["host_effect_label_and_acceptance_provenance"])


if __name__ == "__main__":
    unittest.main()
