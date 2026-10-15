"""Intermediate-operation teacher audit tests; no model training claims."""
from dataclasses import replace
import unittest

from group_tasks import make_tasks, delete_evidence
from group_step_supervision import training_trace


class StepSupervisionTests(unittest.TestCase):
    def test_three_families_generate_bound_training_steps(self):
        tasks = make_tasks("train", count=12, seed=13)
        self.assertEqual({t.family for t in tasks},
                         {"dependency", "constraint", "temporal"})
        for t in tasks:
            row = training_trace(t)
            self.assertEqual(row["authority"], "DENY_ALL")
            self.assertTrue(row["train_only"])
            self.assertEqual(row["source_group"], t.source_group)
            self.assertTrue(row["operation_steps"])
            for step in row["operation_steps"]:
                self.assertTrue(0 <= step["evidence_index"] < len(t.evidence))

    def test_no_test_or_validation_labels(self):
        for split in ("test", "selection", "validation"):
            task = make_tasks(split, count=1, seed=1)[0]
            with self.assertRaisesRegex(ValueError, "TRAIN-only"):
                training_trace(task)

    def test_deleted_evidence_is_not_a_teacher(self):
        task = make_tasks("train", count=1, seed=6)[0]
        with self.assertRaises(ValueError):
            training_trace(delete_evidence(task))

    def test_trace_ignores_stored_target(self):
        task = make_tasks("train", count=1, seed=7)[0]
        a = training_trace(task)
        b = training_trace(replace(task, target=(task.target + 1) % 8))
        self.assertEqual(a["trace_sha256"], b["trace_sha256"])
        self.assertEqual(a["operation_steps"], b["operation_steps"])


if __name__ == "__main__":
    unittest.main()
