"""Behavioral checks for independent fits, budgets, freezing and failure retention."""

import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import strong_control as control
from study_data import FrozenRun, Plan, make_data
from study_model import LinearModel


class StrongControlTests(unittest.TestCase):
    def test_training_keeps_old_coordinates_and_uses_only_admitted_rows(self):
        plan = replace(Plan(), training_steps=2)
        data = make_data(plan, 101, plan.scenarios[0])
        frozen = FrozenRun.freeze(plan, data, "source")
        parent = LinearModel("shared", np.arange(6, dtype=np.float64))
        ledger = []
        result = control.fit_unsplit(parent, data["train"], frozen, plan, ledger, True)
        np.testing.assert_array_equal(result[:6], parent.weights)
        self.assertFalse(np.array_equal(result[6:], parent.weights))
        with self.assertRaisesRegex(ValueError, "held-out"):
            control.fit_unsplit(parent, data["test"], frozen, plan, [], True)

    def test_three_arms_train_independently_and_do_not_claim_positive_gain(self):
        plan = Plan()
        import study_model
        calls = []
        original = study_model.fit
        def recorded(*args, **kwargs):
            calls.append(args[-1])
            return original(*args, **kwargs)
        with patch.object(control, "fit", side_effect=recorded):
            result = control.run_trial(plan, 3, plan.scenarios[0], "source")
        self.assertEqual(calls, ["parent_pretrain", "new_slot_fit", "new_slot_fit"])
        self.assertEqual(result["decision"]["decision"], "HOLD")
        self.assertEqual(len({a["parameter_digest"] for a in result["arms"].values()}), 1)
        for arm in result["arms"].values():
            self.assertTrue(control.verify_training_cost(result, arm, plan))
            self.assertEqual(arm["budget"]["gradient_updates"], 257)
            self.assertEqual(arm["budget"]["training_presentations"], 49280)
        altered = copy.deepcopy(result)
        altered["arms"]["fixed_selective"]["ledger"][0]["requests"] -= 1
        self.assertIn("unmatched_budget:fixed_selective", control.adjudicate(altered, plan)["reasons"])
        del altered["arms"]["fixed_selective"]
        self.assertEqual(control.adjudicate(altered, plan)["reasons"], ["arm_denominator_changed"])

    def test_readback_rejects_dropped_requests_or_relabelled_metrics(self):
        from strong_control_audit import audit_trial
        plan = control.StrongPlan()
        result = control.run_trial(plan, 5, plan.scenarios[0], "source")
        self.assertEqual(audit_trial(result, plan, "source")["verified_requests"], 960)
        modified = copy.deepcopy(result)
        modified["arms"]["demand_split"]["observations"]["test"]["records"].pop()
        with self.assertRaisesRegex(ValueError, "denominator"):
            audit_trial(modified, plan, "source")
        modified = copy.deepcopy(result)
        modified["arms"]["demand_split"]["observations"]["test"]["summary"]["mse"] = 0
        with self.assertRaisesRegex(ValueError, "metric summary"):
            audit_trial(modified, plan, "source")

    def test_audit_failure_keeps_original_numerical_result(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocol.json"
            control.prepare(path)
            out = Path(tmp) / "run"
            numerical = {"status": "completed", "seed": 1, "scenario": "fixture",
                         "original_records": [0.125], "decision": {"decision": "HOLD"}}
            with patch.object(control, "run_trial", side_effect=lambda *args: copy.deepcopy(numerical)), patch(
                "strong_control_audit.audit_trial", side_effect=ValueError("injected audit failure")
            ):
                result = control.run(path, out)
            self.assertEqual(result["failed_trials"], 10)
            for raw in out.glob("RAW-*.json"):
                self.assertEqual(json.loads(raw.read_text()), numerical)
            self.assertTrue(all(json.loads(f.read_text())["original_records"] == [0.125]
                                for f in out.glob("*specialization-*.json")))

    def test_protocol_cannot_change_after_freeze_or_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocol.json"
            control.prepare(path)
            with self.assertRaises(FileExistsError):
                control.prepare(path)
            changed = control.protocol()
            changed["minimum_mse_gain"] = 0
            with self.assertRaisesRegex(ValueError, "frozen protocol"):
                control.verify_protocol(changed)

    def test_failure_preserves_all_trials_and_unknown_cost_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocol.json"
            control.prepare(path)
            out = Path(tmp) / "run"
            with patch.object(control, "run_trial", side_effect=RuntimeError("injected")) as execute:
                summary = control.run(path, out)
                self.assertEqual(execute.call_count, 10)
            self.assertEqual(summary["completed_trials"], 0)
            self.assertEqual(summary["failed_trials"], 10)
            self.assertEqual(summary["planned_test_predictions"], 5760)
            self.assertEqual(summary["completed_test_predictions"], 0)
            self.assertEqual(summary["decision"], "HOLD")
            self.assertEqual(len(list(out.glob("RAW-*specialization-*.json"))), 10)
            with self.assertRaises(FileExistsError):
                control.run(path, out)


if __name__ == "__main__":
    unittest.main()
