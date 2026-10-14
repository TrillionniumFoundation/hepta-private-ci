"""Durable failure boundaries and planned-denominator menu diagnostics."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


from system2_budget_audit import menu_report
from system2_budget_control import (
    ARMS,
    LIMITS,
    collect_training,
    episode,
    make_head,
    training_census,
)
from system2_budget_trial import journal, run
from system2_verified_search import ExactLabels, digest
from test_system2_budget_control import Fixed, PROOF, simulated_search


def fixture_rows():
    numbers = (1, 2, 3, 4)
    head = Fixed([20.0, -20.0, 0.0, 0.0])
    with patch("system2_budget_control.search", side_effect=simulated_search):
        rows = [
            episode(numbers, budget, arm, None, head)
            for budget in LIMITS
            for arm in ARMS
        ]
    for row in rows:
        row.update(group="fixture", query_id=digest(numbers))
    return rows, {"fixture": [numbers]}


class TrainingEvidenceTests(unittest.TestCase):
    def test_success_preserves_training_targets_and_counts_all_counterfactual_work(
        self,
    ):
        rows, events = [], []
        with patch("system2_budget_control.search", side_effect=simulated_search):
            x, y, actual = collect_training(
                [(1, 2, 3, 4), (1, 1, 1, 1)],
                None,
                ledger=rows,
                event_sink=events.append,
            )
        self.assertIs(rows, actual)
        self.assertEqual(x.shape, (4, 15))
        self.assertEqual(
            y[:, :2].tolist(), [[0.0, 1.0], [0.0, 1.0], [0.0, 0.0], [0.0, 0.0]]
        )
        report = training_census(rows, [(1, 2, 3, 4), (1, 1, 1, 1)])
        self.assertEqual(report["completed_child_calls"], 12)
        self.assertFalse(report["work_may_be_missing"])
        self.assertEqual(sum(e["phase"] == "child_started" for e in events), 12)
        self.assertEqual(sum(e["phase"] == "child_completed" for e in events), 12)

    def test_second_tail_failure_retains_prior_work_without_returning_targets(self):
        rows, events = [], []

        def fail(*args, **kwargs):
            if args[2] == "value_search":
                raise RuntimeError("second tail failed")
            return simulated_search(*args, **kwargs)

        with patch("system2_budget_control.search", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "second tail failed"):
                collect_training(
                    [(1, 2, 3, 4)], None, ledger=rows, event_sink=events.append
                )
        self.assertEqual(
            [e["status"] for e in rows[0]["executions"]],
            ["completed", "completed", "failed"],
        )
        self.assertNotIn("target", rows[0])
        report = training_census(rows, [(1, 2, 3, 4)])
        self.assertEqual(
            report["known_completed_child_costs"]["generated_successors"], 256
        )
        self.assertEqual(report["not_started_contexts"], 1)
        self.assertTrue(report["work_may_be_missing"])
        self.assertEqual(events[-1]["phase"], "context_failed")

    def test_runner_finally_writes_partial_ledger_and_no_fitted_model(self):
        child = make_head().eval().requires_grad_(False)

        def fail(*args, **kwargs):
            if args[2] == "value_search":
                raise RuntimeError("tail failure")
            return simulated_search(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            with (
                patch(
                    "system2_budget_trial.read_parent",
                    return_value=({}, {"value": child}, [], {}),
                ),
                patch(
                    "system2_budget_trial.cohort",
                    return_value=([(1, 2, 3, 4)], {"fixture": [(1, 1, 1, 1)]}),
                ),
                patch("system2_budget_control.search", side_effect=fail),
            ):
                with self.assertRaises(RuntimeError):
                    run(Path("fixture.zip"), output, source_commit="a" * 40)
            stored = json.loads((output / "training-rollouts.json").read_text())
            self.assertEqual(stored[0]["status"], "failed")
            self.assertTrue(
                json.loads((output / "training-census.json").read_text())[
                    "work_may_be_missing"
                ]
            )
            events = [
                json.loads(line)
                for line in (output / "training-events.jsonl").read_text().splitlines()
            ]
            self.assertEqual([e["phase"] for e in events].count("child_completed"), 2)
            self.assertFalse((output / "freeze.json").exists())
            self.assertFalse((output / "training-examples.json").exists())

    def test_interrupt_is_retained_then_reraised(self):
        rows = []
        with patch("system2_budget_control.search", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                collect_training([(1, 2, 3, 4)], None, ledger=rows)
        self.assertEqual(rows[0]["executions"][0]["error_type"], "KeyboardInterrupt")
        self.assertTrue(training_census(rows, [(1, 2, 3, 4)])["work_may_be_missing"])

    def test_logging_failure_prevents_unjournaled_child(self):
        def unavailable(_):
            raise OSError("journal unavailable")

        with patch("system2_budget_control.search") as call:
            with self.assertRaises(OSError):
                collect_training([(1, 2, 3, 4)], None, event_sink=unavailable)
        call.assert_not_called()

    def test_snapshot_callback_cannot_mutate_live_child_receipt(self):
        def mutate(event):
            if "execution" in event:
                event["execution"].clear()

        with patch("system2_budget_control.search", side_effect=simulated_search):
            _, _, rows = collect_training([(1, 2, 3, 4)], None, event_sink=mutate)
        self.assertTrue(
            all(e["status"] == "completed" for row in rows for e in row["executions"])
        )

    def test_successful_probes_still_record_when_no_training_examples(self):
        def success(*args, **kwargs):
            r = simulated_search(*args, **kwargs)
            r.update(found=True, proof=PROOF)
            return r

        rows = []
        with patch("system2_budget_control.search", side_effect=success):
            with self.assertRaisesRegex(ValueError, "no observed"):
                collect_training([(1, 2, 3, 4)], None, ledger=rows)
        report = training_census(rows, [(1, 2, 3, 4)])
        self.assertEqual(
            (report["completed_contexts"], report["usable_targets"]), (2, 0)
        )
        self.assertFalse(report["work_may_be_missing"])

    def test_all_tasks_admitted_before_execution(self):
        with patch("system2_budget_control.search") as call:
            with self.assertRaises(ValueError):
                collect_training([(1, 2, 3, 4), (0, 2, 3, 4)], None)
        call.assert_not_called()
        with self.assertRaises(ValueError):
            collect_training([(1, 2, 3, 4)], None, ledger=[{}])

    def test_file_journal_orders_start_before_child_and_preserves_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"

            def checked(*args, **kwargs):
                last = json.loads(path.read_text().splitlines()[-1])
                self.assertEqual(last["phase"], "child_started")
                return simulated_search(*args, **kwargs)

            with patch("system2_budget_control.search", side_effect=checked):
                collect_training(
                    [(1, 2, 3, 4)], None, event_sink=lambda e: journal(path, e)
                )
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertTrue(
                all(
                    e["execution"]["status"] == "started"
                    for e in events
                    if e["phase"] == "child_started"
                )
            )


class MenuEvidenceTests(unittest.TestCase):
    def test_perfect_menu_value_is_not_online_oracle(self):
        rows, groups = fixture_rows()
        before = deepcopy(rows)
        with (
            patch.object(ExactLabels, "_solve", side_effect=AssertionError("oracle")),
            patch(
                "system2_verified_search.search",
                side_effect=AssertionError("new search"),
            ),
        ):
            report = menu_report(rows, groups)
        self.assertEqual(rows, before)
        self.assertEqual(report["new_model_calls"], 0)
        self.assertTrue(report["perfect_information_not_online_policy"])
        self.assertGreater(report["groups"][0]["mean_selector_regret_bounds"][0], 0.0)

    def test_missing_action_keeps_every_planned_question_and_unknown_bounds(self):
        rows, groups = fixture_rows()
        rows = [
            r for r in rows if not (r["arm"] == "probe_value" and r["budget"] == 256)
        ]
        report = menu_report(rows, groups)
        self.assertEqual(report["planned_predictions"], 16)
        self.assertEqual(report["missing_predictions"], 1)
        entry = report["groups"][0]
        self.assertEqual(entry["menu_proofs_bounds"], [0, 1])
        self.assertEqual(entry["questions_with_unknown_arms"], 1)
        self.assertLess(
            entry["mean_menu_utility_bounds"][0], entry["mean_menu_utility_bounds"][1]
        )

    def test_failed_action_is_unknown_not_negative(self):
        rows, groups = fixture_rows()
        row = next(r for r in rows if r["arm"] == "probe_value" and r["budget"] == 256)
        row.update(status="failed", utility=None)
        report = menu_report(rows, groups)
        self.assertEqual(report["failed_predictions"], 1)
        self.assertEqual(report["groups"][0]["menu_proofs_bounds"], [0, 1])

    def test_no_records_still_preserves_plan(self):
        _, groups = fixture_rows()
        report = menu_report([], groups)
        self.assertEqual(report["missing_predictions"], 16)
        self.assertEqual(len(report["groups"]), 2)
        self.assertTrue(
            all(r["menu_proofs_bounds"] == [0, 1] for r in report["groups"])
        )

    def test_duplicate_wrong_identity_and_false_proof_rejected(self):
        rows, groups = fixture_rows()
        wrong = deepcopy(rows)
        wrong[0]["numbers"] = [1, 1, 1, 1]
        forged = deepcopy(rows)
        positive = next(r for r in forged if r["found"])
        positive["proof"] = ["n0"] * 7
        for bad in (rows + rows[:1], wrong, forged):
            with self.assertRaises(ValueError):
                menu_report(bad, groups)

    def test_forged_utility_or_child_cost_rejected(self):
        rows, groups = fixture_rows()
        changed = deepcopy(rows)
        changed[0]["utility"] += 0.01
        bad_cost = deepcopy(rows)
        bad_cost[0]["executions"][0]["result"]["costs"]["popped_states"] += 1
        for bad in (changed, bad_cost):
            with self.assertRaises(ValueError):
                menu_report(bad, groups)

    def test_same_probe_required_for_counterfactual_comparison(self):
        rows, groups = fixture_rows()
        row = next(r for r in rows if r["arm"] == "probe_value")
        row["executions"][0]["successor_limit"] += 1
        with self.assertRaisesRegex(ValueError, "same probe"):
            menu_report(rows, groups)

    def test_selected_action_must_match_its_observed_control(self):
        rows, groups = fixture_rows()
        row = next(r for r in rows if r["arm"] == "learned")
        row["decision"]["action"] = "value_search"
        with self.assertRaisesRegex(ValueError, "paired control"):
            menu_report(rows, groups)

    def test_failed_known_budget_violation_cannot_receive_registered_bounds(self):
        rows, groups = fixture_rows()
        rows[0].update(status="failed", utility=None)
        rows[0]["costs"]["generated_successors"] = 1025
        with self.assertRaisesRegex(ValueError, "assumed successor cap"):
            menu_report(rows, groups)

    def test_structural_loss_and_selector_gap_are_different(self):
        rows, groups = fixture_rows()
        # Remove all proof opportunities from the menu; leave a valid direct proof.
        for row in rows:
            if row["arm"] == "direct_heuristic":
                row.update(
                    found=True,
                    proof=PROOF,
                    utility=1 - 0.0001 * row["costs"]["generated_successors"],
                )
                row["executions"][-1]["result"].update(found=True, proof=PROOF)
            elif row["arm"] == "probe_value":
                row.update(
                    found=False,
                    proof=None,
                    utility=-0.0001 * row["costs"]["generated_successors"],
                )
                row["executions"][-1]["result"].update(found=False, proof=None)
        report = menu_report(rows, groups)
        self.assertEqual(report["groups"][0]["menu_proofs_bounds"], [0, 0])
        self.assertEqual(report["groups"][0]["structurally_lost"], [[1, 2, 3, 4]])
        self.assertTrue(report["groups"][0]["menu_cannot_beat_observed_direct_mean"])


if __name__ == "__main__":
    unittest.main()
