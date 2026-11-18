"""Recovery counterexamples use explicit model fixtures, never research evidence."""

import copy
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch

from cell_experiments import adoption as a
from cell_experiments import test_adoption as fixtures


class AdoptionRecoveryTests(unittest.TestCase):
    setUp = fixtures.AdoptionTests.setUp
    child = fixtures.AdoptionTests.child

    def execute_fixture(self, request, output):
        with (
            patch.object(
                a, "load_predictor", side_effect=lambda m, r: fixtures.Predictor(m)
            ),
            patch.object(a.subprocess, "run", side_effect=self.child),
        ):
            return a.execute(request, output)

    def test_lost_store_or_selected_row_never_repeats_c(self):
        for fault in ("database", "table", "row"):
            with self.subTest(fault=fault):
                output = self.root / fault
                result = self.execute_fixture(self.request, output)
                self.assertEqual(result["status"], "ADOPTED", result)
                original = (output / "RESULT.json").read_bytes()
                if fault == "database":
                    (output / "selection.sqlite").unlink()
                else:
                    with (
                        closing(sqlite3.connect(output / "selection.sqlite")) as db,
                        db,
                    ):
                        db.execute(
                            "DROP TABLE selections"
                            if fault == "table"
                            else "DELETE FROM selections"
                        )
                with patch.object(a, "load_predictor") as loader:
                    retry = a.execute(self.request, output)
                loader.assert_not_called()
                self.assertIn(retry["status"], ("FAILED", "INCOMPLETE"), retry)
                self.assertEqual((output / "RESULT.json").read_bytes(), original)

    def test_another_operation_cannot_reuse_output_or_overwrite_originals(self):
        output = self.root / "one-owner"
        self.assertEqual(
            self.execute_fixture(self.request, output)["status"], "ADOPTED"
        )
        originals = {p.name: p.read_bytes() for p in output.glob("*.json")}
        request = copy.deepcopy(self.request)
        request["plan"]["operation_id"] = "different-operation"
        for name in ("training", "evaluation"):
            request[name]["plan_digest"] = a.digest(request["plan"])
        with patch.object(a, "load_predictor") as loader:
            result = a.execute(request, output)
        loader.assert_not_called()
        self.assertEqual(result["status"], "FAILED", result)
        self.assertEqual(
            {name: (output / name).read_bytes() for name in originals}, originals
        )

    def test_caller_mutation_cannot_change_frozen_c_or_cold_input(self):
        output = self.root / "mutation"
        before = copy.deepcopy(self.request)
        seen = []

        class MutableCaller(fixtures.Predictor):
            def predict(inner, task):
                seen.append(copy.deepcopy(task))
                self.request["c_tasks"][0]["record"]["task"]["input"] = (
                    "changed after selection"
                )
                return super().predict(task)

        with (
            patch.object(
                a, "load_predictor", side_effect=lambda m, r: MutableCaller(m)
            ),
            patch.object(a.subprocess, "run", side_effect=self.child),
        ):
            result = a.execute(self.request, output)
        self.assertEqual(result["status"], "ADOPTED", result)
        self.assertEqual(seen, [before["c_tasks"][0]["record"]] * 2)
        self.assertEqual(a.read_json(output / "REQUEST.json"), before)

    def test_changed_terminal_receipts_cannot_be_replayed_as_success(self):
        for fault in (
            "result",
            "c_receipts",
            "request",
            "stored_report",
            "cold_stderr",
        ):
            with self.subTest(fault=fault):
                output = self.root / fault
                self.assertEqual(
                    self.execute_fixture(self.request, output)["status"], "ADOPTED"
                )
                if fault == "stored_report":
                    with (
                        closing(sqlite3.connect(output / "selection.sqlite")) as db,
                        db,
                    ):
                        old = json.loads(
                            db.execute("SELECT report FROM selections").fetchone()[0]
                        )
                        old["selected_model_digest"] = "0" * 64
                        db.execute("UPDATE selections SET report=?", (json.dumps(old),))
                elif fault == "cold_stderr":
                    path = output / "COLD_PROCESS.json"
                    process = a.read_json(path)
                    process["stderr"] += "changed retained diagnostics"
                    a.save(path, process)
                elif fault == "request":
                    (output / "REQUEST.json").unlink()
                else:
                    path = output / (
                        "RESULT.json" if fault == "result" else "C_RECEIPTS.json"
                    )
                    value = a.read_json(path)
                    if fault == "result":
                        value["selected_model_digest"] = "0" * 64
                    else:
                        value[0]["outcome"]["success"] = False
                    a.save(path, value)
                original = (output / "RESULT.json").read_bytes()
                with patch.object(a, "load_predictor") as loader:
                    result = a.execute(self.request, output)
                loader.assert_not_called()
                self.assertIn(result["status"], ("FAILED", "INCOMPLETE"), result)
                self.assertEqual((output / "RESULT.json").read_bytes(), original)

    def test_invalid_cold_budget_is_rejected_before_any_c_execution(self):
        request = copy.deepcopy(self.request)
        request["plan"]["cold_timeout_seconds"] = 0
        for name in ("training", "evaluation"):
            request[name]["plan_digest"] = a.digest(request["plan"])
        with patch.object(a, "load_predictor") as loader:
            result = a.execute(request, self.root / "invalid-budget")
        loader.assert_not_called()
        self.assertEqual(result["status"], "FAILED", result)
        self.assertIsNone(result["model_decision"])

    def test_missing_or_changed_cold_and_selection_originals_refuse_completion(self):
        for name in ("DECISION.json", "COLD_REQUEST.json", "COLD_PROCESS.json"):
            for fault in ("missing", "changed"):
                with self.subTest(name=name, fault=fault):
                    output = self.root / (name + fault)
                    self.assertEqual(
                        self.execute_fixture(self.request, output)["status"], "ADOPTED"
                    )
                    original = (output / "RESULT.json").read_bytes()
                    path = output / name
                    if fault == "missing":
                        path.unlink()
                    else:
                        a.save(path, {})
                    with patch.object(a, "load_predictor") as loader:
                        result = a.execute(self.request, output)
                    loader.assert_not_called()
                    self.assertEqual(
                        result["status"],
                        "INCOMPLETE" if fault == "missing" else "FAILED",
                    )
                    self.assertEqual((output / "RESULT.json").read_bytes(), original)

    def test_original_legacy_completion_is_read_only(self):
        output = self.root / "legacy"
        original = self.execute_fixture(self.request, output)
        (output / "ADMISSION.json").unlink()
        before = {p.name: p.read_bytes() for p in output.glob("*.json")}
        with patch.object(a, "load_predictor") as loader:
            self.assertEqual(a.execute(self.request, output), original)
        loader.assert_not_called()
        self.assertEqual(
            {p.name: p.read_bytes() for p in output.glob("*.json")}, before
        )


if __name__ == "__main__":
    unittest.main()
