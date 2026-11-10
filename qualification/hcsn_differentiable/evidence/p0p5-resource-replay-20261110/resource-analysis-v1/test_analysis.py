import unittest

from analyze_resources import best_point, first_crossing, matrix_metrics, select_lr


def point(time, quality, epoch=1):
    return {"wall_seconds": time, "quality": quality, "epoch": epoch,
            "kind": "complete_epoch" if epoch else "development_before"}


class ResourceSemanticsTests(unittest.TestCase):
    def test_cutoff_keeps_missing_and_does_not_interpolate(self):
        rows = [point(301, 0.2), point(901, 0.7)]
        self.assertIsNone(best_point(rows, 300))
        self.assertEqual(best_point(rows, 900), rows[0])
        self.assertEqual(best_point(rows, 901), rows[1])

    def test_initial_evaluation_can_score_budget_but_cannot_cross_target(self):
        rows = [point(5, 0.8, 0), point(50, 0.2)]
        self.assertEqual(best_point(rows, 10), rows[0])
        self.assertEqual(best_point(rows, complete_only=True), rows[1])
        self.assertIsNone(first_crossing(rows, 0.3))

    def test_strict_best_retains_first_tie_and_crossing_is_first_observation(self):
        rows = [point(10, 0.3), point(20, 0.3, 2), point(30, 0.4, 3)]
        self.assertEqual(best_point(rows, 25), rows[0])
        self.assertEqual(first_crossing(rows, 0.3), rows[0])

    def test_incomplete_three_seed_mean_cannot_win_and_tie_uses_low_lr(self):
        rows = [{"learning_rate": 0.001, "three_seed_mean": None},
                {"learning_rate": 0.003, "three_seed_mean": 0.2}]
        self.assertEqual(select_lr(rows), rows[1])
        rows[0]["three_seed_mean"] = 0.2
        self.assertEqual(select_lr(rows), rows[0])
        self.assertIsNone(select_lr([{**r, "three_seed_mean": None} for r in rows]))

    def test_absent_class_denominator_is_preserved(self):
        cm = [[0] * 11 for _ in range(11)]
        cm[0][0] = 3
        cm[0][1] = 1
        rows, metrics = matrix_metrics(cm)
        self.assertEqual(rows, [4] + [0] * 10)
        self.assertEqual(metrics["accuracy"], 0.75)
        self.assertAlmostEqual(metrics["macro_f1_11_classes"], (6 / 7) / 11)
        self.assertAlmostEqual(metrics["macro_f1_present_classes"], 6 / 7)
        cm[0][0] = -1
        with self.assertRaisesRegex(ValueError, "CM counts"):
            matrix_metrics(cm)


if __name__ == "__main__":
    unittest.main()
