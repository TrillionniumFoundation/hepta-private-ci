"""Durability and isolation checks for the experimental Python Cell owner."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from hepta_cells.deterministic import (
    ExactRetriever,
    NumericAlgorithm,
    RuleVerifier,
    ToolCell,
    ToolReply,
)
from hepta_cells.lifecycle import (
    Budget,
    CellError,
    CellOwner,
    ComponentIdentity,
    OwnerLimits,
    Partition,
    PendingExecution,
    Qualification,
    ReadbackResult,
    RequestConflict,
    StepContext,
    StepResult,
)


class Counter:
    def __init__(self, version="1", multiplier=1):
        self.identity = ComponentIdentity("counter", version * 64)
        self.multiplier, self.calls = multiplier, 0

    def initial_state(self):
        return {"value": 0}

    def step(self, payload, state, context):
        self.calls += 1
        value = state["value"] + payload["add"] * self.multiplier
        return StepResult({"value": value}, {"value": value}, 2)


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "cells.sqlite"
        self.owner = CellOwner(self.path)
        self.cell = Partition("principal", "agent", "cell", "run")
        self.component = Counter()

    def tearDown(self):
        self.owner.close()
        self.directory.cleanup()

    def create(self, **kwargs):
        return self.owner.create(self.cell, self.component, **kwargs)

    def test_partition_state_view_and_payload_are_detached(self):
        cells = [
            self.cell,
            Partition("principal2", "agent", "cell", "run"),
            Partition("principal", "agent", "cell2", "run"),
            Partition("principal", "agent", "cell", "run2"),
        ]
        view = {"keys": ["allowed"]}
        for cell in cells:
            self.owner.create(cell, self.component, view)
        view["keys"].append("secret")
        first = self.owner.step(cells[0], self.component, "r1", {"add": 7})
        second = self.owner.step(cells[1], self.component, "r1", {"add": 2})
        first["output"]["value"] = -100
        snapshots = [self.owner.checkpoint(cell) for cell in cells]
        self.assertEqual(
            [item["state"] for item in snapshots],
            [{"value": 7}, {"value": 2}, {"value": 0}, {"value": 0}],
        )
        self.assertEqual(
            [item["retrieval_view"] for item in snapshots], [{"keys": ["allowed"]}] * 4
        )
        self.assertEqual(second["output"], {"value": 2})
        self.assertEqual(
            self.owner.step(cells[0], self.component, "r1", {"add": 7})["output"],
            {"value": 7},
        )

    def test_restart_replays_exact_receipt_without_callback(self):
        self.create()
        receipt = self.owner.step(self.cell, self.component, "same", {"add": 4})
        self.owner.close()
        self.owner = CellOwner(self.path)
        with patch.object(
            self.component, "step", side_effect=AssertionError("must not execute")
        ):
            self.assertEqual(
                self.owner.step(self.cell, self.component, "same", {"add": 4}), receipt
            )
        self.assertEqual(
            self.owner.checkpoint(self.cell)["remaining_work_units"], 999998
        )
        with self.assertRaises(RequestConflict):
            self.owner.step(self.cell, self.component, "same", {"add": 5})
        with self.assertRaises(RequestConflict):
            self.owner.step(self.cell, Counter("2"), "same", {"add": 4})

    def test_adopt_reset_rollback_retain_replay_and_refuse_old_hidden(self):
        self.create()
        first = self.owner.step(self.cell, self.component, "old", {"add": 4})
        old = self.owner.checkpoint(self.cell)
        candidate = Counter("2", 10)
        qualification = Qualification(
            self.component.identity.digest, candidate.identity.digest, "a" * 64
        )
        with self.assertRaises(CellError):
            self.owner.adopt(self.cell, candidate, qualification)
        self.owner.qualify = lambda received: received == qualification
        adopted = self.owner.adopt(self.cell, candidate, qualification)
        self.assertEqual((adopted["state"], adopted["epoch"]), ({"value": 0}, 1))
        with self.assertRaises(CellError):
            self.owner.restore(
                self.cell, candidate, old["digest"], candidate.identity.digest
            )
        with self.assertRaises(CellError):
            self.owner.step(self.cell, self.component, "new-with-old", {"add": 1})
        self.assertEqual(
            self.owner.step(self.cell, self.component, "old", {"add": 4}), first
        )
        self.assertEqual(
            self.owner.step(self.cell, candidate, "new", {"add": 1})["output"],
            {"value": 10},
        )
        rolled = self.owner.rollback(
            self.cell, self.component, candidate.identity.digest
        )
        self.assertEqual((rolled["state"], rolled["epoch"]), ({"value": 0}, 2))
        with self.assertRaises(CellError):
            self.owner.restore(
                self.cell, self.component, old["digest"], self.component.identity.digest
            )
        self.owner.reset(self.cell, self.component, self.component.identity.digest)
        self.assertEqual(
            self.owner.step(self.cell, self.component, "old", {"add": 4}), first
        )
        with self.assertRaises(CellError):
            self.owner.rollback(self.cell, Counter("3"), self.component.identity.digest)

    def test_initialization_cannot_change_the_qualified_identity(self):
        self.create()
        candidate = Counter("2")
        qualification = Qualification(
            self.component.identity.digest, candidate.identity.digest, "a" * 64
        )
        self.owner.qualify = lambda received: received == qualification

        def mutating_state():
            candidate.identity = ComponentIdentity("counter", "3" * 64)
            return {"value": 0}

        candidate.initial_state = mutating_state
        with self.assertRaises(CellError):
            self.owner.adopt(self.cell, candidate, qualification)
        self.assertEqual(
            self.owner.status(self.cell)["identity"],
            self.owner.checkpoint(self.cell)["identity"],
        )
        self.assertEqual(
            self.owner.status(self.cell)["identity"]["bundle_digest"], "1" * 64
        )
        old = self.component.identity.digest

        def bad_reset():
            self.component.identity = ComponentIdentity("counter", "4" * 64)
            return {"value": 0}

        self.component.initial_state = bad_reset
        with self.assertRaises(CellError):
            self.owner.reset(self.cell, self.component, old)
        candidate.identity = ComponentIdentity("counter", "2" * 64)
        with self.assertRaises(CellError):
            self.owner.create(Partition("other", "agent", "cell", "run"), candidate)
        self.assertEqual(self.owner.status(self.cell)["epoch"], 0)

    def test_readback_cannot_publish_state_under_a_changed_identity(self):
        self.create()
        with patch.object(
            self.component, "step", side_effect=OSError("lost acknowledgement")
        ):
            with self.assertRaises(PendingExecution):
                self.owner.step(self.cell, self.component, "pending", {"add": 1})

        def changed_identity(pending):
            self.component.identity = ComponentIdentity("counter", "2" * 64)
            return ReadbackResult(StepResult({"value": 10}, {"value": 10}, 2), 1000)

        with self.assertRaises(PendingExecution):
            self.owner.reconcile(self.cell, self.component, "pending", changed_identity)
        status = self.owner.status(self.cell)
        self.assertEqual((status["sequence"], status["pending"]), (0, ["pending"]))
        self.assertEqual(status["identity"]["bundle_digest"], "1" * 64)
        attempt = self.owner.attempts(self.cell, "pending")[-1]
        self.assertEqual(
            (attempt["outcome"], attempt["elapsed_ns"], attempt["work_units"]),
            ("identity_changed", 1000, 2),
        )
        self.assertGreaterEqual(attempt["readback_elapsed_ns"], 0)

    def test_restore_compatible_state_never_refunds_budget(self):
        self.create()
        self.owner.step(self.cell, self.component, "one", {"add": 3})
        snapshot = self.owner.checkpoint(self.cell)
        self.owner.step(self.cell, self.component, "two", {"add": 5})
        restored = self.owner.restore(
            self.cell,
            self.component,
            snapshot["digest"],
            self.component.identity.digest,
        )
        self.assertEqual(
            (restored["state"], restored["epoch"], restored["remaining_work_units"]),
            ({"value": 3}, 1, 999996),
        )
        with self.assertRaises(CellError):
            self.owner.restore(
                self.cell,
                self.component,
                snapshot["digest"],
                self.component.identity.digest,
            )

    def test_budget_failure_is_durable_and_preserves_old_state(self):
        self.create(budget=Budget(max_work_units=1), total_work_units=3)
        receipt = self.owner.step(self.cell, self.component, "over", {"add": 9})
        self.assertEqual(
            (receipt["status"], receipt["work_units"]), ("budget_exceeded", 2)
        )
        self.assertEqual(self.owner.checkpoint(self.cell)["state"], {"value": 0})
        self.assertEqual(
            self.owner.step(self.cell, self.component, "over", {"add": 9}), receipt
        )
        self.assertEqual(self.owner.status(self.cell)["remaining_work_units"], 1)
        self.owner.step(self.cell, self.component, "over-again", {"add": 9})
        with self.assertRaises(CellError):
            self.owner.step(self.cell, self.component, "exhausted", {"add": 9})
        self.assertEqual(self.component.calls, 2)

    def test_confirmed_effect_overrun_preserves_state_and_requires_explicit_recovery(
        self,
    ):
        class Port:
            def __init__(self):
                self.calls = 0

            def invoke(self, invocation):
                self.calls += 1
                return ToolReply({"completed": self.calls}, 11)

        port = Port()
        tool = ToolCell("write", "a" * 64, port, "b" * 64)
        self.owner.create(
            self.cell, tool, budget=Budget(max_work_units=10, max_elapsed_ms=1)
        )
        with patch(
            "hepta_cells.lifecycle.time.perf_counter_ns", side_effect=[1000, 2001000]
        ):
            receipt = self.owner.step(self.cell, tool, "late", {"value": 1})
        self.assertEqual(
            (receipt["status"], receipt["work_units"], receipt["elapsed_ns"]),
            ("budget_exceeded", 11, 2000000),
        )
        self.assertTrue(receipt["state_applied"])
        self.assertTrue(receipt["requires_recovery"])
        snapshot = self.owner.checkpoint(self.cell)
        self.assertEqual(snapshot["state"], {"completed": 1})
        self.owner.close()
        self.owner = CellOwner(self.path)
        self.assertEqual(self.owner.status(self.cell)["budget_halt"], "late")
        self.assertEqual(
            self.owner.step(self.cell, tool, "late", {"value": 1}), receipt
        )
        with self.assertRaises(CellError):
            self.owner.step(self.cell, tool, "next", {"value": 2})
        self.assertEqual(port.calls, 1)
        restored = self.owner.restore(
            self.cell, tool, snapshot["digest"], tool.identity.digest
        )
        self.assertEqual(restored["state"], {"completed": 1})
        self.assertIsNone(self.owner.status(self.cell)["budget_halt"])
        self.assertEqual(
            self.owner.step(self.cell, tool, "late", {"value": 1}), receipt
        )
        self.assertEqual(port.calls, 1)

    def test_observed_timeout_is_not_replaced_with_zero_cost(self):
        self.create(budget=Budget(max_elapsed_ms=1))
        with patch(
            "hepta_cells.lifecycle.time.perf_counter_ns", side_effect=[1000, 2001000]
        ):
            receipt = self.owner.step(self.cell, self.component, "slow", {"add": 9})
        self.assertEqual(
            (receipt["status"], receipt["elapsed_ns"]), ("budget_exceeded", 2000000)
        )
        self.assertEqual(
            self.owner.attempts(self.cell, "slow"),
            [
                dict(
                    phase="settled",
                    elapsed_ns=2000000,
                    work_units=2,
                    outcome="budget_exceeded",
                    readback_elapsed_ns=None,
                )
            ],
        )
        self.assertEqual(self.owner.checkpoint(self.cell)["state"], {"value": 0})

    def test_bad_inputs_are_rejected_before_reservation(self):
        self.create(budget=Budget(max_input_bytes=64))
        for payload in (
            {"add": float("nan")},
            {"add": float("inf")},
            {"add": 10**1000},
            {"add": "x" * 100},
            {1: "value"},
            {"add": (1, 2)},
        ):
            with self.assertRaises(CellError):
                self.owner.step(self.cell, self.component, "bad", payload)
        self.assertEqual(self.component.calls, 0)
        self.assertEqual(self.owner.status(self.cell)["remaining_work_units"], 1000000)
        self.assertEqual(
            self.owner.step(self.cell, self.component, "bad", {"add": 1})["output"],
            {"value": 1},
        )
        with self.assertRaises(CellError):
            Partition("bad/id", "agent", "cell", "run")

    def test_invalid_result_retains_pending_reservation_and_attempt(self):
        self.create()
        with patch.object(
            self.component,
            "step",
            return_value=StepResult("observed", {"value": float("nan")}, 9),
        ):
            with self.assertRaises(PendingExecution):
                self.owner.step(self.cell, self.component, "invalid", {"add": 2})
        attempt = self.owner.attempts(self.cell, "invalid")[0]
        self.assertEqual(
            (attempt["phase"], attempt["work_units"], attempt["outcome"]),
            ("invocation", 9, "CellError"),
        )
        self.assertGreaterEqual(attempt["elapsed_ns"], 0)
        self.assertEqual(self.owner.status(self.cell)["pending"], ["invalid"])
        self.assertEqual(self.owner.status(self.cell)["remaining_work_units"], 990000)
        with self.assertRaises(PendingExecution):
            self.owner.reset(self.cell, self.component, self.component.identity.digest)

    def test_effect_readback_requires_original_cost_and_never_reinvokes(self):
        class Port:
            def __init__(self):
                self.calls, self.invocation, self.reply = 0, None, None

            def invoke(self, invocation):
                self.calls += 1
                self.invocation = invocation
                raise ConnectionError("acknowledgement lost after effect")

            def readback(self, invocation):
                self.assertion = invocation == self.invocation
                return self.reply

        port = Port()
        tool = ToolCell("enqueue", "b" * 64, port, "c" * 64)
        self.owner.create(self.cell, tool)
        with self.assertRaises(PendingExecution):
            self.owner.step(self.cell, tool, "effect", {"job": 7})
        self.owner.close()
        self.owner = CellOwner(self.path)
        for request in ("effect", "different"):
            with self.assertRaises(PendingExecution):
                self.owner.step(self.cell, tool, request, {"job": 7})
        with self.assertRaises(PendingExecution):
            self.owner.reconcile(self.cell, tool, "effect", tool.readback)
        with patch.object(
            port, "readback", side_effect=ConnectionError("readback offline")
        ):
            with self.assertRaises(PendingExecution):
                self.owner.reconcile(self.cell, tool, "effect", tool.readback)
        failed_readback = self.owner.attempts(self.cell, "effect")[-1]
        self.assertEqual(failed_readback["outcome"], "ConnectionError")
        self.assertIsNone(failed_readback["elapsed_ns"])
        self.assertGreaterEqual(failed_readback["readback_elapsed_ns"], 0)
        port.reply = ToolReply({"accepted": 7}, 6)
        with self.assertRaises(PendingExecution):
            self.owner.reconcile(self.cell, tool, "effect", tool.readback)
        self.assertIsNone(self.owner.attempts(self.cell, "effect")[-1]["elapsed_ns"])
        port.reply = ToolReply({"accepted": 7}, 6, 500000)
        receipt = self.owner.reconcile(self.cell, tool, "effect", tool.readback)
        self.assertEqual(
            (receipt["output"], receipt["elapsed_ns"], receipt["work_units"]),
            ({"accepted": 7}, 500000, 6),
        )
        self.assertEqual(self.owner.checkpoint(self.cell)["state"], {"completed": 1})
        self.assertTrue(port.assertion)
        self.assertEqual(port.calls, 1)
        with patch.object(
            port, "readback", side_effect=AssertionError("must not reconcile twice")
        ):
            self.assertEqual(
                self.owner.reconcile(self.cell, tool, "effect", tool.readback), receipt
            )

    def test_actual_process_exit_leaves_durable_pending_without_replay(self):
        self.create()
        effect_file = Path(self.directory.name) / "effect.txt"
        script = """
