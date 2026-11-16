"""Actual new optimization from durable inputs and fresh-process artifact reads."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_learning_models import NumpyCellHead
from cell_training_queue import TrainingQueue
from real_cell_study_queue import run_queue_stage, verify_queue


class StudyQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "queue"
        self.tasks = ["added_return", "removed_return"]
        self.rows = [{"source_id": f"source:{i}", "split": "train",
                      "labels": {self.tasks[0]: i % 2, self.tasks[1]: 1 - i % 2}}
                     for i in range(32)]
        self.features = np.array([[2 * (i % 2) - 1, 1, i / 100, -i / 100]
                                  for i in range(32)], dtype=np.float32)
        self.sources = [hashlib.sha256(row["source_id"].encode()).hexdigest() for row in self.rows]
        self.training_ids = {task: [row["source_id"] for row in self.rows] for task in self.tasks}
        self.identity = "d" * 64

    def execute(self):
        return run_queue_stage(self.root, self.tasks, self.training_ids, self.rows,
                               self.features, self.sources, self.identity)

    def test_new_200_step_training_publishes_and_recovers_both_distinct_tasks(self):
        result = self.execute()
        self.assertEqual(result["optimizer_steps_per_task"], 200)
        self.assertEqual(result["queue_costs_open"]["jobs_by_status"], {"done": 2})
        self.assertTrue(result["recovery"]["fresh_process"])
        self.assertEqual(result["recovery"]["validation"]["verified_cell_ids"], sorted(self.tasks))
        self.assertGreater(result["stored_input_bytes"], 0)
        digests = []
        with TrainingQueue(self.root / "training.sqlite") as queue:
            for task in self.tasks:
                publication = queue.read_current(task)
                training = publication["result"]["training"]
                self.assertEqual(training["example_updates"], 6400)
                self.assertNotEqual(training["initial_tensor_sha256"], training["trained_tensor_sha256"])
                head = NumpyCellHead.load(self.root / publication["result"]["artifact"], self.identity)
                digests.append(head.digest())
        self.assertEqual(len(set(digests)), 2)
        self.assertEqual(verify_queue(self.root, self.identity)["verified_publications"], 2)

    def test_heldout_source_rejects_before_queue_creation(self):
        self.rows[0]["split"] = "holdout"
        with self.assertRaisesRegex(ValueError, "held-out"):
            self.execute()
        self.assertFalse(self.root.exists())

    def test_changed_persisted_input_or_identity_rejects_recovery(self):
        self.execute()
        with self.assertRaisesRegex(ValueError, "stale"):
            verify_queue(self.root, "c" * 64)
        path = self.root / "inputs" / (self.tasks[0] + ".npz")
        path.write_bytes(b"changed persisted features")
        with self.assertRaisesRegex(ValueError, "archive changed"):
            verify_queue(self.root, self.identity)


if __name__ == "__main__":
    unittest.main()
