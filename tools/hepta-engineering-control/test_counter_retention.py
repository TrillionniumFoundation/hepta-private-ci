"""Retained task effects and failure-atomic migration in real child processes."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from assimilation.counter_task import CounterTask, run_counter_task
from assimilation.owned_service import DisposableCounterService, ServiceError


class CounterRetentionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-retention-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def start(self, generation, frontier, version=1):
        service = DisposableCounterService(
            self.root, generation, frontier, implementation_version=version
        )
        self.addCleanup(service.close)
        service.start()
        return service

    def rows(self):
        uri = f"file:{self.root / 'service.sqlite3'}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as database:
            return database.execute(
                "SELECT id, value FROM operations ORDER BY value"
            ).fetchall()

    def test_old_task_survives_later_tasks_upgrade_and_code_rollback(self):
        first = CounterTask("first", 0, 2)
        second = CounterTask("second", 2, 4)
        service = self.start(1, 0)
        run_counter_task(service, first)
        service.close()
        upgraded = self.start(2, 2, version=2)
        run_counter_task(upgraded, second)
        before = self.rows()
        upgraded.close()
        rollback = self.start(3, 4, version=1)
        result = run_counter_task(rollback, first)
        self.assertEqual(result, {
            "task_id": "first", "initial_counter": 0, "target_counter": 2,
            "observed_counter": 4, "reconciled_effects": 2,
            "new_effects": 0, "generation": 3,
            "completion_basis": "retained_operation_history",
        })
        self.assertEqual(self.rows(), before)

    def test_later_progress_cannot_authorize_changed_task_target_or_empty_task(self):
        service = self.start(1, 0)
        run_counter_task(service, CounterTask("first", 0, 2))
        run_counter_task(service, CounterTask("second", 2, 4))
        before = self.rows()
        for task in (
            CounterTask("other", 0, 2),
            CounterTask("first", 0, 3),
            CounterTask("empty", 0, 0),
        ):
            with self.subTest(task=task):
                with self.assertRaises(ServiceError):
                    run_counter_task(service, task)
                self.assertEqual(self.rows(), before)

    def test_new_cli_process_reports_historical_completion_not_the_old_state(self):
        first = CounterTask("cliFirst", 0, 2)
        for generation, task, frontier in (
            (1, first, 0),
            (2, CounterTask("cliSecond", 2, 4), 2),
            (3, first, 4),
        ):
            completed = subprocess.run(
                [sys.executable, "-B", "-m", "assimilation.counter_task",
                 "--root", str(self.root), "--generation", str(generation),
                 "--minimum-counter", str(frontier), "--task-id", task.task_id,
                 "--initial-counter", str(task.initial_counter),
                 "--target-counter", str(task.target_counter)],
                cwd=Path(__file__).resolve().parent,
                env={"LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            if generation == 3:
                self.assertEqual(result, {
                    "task_id": "cliFirst", "initial_counter": 0, "target_counter": 2,
                    "observed_counter": 4, "reconciled_effects": 2,
                    "new_effects": 0, "generation": 3,
                    "completion_basis": "retained_operation_history",
                })
        self.assertEqual(len(self.rows()), 4)

    def test_invalid_history_does_not_commit_schema_or_generation(self):
        cases = {
            "gap": [("a", 1), ("c", 3)],
            "zero": [("a", 0)],
            "negative": [("a", -1)],
            "fractional": [("a", 1.5)],
            "invalid_id": [("", 1)],
            "null_id": [(None, 1)],
            "capacity": [(f"a{i}", i) for i in range(1, 257)],
        }
        for name, history in cases.items():
            with self.subTest(name=name):
                root = self.root / name
                root.mkdir(mode=0o700)
                path = root / "service.sqlite3"
                with closing(sqlite3.connect(path)) as database:
                    database.execute(
                        "CREATE TABLE operations "
                        "(id TEXT PRIMARY KEY, value INTEGER NOT NULL UNIQUE)"
                    )
                    database.execute(
                        "CREATE TABLE service_meta "
                        "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                        "generation INTEGER NOT NULL, schema_version INTEGER NOT NULL, "
                        "implementation_version INTEGER NOT NULL)"
                    )
                    database.execute("INSERT INTO service_meta VALUES (1, 1, 1, 1)")
                    database.executemany("INSERT INTO operations VALUES (?, ?)", history)
                    database.commit()
                service = DisposableCounterService(
                    root, 2, 0, implementation_version=2
                )
                try:
                    with self.assertRaises(ServiceError):
                        service.start()
                finally:
                    service.close()
                with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as database:
                    self.assertEqual(
                        database.execute("SELECT * FROM service_meta").fetchall(),
                        [(1, 1, 1, 1)],
                    )
                    self.assertEqual(
                        [row[1] for row in database.execute("PRAGMA table_info(operations)")],
                        ["id", "value"],
                    )
                    self.assertEqual(
                        database.execute(
                            "SELECT id, value FROM operations ORDER BY value"
                        ).fetchall(), history,
                    )

    def test_full_valid_ledger_reopens_without_resetting_state(self):
        service = self.start(1, 0)
        for value in range(1, 256):
            self.assertEqual(service.request("step", f"effect{value}")["value"], value)
        service.close()
        before = self.rows()
        reopened = self.start(2, 255, version=2)
        self.assertEqual(reopened.request("query")["counter"], 255)
        self.assertEqual(self.rows(), before)


if __name__ == "__main__":
    unittest.main()
