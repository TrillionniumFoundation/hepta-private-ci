"""Durable checker treatment, bounded budget and original evidence recovery."""

from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from .checker_dispatch import (
    CheckerBinding,
    CheckerReply,
    DispatchJournal,
    scheduler_identity,
)
from .contracts import digest
from .shadow_schedule import CheckObservation
from . import test_shadow_schedule


class CheckerDispatchTests(unittest.TestCase):
    def setUp(self):
        source = test_shadow_schedule.ShadowScheduleTests()
        source.setUp()
        self.source = source
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "dispatch.sqlite"
        self.journal = DispatchJournal.create(
            self.path,
            manifest_sha256=digest("manifest"),
            risk_model_sha256=source.prediction.model_sha256,
            checker_model_sha256=source.model.model_sha256,
            effects_body_sha256=digest(asdict(source.model)),
            scheduler_sha256=scheduler_identity(),
        )
        self.calls = []

    def reply(self, operation, snapshot, outcome="pass", actual=None):
        return CheckerReply(
            operation,
            "duplicate",
            digest("duplicate"),
            digest(asdict(snapshot)),
            outcome,
            digest("actual-evidence"),
            actual,
        )

    def invoke(self, operation, snapshot):
        self.calls.append(operation)
        return self.reply(operation, snapshot)

    def dispatch(self, operation="op", run=None, **changes):
        args = dict(
            hard_checks_complete=True,
            operation_id=operation,
            checkers=tuple(
                CheckerBinding(c.checker_id, c.version_sha256, run or self.invoke)
                for c in self.source.checkers
            ),
            read_snapshot=lambda snapshot: digest(asdict(snapshot)),
        )
        args.update(changes)
        return self.journal.dispatch_one(
            self.source.prediction,
            self.source.model,
            (),
            ("accept", "reject", "repair"),
            ((0, 100), (5, 5), (2, 12)),
            1,
            **args,
        )

    def test_actual_reply_reopen_and_exact_retry_never_repeat_callback(self):
        result = self.dispatch()
        self.assertEqual(
            (result["status"], self.calls, result["observation"]["outcome"]),
            ("completed", ["op"], "pass"),
        )
        self.journal = DispatchJournal(
            self.path, expected_config_sha256=self.journal.config_sha256
        )
        retry = self.dispatch()
        self.assertEqual((retry["reused"], self.calls), (True, ["op"]))

    def test_pending_original_blocks_new_operation_and_reconciles_without_run(self):
        def lost(operation, snapshot):
            self.calls.append(operation)
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.dispatch(run=lost)
        self.assertEqual(self.dispatch()["status"], "pending")
        with self.assertRaises(ValueError):
            self.dispatch(operation="new")
        result = self.journal.reconcile(
            "op",
            self.reply("op", self.source.snapshot),
            read_snapshot=lambda snapshot: digest(asdict(snapshot)),
            authenticate=lambda *args: True,
        )
        self.assertEqual((result["status"], self.calls), ("completed", ["op"]))

    def test_mandatory_gate_never_calls_checker(self):
        result = self.dispatch(hard_checks_complete=False)
        self.assertEqual((result["status"], self.calls), ("not_run", []))

    def test_invalid_reply_never_enters_history_or_retries_under_new_key(self):
        result = self.dispatch(run=lambda operation, snapshot: "pass")
        self.assertEqual((result["status"], result["observation"]), ("unknown", None))
        with self.assertRaises(ValueError):
            self.dispatch(operation="fresh")

    def test_state_change_keeps_explicit_unknown(self):
        reads = iter((digest(asdict(self.source.snapshot)), digest("changed")))
        result = self.dispatch(read_snapshot=lambda snapshot: next(reads))
        self.assertEqual(
            (result["reason"], result["observation"]), ("stale_after_check", None)
        )

    def test_same_model_hash_with_changed_costs_refuses_before_callback(self):
        self.source.model = replace(
            self.source.model,
            checkers=tuple(
                replace(checker, cost=0) for checker in self.source.model.checkers
            ),
        )
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual(self.calls, [])

    def test_recorded_unknown_is_an_outcome_and_overrun_is_retained(self):
        result = self.dispatch(
            run=lambda operation, snapshot: self.reply(
                operation, snapshot, "unknown", 2
            )
        )
        self.assertEqual(
            (
                result["status"],
                result["observation"]["outcome"],
                result["budget_overrun"],
                result["charged_cost_units"],
            ),
            ("completed", "unknown", True, 2),
        )

    def test_forged_history_and_inflated_budget_refuse(self):
        result = self.dispatch()
        observation = CheckObservation(**result["observation"])
        for history, budget in (((), 0.9), ((observation,), 1)):
            with (
                self.subTest(history=history, budget=budget),
                self.assertRaises(ValueError),
            ):
                self.journal.dispatch_one(
                    self.source.prediction,
                    self.source.model,
                    history,
                    ("accept", "reject", "repair"),
                    ((0, 100), (5, 5), (2, 12)),
                    budget,
                    hard_checks_complete=True,
                    operation_id="next",
                    checkers=(),
                    read_snapshot=lambda snapshot: digest(asdict(snapshot)),
                )

    def test_reconciliation_needs_exact_bound_original_and_literal_authentication(self):
        def lost(operation, snapshot):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.dispatch(run=lost)
        reply = self.reply("op", self.source.snapshot)
        for response in (False, None, 1, "verified"):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.journal.reconcile(
                    "op",
                    reply,
                    read_snapshot=lambda s: digest(asdict(s)),
                    authenticate=lambda *args: response,
                )
        with self.assertRaises(ValueError):
            self.journal.reconcile(
                "op",
                replace(reply, snapshot_sha256=digest("other")),
                read_snapshot=lambda s: digest(asdict(s)),
                authenticate=lambda *args: True,
            )
        self.assertEqual(self.journal.status("op")["result"]["status"], "pending")
