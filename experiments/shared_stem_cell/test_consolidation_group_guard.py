import unittest
from types import SimpleNamespace

from experiments.shared_stem_cell.consolidation_group_guard import GroupAuditError, evaluate


def cases():
    return [SimpleNamespace(
        case_id=f"case{i}", group=f"group{i//2}", split="holdout" if i < 4 else "retention",
        scope="dev", cell=i%2
    ) for i in range(6)]


def probs(ids):
    return [[0.9, 0.1] if n == 0 else [0.1, 0.9] for n in ids]


class GroupGuardTests(unittest.TestCase):
    def test_exact_no_change_is_per_group_nonregression(self):
        x = cases()
        predictions = {"bank": probs([0, 1, 0, 1, 0, 1]),
                       "student": probs([0, 1, 0, 1, 0, 1])}
        receipt = evaluate(predictions, x, [0, 1, 0, 1, 0, 1])
        self.assertTrue(receipt["scores"]["student"]["empirical_no_source_group_regression"])
        self.assertFalse(receipt["future_task_retention_certified"])

    def test_one_source_group_regression_disqualifies_despite_global_gain(self):
        x = cases()
        # Bank wrong on three cases but right on group0/cell0.
        bank = [0, 1, 1, 1, 0, 0]
        student = [1, 1, 0, 1, 0, 1]
        labels = [0, 1, 0, 1, 0, 1]
        receipt = evaluate({"bank": probs(bank), "student": probs(student)}, x, labels)
        out = receipt["scores"]["student"]
        self.assertGreater(out["correct"], out["bank_correct"])
        self.assertFalse(out["empirical_no_source_group_regression"])
        self.assertGreater(out["paired_losses"], 0)

    def test_missing_student_case_fails_before_scoring(self):
        x = cases()
        with self.assertRaisesRegex(GroupAuditError, "missing/extra"):
            evaluate({"bank": probs([0]*6), "student": probs([0]*5)}, x, [0]*6)

    def test_invalid_probabilities_rejected(self):
        x = cases()
        for corrupted in ([1.1, -0.1], [0.0, float("nan")], [0.1, 0.1]):
            with self.subTest(corrupted=corrupted):
                candidate = probs([0]*6)
                candidate[0] = corrupted
                with self.assertRaisesRegex(GroupAuditError, "invalid"):
                    evaluate({"bank": probs([0]*6), "student": candidate}, x, [0]*6)

    def test_cross_scope_and_cross_split_rejected(self):
        x = cases()
        x[1].scope = "foreign"
        with self.assertRaisesRegex(GroupAuditError, "scope"):
            evaluate({"bank": probs([0]*6)}, x, [0]*6)
        x = cases()
        x[-1].group = "group0"
        with self.assertRaisesRegex(GroupAuditError, "different test splits"):
            evaluate({"bank": probs([0]*6)}, x, [0]*6)

    def test_frozen_teacher_cannot_be_missing(self):
        with self.assertRaisesRegex(GroupAuditError, "frozen teacher bank"):
            evaluate({"student": probs([0]*6)}, cases(), [0]*6)

    def test_retention_is_separate_from_holdout(self):
        x = cases()
        labels = [0, 1, 0, 1, 0, 1]
        candidate = [0, 1, 0, 1, 1, 1]
        r = evaluate({"bank": probs(labels), "student": probs(candidate)}, x, labels)
        self.assertTrue(r["scores"]["student"]["holdout_nonregression"])
        self.assertFalse(r["scores"]["student"]["retention_nonregression"])


if __name__ == "__main__":
    unittest.main()
