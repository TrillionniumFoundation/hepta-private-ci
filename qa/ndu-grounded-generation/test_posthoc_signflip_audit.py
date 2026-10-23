"""Offline regression tests for the v1-only post-hoc audit."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from posthoc_signflip_audit import (METHODS, NUM_TASKS, audit_order,
                                    exact_signflip, holm_one_sided, index_scores)


def fixture():
    compact, journal = [], []
    for i in range(NUM_TASKS):
        source = f"source:{i}"
        task = f"task_{i}"
        for j in range(len(METHODS)):
            method = METHODS[(i + j) % len(METHODS)]
            row = {"task_id": task, "source_id": source, "method": method,
                   "quality": 0.5, "loss": 0.5, "severe": 0.0,
                   "coverage": 1.0, "wall_seconds": 2.0, "cpu_seconds": 4.0,
                   "budget_exceeded": False}
            compact.append(row)
            journal.append({"task_id": task, "method": method, "split": "test", "score": row.copy()})
    return compact, journal


class PosthocSignflipTests(unittest.TestCase):
    def test_exact_ties(self):
        r = exact_signflip([0., 0., 0.])
        self.assertEqual(r["nonzero_pairs"], 0)
        self.assertEqual(r["one_sided_ndu_superiority_p"], 1.)
        self.assertEqual(r["two_sided_exchangeable_p"], 1.)

    def test_exact_positive_two(self):
        r = exact_signflip([1., 1., 0.])
        self.assertEqual((r["wins"], r["losses"], r["ties"]), (2, 0, 1))
        self.assertEqual(r["one_sided_ndu_superiority_p"], 0.25)
        self.assertEqual(r["two_sided_exchangeable_p"], 0.5)

    def test_exact_negative_two(self):
        r = exact_signflip([-1., -1., 0.])
        self.assertEqual(r["one_sided_ndu_superiority_p"], 1.)
        self.assertEqual(r["two_sided_exchangeable_p"], 0.5)

    def test_signflip_rejects_bad_input_or_unbounded_exact_work(self):
        for v in ([], [float("nan")], [float("inf")], [1.] * 21):
            with self.subTest(v=str(v)[:20]), self.assertRaises(ValueError):
                exact_signflip(v)

    def test_holm_stepdown_with_tie_and_upper_bound(self):
        p = holm_one_sided({"a": 0.01, "b": 0.04, "c": 0.03, "d": 1.0})
        self.assertEqual(p, {"a": 0.04, "c": 0.09, "b": 0.09, "d": 1.0})

    def test_valid_full_roster_and_rotated_order(self):
        compact, journal = fixture()
        idx = index_scores(compact)
        self.assertEqual(len(idx), 64)
        report = audit_order(journal, idx)
        self.assertEqual(report["all_scores_full_journal_reconciled"], 768)
        self.assertEqual(sum(report["ndu_position_counts"].values()), 64)
        self.assertTrue(report["balanced_positions"])

    def test_duplicate_is_rejected(self):
        compact, _ = fixture()
        compact.append(compact[0].copy())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            index_scores(compact)

    def test_cross_task_source_alias_is_rejected(self):
        compact, _ = fixture()
        alias = compact[len(METHODS)]["source_id"]
        for row in compact[:len(METHODS)]:
            row["source_id"] = alias
        with self.assertRaisesRegex(ValueError, "aliased"):
            index_scores(compact)

    def test_source_changes_inside_task_is_rejected(self):
        compact, _ = fixture()
        compact[1]["source_id"] = "other-source"
        with self.assertRaisesRegex(ValueError, "multiple"):
            index_scores(compact)

    def test_nan_and_loss_tamper_are_rejected(self):
        compact, _ = fixture()
        compact[0]["quality"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid quality"):
            index_scores(compact)
        compact, _ = fixture()
        compact[0]["loss"] = 0.6
        with self.assertRaisesRegex(ValueError, "loss must equal"):
            index_scores(compact)

    def test_full_journal_score_tamper_rejected(self):
        compact, journal = fixture()
        idx = index_scores(compact)
        journal[0]["score"]["quality"] = 0.7
        with self.assertRaisesRegex(ValueError, "full/compact mismatch"):
            audit_order(journal, idx)

    def test_unbalanced_method_order_rejected(self):
        compact, journal = fixture()
        journal.sort(key=lambda x: (x["task_id"], x["method"]))
        with self.assertRaisesRegex(ValueError, "not balanced"):
            audit_order(journal, index_scores(compact))


if __name__ == "__main__":
    unittest.main()
