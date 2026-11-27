import unittest
from dataclasses import replace
from unittest.mock import patch

from group_tasks import (SPLITS, compose_tasks, delete_evidence, feedback_vector, make_tasks,
                         supported_answer, verify)


class GroupTaskTests(unittest.TestCase):
    def test_construction_labels_are_not_copied_from_public_checker(self):
        with patch("group_tasks.supported_answer", return_value=-1):
            with self.assertRaisesRegex(AssertionError, "constructed target"):
                make_tasks("test", count=1)

    def test_composition_has_unseen_operation_and_different_base_families(self):
        first, second, third = make_tasks("test", count=3)
        composed = compose_tasks(first, second)
        self.assertEqual((composed.family, composed.query, composed.evidence, composed.target),
                         ("composition", ("sum_mod", 8), (first, second), (first.target + second.target) % 8))
        self.assertEqual(composed, compose_tasks(first, second))
        self.assertIn("\n[LEFT]\n" + first.text + "\n[RIGHT]\n" + second.text, composed.text)
        self.assertEqual(supported_answer(composed), composed.target)
        self.assertNotEqual(composed.source_group, compose_tasks(first, third).source_group)
        for left, right in ((first, first), (first, replace(second, family=first.family)),
                            (replace(first, split="train"), second), (composed, third)):
            with self.assertRaises(ValueError):
                compose_tasks(left, right)

    def test_composition_verification_uses_only_public_evidence(self):
        first, second = make_tasks("test", count=2)
        task = compose_tasks(first, second)
        poisoned_parts = tuple(replace(part, target=(part.target + 1) % 8) for part in task.evidence)
        poisoned = replace(task, target=(task.target + 1) % 8, evidence=poisoned_parts)
        self.assertTrue(verify(poisoned, task.target).accepted)
        failed = verify(poisoned, poisoned.target)
        self.assertEqual((failed.accepted, failed.feedback, feedback_vector(False, failed.feedback)),
                         (False, "unsupported_composition", (0.0, 0.0, 0.0, 0.0)))
        for missing in (replace(task, evidence=(first,)),
                        replace(task, evidence=(first, delete_evidence(second))), delete_evidence(task)):
            self.assertIsNone(supported_answer(missing))
            self.assertEqual((verify(missing, task.target).accepted, verify(missing, task.target).feedback),
                             (False, "missing_evidence"))
        self.assertEqual(delete_evidence(task).target, task.target)

    def test_sources_are_disjoint_and_unseen_lengths_are_explicit(self):
        cohorts = [make_tasks(split, count=36) for split in SPLITS]
        for i, left in enumerate(cohorts):
            for right in cohorts[i + 1:]:
                self.assertTrue({t.source_group for t in left}.isdisjoint(t.source_group for t in right))
        self.assertTrue(all(t.depth <= 4 for cohort in cohorts for t in cohort))
        self.assertTrue(all(t.depth >= 5 for t in make_tasks("test", count=24, longer=True)))
        self.assertEqual(cohorts[0], make_tasks("train", count=36))

    def test_verifier_recomputes_public_support_without_target_or_correction(self):
        for task in make_tasks("test", count=24):
            poisoned = replace(task, target=(task.target + 1) % 8)
            self.assertTrue(verify(poisoned, task.target).accepted)
            failed = verify(poisoned, poisoned.target)
            self.assertFalse(failed.accepted)
            self.assertEqual(failed.feedback, "unsupported_" + task.family)
            self.assertEqual(sum(feedback_vector(failed.accepted, failed.feedback)), 1)
            deleted = delete_evidence(task)
            self.assertIsNone(supported_answer(deleted))
            self.assertFalse(verify(deleted, task.target).accepted)


if __name__ == "__main__":
    unittest.main()