import os, sys
from pathlib import Path
from hepta_cells.lifecycle import CellOwner, ComponentIdentity, Partition
class Crash:
    identity = ComponentIdentity("counter", "1" * 64)
    def step(self, payload, state, context):
        Path(sys.argv[2]).write_text("one effect", encoding="utf-8")
        os._exit(41)
CellOwner(sys.argv[1]).step(Partition("principal","agent","cell","run"), Crash(), "crash", {"add": 1})
"""
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parent))
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.path), str(effect_file)],
            env=environment,
            timeout=10,
        )
        self.assertEqual(result.returncode, 41)
        self.assertEqual(effect_file.read_text(), "one effect")
        with self.assertRaises(PendingExecution):
            self.owner.step(self.cell, self.component, "crash", {"add": 1})
        self.assertEqual(self.component.calls, 0)
        self.assertEqual(self.owner.status(self.cell)["remaining_work_units"], 990000)
        with self.assertRaises(PendingExecution):
            self.owner.reconcile(
                self.cell,
                self.component,
                "crash",
                lambda intent: ReadbackResult(StepResult(1, {"value": 1}, 2), None),
            )


class OwnerCapacityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "bounded.sqlite"
        self.cell = Partition("principal", "agent", "cell", "run")
        self.other = Partition("principal", "agent", "other", "run")
        self.component = Counter()
        self.owner = None

    def tearDown(self):
        if self.owner is not None:
            self.owner.close()
        self.directory.cleanup()

    def counts(self):
        return {
            table: self.owner.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("cells", "intents", "checkpoints", "history")
        }

    def test_full_global_quotas_survive_reopen_without_blocking_replay_or_readback(
        self,
    ):
        limits = OwnerLimits(
            max_cells=2, max_intents=2, max_checkpoints=2, max_epochs=2
        )
        self.owner = CellOwner(self.path, limits=limits)
        self.owner.create(self.cell, self.component)
        self.owner.create(self.other, self.component)
        receipt = self.owner.step(self.cell, self.component, "done", {"add": 4})
        with patch.object(
            self.component, "step", side_effect=OSError("lost acknowledgement")
        ) as invoked:
            with self.assertRaises(PendingExecution):
                self.owner.step(self.other, self.component, "pending", {"add": 9})
            self.assertEqual(invoked.call_count, 1)
        full = {"cells": 2, "intents": 2, "checkpoints": 2, "history": 2}
        self.assertEqual(self.counts(), full)
        self.owner.close()
        with self.assertRaisesRegex(CellError, "retained database policy"):
            CellOwner(self.path, limits=OwnerLimits())
        self.owner = CellOwner(self.path)
        self.assertEqual(self.owner.limits, limits)
        with patch.object(
            self.component, "step", side_effect=AssertionError("must not invoke")
        ):
            self.assertEqual(
                self.owner.step(self.cell, self.component, "done", {"add": 4}), receipt
            )
            with self.assertRaisesRegex(CellError, "owner intents capacity"):
                self.owner.step(self.cell, self.component, "new", {"add": 4})
            with self.assertRaises(PendingExecution):
                self.owner.step(self.other, self.component, "pending", {"add": 9})
            recovered = self.owner.reconcile(
                self.other,
                self.component,
                "pending",
                lambda intent: ReadbackResult(
                    StepResult({"value": 9}, {"value": 9}, 2), 1000
                ),
            )
            self.assertEqual(
                (recovered["status"], recovered["output"], recovered["elapsed_ns"]),
                ("committed", {"value": 9}, 1000),
            )
            self.assertEqual(
                self.owner.step(self.other, self.component, "pending", {"add": 9}),
                recovered,
            )
            self.assertEqual(
                self.owner.reconcile(
                    self.other,
                    self.component,
                    "pending",
                    lambda intent: self.fail("must not read back twice"),
                ),
                recovered,
            )
            with self.assertRaisesRegex(CellError, "owner intents capacity"):
                self.owner.step(self.other, self.component, "new", {"add": 1})
        self.assertEqual(self.counts(), full)
        self.assertEqual(self.owner.status(self.other)["pending"], [])

    def test_each_global_creation_limit_rejects_before_initializer_and_retains_evidence(
        self,
    ):
        for resource in ("cells", "checkpoints", "epochs"):
            with self.subTest(resource=resource):
                limits = OwnerLimits(**{f"max_{resource}": 1})
                path = self.path.with_name(f"{resource}.sqlite")
                self.owner = CellOwner(path, limits=limits)
                saved = self.owner.create(self.cell, self.component)
                with patch.object(
                    self.component,
                    "initial_state",
                    side_effect=AssertionError("must not initialize"),
                ):
                    with self.assertRaisesRegex(
                        CellError, f"owner {resource} capacity"
                    ):
                        self.owner.create(self.other, self.component)
                self.assertEqual(
                    self.counts(),
                    {"cells": 1, "intents": 0, "checkpoints": 1, "history": 1},
                )
                self.owner.close()
                self.owner = CellOwner(path)
                self.assertEqual(self.owner.checkpoint(self.cell), saved)
                self.assertEqual(self.owner.limits, limits)
                self.owner.close()

    def test_global_epoch_and_checkpoint_limits_reject_transition_without_partial_publish(
        self,
    ):
        for resource in ("epochs", "checkpoints"):
            with self.subTest(resource=resource):
                path = self.path.with_name(f"transition-{resource}.sqlite")
                self.owner = CellOwner(
                    path, limits=OwnerLimits(**{f"max_{resource}": 2})
                )
                saved = self.owner.create(self.cell, self.component)
                self.owner.create(self.other, self.component)
                before = self.owner.status(self.cell)
                with patch.object(
                    self.component,
                    "initial_state",
                    side_effect=AssertionError("must not initialize"),
                ):
                    with self.assertRaisesRegex(
                        CellError, f"owner {resource} capacity"
                    ):
                        self.owner.reset(
                            self.cell, self.component, self.component.identity.digest
                        )
                self.assertEqual(self.owner.status(self.cell), before)
                self.assertEqual(self.owner.checkpoint(self.cell), saved)
                self.assertEqual(
                    self.counts(),
                    {"cells": 2, "intents": 0, "checkpoints": 2, "history": 2},
                )
                self.owner.step(self.cell, self.component, "still-in-epoch", {"add": 1})
                if resource == "checkpoints":
                    with self.assertRaisesRegex(
                        CellError, "owner checkpoints capacity"
                    ):
                        self.owner.checkpoint(self.cell)
                self.owner.close()

    def test_checkpoint_write_failure_cannot_commit_create_or_transition(self):
        self.owner = CellOwner(self.path)
        saved = self.owner.create(self.cell, self.component)
        before = self.counts()
        self.owner.db.execute(
            "CREATE TRIGGER reject_checkpoint BEFORE INSERT ON checkpoints BEGIN SELECT RAISE(ABORT,'checkpoint write failed'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.owner.reset(self.cell, self.component, self.component.identity.digest)
        with self.assertRaises(sqlite3.IntegrityError):
            self.owner.create(self.other, self.component)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.owner.checkpoint(self.cell), saved)
        self.owner.db.execute("DROP TRIGGER reject_checkpoint")
        restored = self.owner.reset(
            self.cell, self.component, self.component.identity.digest
        )
        self.assertEqual(restored["epoch"], 1)
        self.assertEqual(
            self.counts(), {"cells": 1, "intents": 0, "checkpoints": 2, "history": 2}
        )


class DeterministicTests(unittest.TestCase):
    def context(self, component, view=None):
        return StepContext(
            Partition("p", "a", "c", "r"), "request", component.identity, view, Budget()
        )

    def test_configuration_substitution_is_bound_even_with_same_declared_bundle(self):
        first = ExactRetriever({"key": "first"}, "1" * 64)
        changed = ExactRetriever({"key": "changed"}, "1" * 64)
        reordered = ExactRetriever({"key": "first"}, "1" * 64)
        self.assertNotEqual(first.identity, changed.identity)
        self.assertEqual(first.identity, reordered.identity)
        self.assertNotEqual(
            RuleVerifier([{"field": "a", "op": "required"}], "1" * 64).identity,
            RuleVerifier([{"field": "b", "op": "required"}], "1" * 64).identity,
        )
        self.assertNotEqual(
            ToolCell("one", "2" * 64, object(), "1" * 64).identity,
            ToolCell("one", "3" * 64, object(), "1" * 64).identity,
        )
        self.assertNotEqual(
            ToolCell("one", "2" * 64, object(), "1" * 64).identity,
            ToolCell("two", "2" * 64, object(), "1" * 64).identity,
        )
        with tempfile.TemporaryDirectory() as directory:
            owner = CellOwner(Path(directory) / "owner.sqlite")
            cell = Partition("p", "a", "c", "r")
            try:
                owner.create(cell, first, {"keys": ["key"]})
                receipt = owner.step(cell, first, "request", {"key": "key"})
                with self.assertRaises(CellError):
                    owner.step(cell, changed, "new", {"key": "key"})
                with self.assertRaises(RequestConflict):
                    owner.step(cell, changed, "request", {"key": "key"})
                self.assertEqual(
                    owner.step(cell, first, "request", {"key": "key"}), receipt
                )
            finally:
                owner.close()

    def test_exact_retriever_enforces_independent_views(self):
        records = {"public": {"text": "open"}, "private": {"text": "secret"}}
        component = ExactRetriever(records, "d" * 64)
        records["public"]["text"] = "mutated"
        allowed = component.step(
            {"key": "public"},
            component.initial_state(),
            self.context(component, {"keys": ["public"]}),
        )
        denied = component.step(
            {"key": "private"},
            component.initial_state(),
            self.context(component, {"keys": ["public"]}),
        )
        self.assertEqual(
            allowed,
            StepResult({"found": True, "value": {"text": "open"}}, {"queries": 1}, 2),
        )
        self.assertEqual(
            denied, StepResult({"found": False, "value": None}, {"queries": 1}, 2)
        )

    def test_rule_grammar_and_numeric_algorithms(self):
        rules = RuleVerifier(
            [
                {"field": "age", "op": "range", "min": 18, "max": 65},
                {"field": "kind", "op": "member", "values": ["a", "b"]},
            ],
            "e" * 64,
        )
        result = rules.step(
            {"age": 19, "kind": "a"}, rules.initial_state(), self.context(rules)
        )
        self.assertEqual(
            result, StepResult({"passed": True, "failed_rules": []}, {"checks": 1}, 4)
        )
        failed = rules.step(
            {"age": True, "kind": "x"}, rules.initial_state(), self.context(rules)
        )
        self.assertEqual(failed.output, {"passed": False, "failed_rules": [0, 1]})
        with self.assertRaises(CellError):
            RuleVerifier([{"field": "x", "op": "eval", "value": "print(1)"}], "e" * 64)
        mean = NumericAlgorithm("mean_variance", "f" * 64)
        result = mean.step(
            {"values": [1, 2, 3]}, mean.initial_state(), self.context(mean)
        )
        self.assertEqual(
            result,
            StepResult({"count": 3, "mean": 2.0, "variance": 2 / 3}, {"calls": 1}, 6),
        )
        dot = NumericAlgorithm("dot", "f" * 64)
        self.assertEqual(
            dot.step(
                {"left": [1, 3], "right": [2, 4]},
                dot.initial_state(),
                self.context(dot),
            ).output,
            {"value": 14.0},
        )
        with self.assertRaises(CellError):
            dot.step(
                {"left": [1], "right": [2, 3]}, dot.initial_state(), self.context(dot)
            )


if __name__ == "__main__":
    unittest.main()
