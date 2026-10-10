"""Real task input, child effects, independent reads, interruption and recovery."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from assimilation.counter_task import CounterTask, run_counter_task
from assimilation.owned_service import DisposableCounterService, IndeterminateOperation, ServiceError


class CounterTaskTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-counter-task-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def target(self, generation=1, frontier=0, **profile):
        service = DisposableCounterService(self.root, generation, frontier, **profile)
        self.addCleanup(service.close)
        service.start()
        return service

    def observed_rows(self):
        # Independent read-only SQLite connection, never the service's writer or
        # its acknowledgement. This observer does not establish host authority.
        with closing(sqlite3.connect(f"file:{self.root / 'service.sqlite3'}?mode=ro", uri=True)) as db:
            return db.execute("SELECT id,value FROM operations ORDER BY value").fetchall()

    def test_goal_completion_and_repeated_task_do_not_duplicate_effects(self):
        service = self.target()
        self.assertNotEqual(service.process.pid, os.getpid())
        task = CounterTask("allocationA", 0, 3)
        self.assertEqual(run_counter_task(service, task), {
            "task_id": "allocationA", "initial_counter": 0, "target_counter": 3,
            "observed_counter": 3, "reconciled_effects": 0, "new_effects": 3, "generation": 1,
        })
        again = run_counter_task(service, task)
        self.assertEqual((again["new_effects"], again["reconciled_effects"]), (0, 3))
        self.assertEqual(self.observed_rows(), [(task.operation_id(i), i) for i in range(1, 4)])

    def test_commit_without_ack_recovers_exact_task_in_a_new_process(self):
        service = self.target()
        task = CounterTask("allocationB", 0, 4)
        original = service.request

        def lose_second_ack(operation, request_id=""):
            if operation == "step" and request_id == task.operation_id(2):
                return original("commit_then_exit", request_id)
            return original(operation, request_id)

        with patch.object(service, "request", side_effect=lose_second_ack):
            with self.assertRaises(IndeterminateOperation):
                run_counter_task(service, task)
        self.assertEqual(self.observed_rows(), [(task.operation_id(i), i) for i in (1, 2)])
        pid = service.process.pid
        service.close()
        recovered = self.target(2, service.minimum_counter)
        self.assertNotEqual(recovered.process.pid, pid)
        result = run_counter_task(recovered, task)
        self.assertEqual((result["new_effects"], result["reconciled_effects"]), (2, 2))
        self.assertEqual(self.observed_rows(), [(task.operation_id(i), i) for i in range(1, 5)])

    def test_changed_target_or_task_cannot_adopt_someone_elses_progress(self):
        service = self.target()
        task = CounterTask("allocationC", 0, 4)
        service.request("step", task.operation_id(1))
        before = self.observed_rows()
        for changed in (CounterTask("allocationC", 0, 5), CounterTask("other", 0, 4)):
            with self.subTest(task=changed), self.assertRaises(ServiceError):
                run_counter_task(service, changed)
            self.assertEqual(self.observed_rows(), before)
        self.assertEqual(run_counter_task(service, task)["observed_counter"], 4)

    def test_upgrade_and_code_rollback_continue_the_same_target_without_data_restore(self):
        task = CounterTask("allocationD", 0, 4)
        before = self.target()
        before.request("step", task.operation_id(1))
        before.close()
        upgraded = self.target(2, 1, implementation_version=2)
        upgraded.request("step", task.operation_id(2))
        upgraded.close()
        rollback = self.target(3, 2, implementation_version=1)
        result = run_counter_task(rollback, task)
        self.assertEqual((result["reconciled_effects"], result["new_effects"]), (2, 2))
        self.assertEqual(self.observed_rows(), [(task.operation_id(i), i) for i in range(1, 5)])

    def test_cli_new_process_reuses_durable_task_instead_of_python_memory(self):
        for generation in (1, 2):
            completed = subprocess.run(
                [sys.executable, "-B", "-m", "assimilation.counter_task",
                 "--root", str(self.root), "--generation", str(generation),
                 "--minimum-counter", str(generation - 1),
                 "--task-id", "cliTask", "--initial-counter", "0", "--target-counter", "1"],
                cwd=Path(__file__).resolve().parent,
                env={"LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual((result["new_effects"], result["reconciled_effects"]),
                             (2 - generation, generation - 1))
        task = CounterTask("cliTask", 0, 1)
        self.assertEqual(self.observed_rows(), [(task.operation_id(1), 1)])

    def test_invalid_target_and_insufficient_budget_have_no_effects(self):
        for values in (("", 0, 1), ("task", True, 1), ("task", 0, 33), ("task", 3, 2)):
            with self.subTest(values=values), self.assertRaises(ServiceError):
                CounterTask(*values)
        service = self.target()
        for _ in range(253):
            service.request("query")
        with self.assertRaises(ServiceError):
            run_counter_task(service, CounterTask("tooLate", 0, 2))
        self.assertEqual(service.sequence, 253)
        self.assertEqual(self.observed_rows(), [])


if __name__ == "__main__":
    unittest.main()
