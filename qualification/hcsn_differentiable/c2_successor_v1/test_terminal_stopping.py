"""Actual-gate stopping/selection counterexamples and frozen-producer parity."""

import ast
import json
import math
from pathlib import Path
import unittest

import test_terminal_event_accounting as fixtures
from test_terminal_result_json_admission import identity, sha
from c2_stopping import stopping_history, terminal_stopping


class TerminalStoppingTests(unittest.TestCase):
    def setUp(self):
        self.fit = fixtures.TerminalEventAccountingTests(
            "test_complete_two_update_journal_is_admitted"
        )
        self.fit.setUp()
        self.addCleanup(self.fit.doCleanups)

    def rewrite_commit(self):
        fit = self.fit
        fit.commit_path.write_text(json.dumps(fit.commit))
        receipt = {"path": str(fit.commit_path), **identity(fit.commit_path)}
        fit.events[-2]["commit"] = receipt
        fit.result["last_commit"] = receipt

    def rewrite_parent(self, *, patience=None):
        fit = self.fit
        plan = fit.parent_dir / "plan.json"
        if patience is not None:
            value = json.loads(plan.read_text())
            value["patience"] = patience
            plan.write_text(json.dumps(value))
        fit.prior["plan_sha256"] = sha(plan)
        report = fit.parent_dir / "result.json"
        report.write_text(json.dumps(fit.prior))
        fit.parent["result_sha256"] = sha(report)
        fit.result["parent_report"] = identity(report)

    def test_unearned_plateau_is_rejected(self):
        self.fit.result["stop_reason"] = "development_plateau"
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_wrong_reported_best_epoch_is_rejected(self):
        self.fit.result["best_epoch"] = 2
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_hash_consistent_fake_stale_count_is_rejected(self):
        self.fit.commit["stopping"]["stale_epochs"] = 9
        self.rewrite_commit()
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_boolean_committed_epoch_is_rejected(self):
        self.fit.commit["stopping"]["best_epoch"] = True
        self.rewrite_commit()
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_tie_cannot_select_latest_checkpoint(self):
        path = self.fit.root / "checkpoints/epoch-0002.pt"
        self.fit.commit["best_path"] = str(path)
        self.fit.commit["best_checkpoint"] = identity(path)
        self.rewrite_commit()
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_changed_best_alias_is_rejected(self):
        path = self.fit.root / "best.pt"
        path.write_bytes(b"different synthetic candidate")
        self.fit.result["best_checkpoint_sha256"] = sha(path)
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_missing_parent_metric_history_is_rejected(self):
        del self.fit.prior["epochs"][0]["development"]
        self.rewrite_parent()
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_legacy_parent_prefix_without_complete_flag_is_admitted(self):
        del self.fit.prior["epochs"][0]["complete"]
        self.rewrite_parent()
        self.assertTrue(self.fit.invoke()["terminal_evidence_complete"])

    def test_explicit_incomplete_parent_prefix_is_rejected(self):
        self.fit.prior["epochs"][0]["complete"] = False
        self.rewrite_parent()
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_valid_plateau_is_admitted(self):
        self.rewrite_parent(patience=1)
        self.fit.contract["maximum_epochs"] = 200
        self.fit.result["stop_reason"] = "development_plateau"
        self.assertTrue(self.fit.invoke()["terminal_evidence_complete"])

    def test_epoch_cap_cannot_override_simultaneous_plateau(self):
        self.rewrite_parent(patience=1)
        self.assertFalse(self.fit.invoke()["terminal_evidence_complete"])

    def test_later_improvement_cannot_erase_first_stop(self):
        rows = [
            {
                "epoch": i + 1,
                "complete": True,
                "development": {"macro_f1_11_classes": score},
            }
            for i, score in enumerate((0.5, 0.5, 0.8))
        ]
        with self.assertRaises(ValueError):
            terminal_stopping(
                {"epochs": rows[:1]},
                {
                    "epochs": rows[1:],
                    "stop_reason": "development_plateau",
                    "best_epoch": 3,
                },
                {"min_epochs": 2, "patience": 1, "plateau_delta": 0.01},
                200,
            )

    def test_parity_with_actual_frozen_producer_rule(self):
        source = Path(__file__).with_name("c2_boundary.py")
        tree = ast.parse(source.read_text())
        selected = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in ("finite_number", "plateau_state", "first_plateau_epoch")
        ]

        def require(condition, message):
            if not condition:
                raise ValueError(message)

        namespace = dict(math=math, require=require)
        exec(
            compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"),
            namespace,
        )
        scores = (0.2, 0.2, 0.201, 0.25, 0.25, 0.255, 0.25, 0.7, 0.7)
        rows = [
            {
                "epoch": i + 1,
                "complete": True,
                "development": {"macro_f1_11_classes": score},
            }
            for i, score in enumerate(scores)
        ]
        for delta in (0.0, 0.01, 0.05):
            plan = {"min_epochs": 3, "patience": 2, "plateau_delta": delta}
            states, first = stopping_history(rows, plan)
            for end, state in enumerate(states, 1):
                self.assertEqual(state, namespace["plateau_state"](rows[:end], delta))
            self.assertEqual(first, namespace["first_plateau_epoch"](rows, delta, 3, 2))


if __name__ == "__main__":
    unittest.main()
