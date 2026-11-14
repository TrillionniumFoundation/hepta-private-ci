"""Integration counterexamples use real committed SQLite effects."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from . import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "effects.sqlite"
        self.goal = {"task_id": "task-1", "left": 21, "right": 42}
        runtime.initialize(self.path, self.goal)

    def step(self, fault, tick):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "experiments.verification_cell_verify1.runtime",
                "--database",
                str(self.path),
                "--goal",
                json.dumps(self.goal),
                "--fault",
                fault,
                "--tick",
                str(tick),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(process.stdout)

    def test_fresh_process_effects_and_atomic_acceptance(self):
        for tick in (1, 2, 3):
            self.step("clean", tick)
        report = runtime.inspect(self.path, self.goal, 4, accept=True)
        self.assertTrue(report["accepted"])
        self.assertFalse(runtime.outcome(self.path, self.goal))
        self.assertFalse(
            runtime.inspect(self.path, self.goal, 4, accept=True, authorized=False)[
                "accepted"
            ]
        )

    def test_missing_ack_recovery_does_not_repeat_effect(self):
        for tick in (1, 2, 3):
            self.step("missing_receipt", tick)
        self.assertEqual(runtime.inspect(self.path, self.goal, 4)["verdict"], "unknown")
        with runtime.connect(self.path) as db:
            before = db.execute(
                "SELECT COUNT(*) FROM journal WHERE kind='effect'"
            ).fetchone()[0]
        self.assertTrue(self.step("missing_receipt", 2)["replayed"])
        result = runtime.reconcile(self.path, self.goal, 4)
        self.assertEqual(
            result,
            {
                "resolved": True,
                "effects_replayed": 0,
                "reason": "actual_snapshot_readback",
            },
        )
        self.assertTrue(
            runtime.inspect(self.path, self.goal, 4, accept=True)["accepted"]
        )
        with runtime.connect(self.path) as db:
            after = db.execute(
                "SELECT COUNT(*) FROM journal WHERE kind='effect'"
            ).fetchone()[0]
        self.assertEqual(before, after)

    def test_each_wrong_effect_is_refuted(self):
        for fault in (
            "semantic_error",
            "partial_success",
            "common_misjudgment",
            "stale_read",
        ):
            with self.subTest(fault=fault):
                path = Path(self.temp.name) / f"{fault}.sqlite"
                runtime.initialize(path, self.goal)
                for tick in (1, 2, 3):
                    runtime.execute_step(path, self.goal, fault, tick)
                result = runtime.inspect(path, self.goal, 4, accept=True)
                self.assertEqual(
                    (result["verdict"], result["accepted"]), ("refuted", False)
                )
                self.assertTrue(runtime.outcome(path, self.goal))

    def test_cached_success_cannot_override_later_state(self):
        for tick in (1, 2):
            self.step("stale_read", tick)
        cached = runtime.inspect(self.path, self.goal, 2)
        self.assertEqual(cached["verdict"], "proved")
        self.step("stale_read", 3)
        latest = runtime.inspect(self.path, self.goal, 4, accept=True)
        self.assertNotEqual(cached["state_version"], latest["state_version"])
        self.assertFalse(latest["accepted"])
        with self.assertRaises(TypeError):
            runtime.inspect(self.path, self.goal, 4, accept=True, receipt=cached)

    def test_conflicting_retry_and_incomplete_intent_are_not_reexecuted(self):
        self.step("clean", 1)
        with self.assertRaises(ValueError):
            runtime.execute_step(self.path, {**self.goal, "left": 99}, "clean", 1)
        with runtime.connect(self.path) as db:
            request = runtime.sha({"goal": self.goal, "fault": "clean", "tick": 2})
            db.execute(
                "INSERT INTO intents VALUES (?,?,2,0,0)", ("task-1/step/2", request)
            )
        self.assertTrue(self.step("clean", 2)["replayed"])
        self.assertEqual(runtime.inspect(self.path, self.goal, 2)["verdict"], "unknown")
        self.assertTrue(runtime.outcome(self.path, self.goal))

    def test_aba_invalidates_old_ack_recovery(self):
        for tick in (1, 2, 3):
            self.step("missing_receipt", tick)
        runtime.reconcile(self.path, self.goal, 4)
        self.assertEqual(runtime.inspect(self.path, self.goal, 4)["verdict"], "proved")
        with runtime.connect(self.path) as db:
            db.execute("UPDATE resources SET value=value+1 WHERE name='right'")
            db.execute("UPDATE meta SET epoch=epoch+1")
            db.execute("UPDATE resources SET value=value-1 WHERE name='right'")
            db.execute("UPDATE meta SET epoch=epoch+1")
        result = runtime.inspect(self.path, self.goal, 4, accept=True)
        self.assertEqual((result["verdict"], result["accepted"]), ("unknown", False))

    def test_changed_goal_cannot_relabel_wrong_effects_as_success(self):
        for tick in (1, 2, 3):
            self.step("semantic_error", tick)
        substituted = {**self.goal, "right": self.goal["right"] + 1}
        for call in (
            lambda: runtime.inspect(self.path, substituted, 4, accept=True),
            lambda: runtime.reconcile(self.path, substituted, 4),
            lambda: runtime.outcome(self.path, substituted),
        ):
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()
        with runtime.connect(self.path) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM accepted").fetchone()[0], 0
            )
        self.assertTrue(runtime.outcome(self.path, self.goal))

    def test_changed_goal_is_rejected_before_new_intent_or_effect(self):
        for change in ({"left": 22}, {"right": 43}, {"task_id": "other"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                runtime.execute_step(self.path, {**self.goal, **change}, "clean", 1)
        with runtime.connect(self.path) as db:
            self.assertEqual(
                (
                    db.execute("SELECT COUNT(*) FROM intents").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM resources").fetchone()[0],
                ),
                (0, 0),
            )

    def test_connections_close_and_exceptions_roll_back(self):
        with self.assertRaises(RuntimeError):
            with runtime.connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO resources VALUES ('left', 999)")
                raise RuntimeError("interrupt transaction")
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
        with runtime.connect(self.path) as checked:
            self.assertEqual(
                checked.execute("SELECT COUNT(*) FROM resources").fetchone()[0], 0
            )
        with self.assertRaises(sqlite3.ProgrammingError):
            checked.execute("SELECT 1")

    def test_invalid_goal_or_frontier_does_not_create_state(self):
        for index, change in enumerate(
            ({"left": True}, {"right": 1.0}, {"task_id": ""}, {"extra": 1})
        ):
            path = Path(self.temp.name) / f"invalid-{index}.sqlite"
            with self.subTest(change=change), self.assertRaises(ValueError):
                runtime.initialize(path, {**self.goal, **change})
            self.assertFalse(path.exists())
        for tick in (-1, 0, 5, True):
            with self.subTest(tick=tick), self.assertRaises(ValueError):
                runtime.reconcile(self.path, self.goal, tick)
        with self.assertRaises(ValueError):
            runtime.inspect(self.path, self.goal, 4, accept=1)
        missing = Path(self.temp.name) / "absent.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            runtime.outcome(missing, self.goal)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
