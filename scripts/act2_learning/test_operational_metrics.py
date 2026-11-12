"""Missing evidence cannot become free cost, known effects or independent tasks."""

import unittest

from operational_metrics import summarize


def row(arm="fixed", seed=700, **values):
    return {
        "task_id": "same-task",
        "arm": arm,
        "seed": seed,
        "complete": True,
        "claimed_success": True,
        **values,
    }


class OperationalMetricsTests(unittest.TestCase):
    def test_missing_knowledge_and_cost_stay_unknown_despite_oracle_completion(self):
        result = summarize([row(duration_ns=10), row(seed=701, effect_knowledge=None)])
        actual = result["arms"]["fixed"]
        self.assertEqual(
            (
                actual["episodes"],
                actual["task_clusters"],
                actual["offline_complete"],
                actual["policy_confirmed_complete"],
                actual["unknown_effect_outcomes"],
            ),
            (2, 1, 2, 0, 2),
        )
        self.assertEqual(
            actual["measurements"]["end_to_end_ns"],
            {"sum": None, "measured_rows": 0, "missing_rows": 2},
        )
        self.assertEqual(
            actual["measurements"]["duration_ns"],
            {"sum": 10, "measured_rows": 1, "missing_rows": 1},
        )
        self.assertFalse(result["promotion"])

    def test_false_success_and_duplicate_effects_are_retained(self):
        actual = summarize(
            [
                row(
                    complete=False,
                    effect_knowledge="CONFIRMED_COMPLETE",
                    duplicate_effects=2,
                    primitive_calls=0,
                )
            ]
        )["arms"]["fixed"]
        self.assertEqual(
            (actual["false_success"], actual["policy_confirmed_complete"]), (1, 1)
        )
        self.assertEqual(
            actual["measurements"]["duplicate_effects"],
            {"sum": 2, "measured_rows": 1, "missing_rows": 0},
        )
        self.assertEqual(actual["measurements"]["primitive_calls"]["sum"], 0)

    def test_seed_pairing_aggregates_within_task_without_inference(self):
        rows = [
            row(seed=700),
            row(seed=701),
            row("gru", complete=False),
            row("gru", seed=701),
        ]
        self.assertEqual(
            summarize(rows)["paired_task_results"],
            [
                {
                    "task_id": "same-task",
                    "arm": "gru",
                    "seed_pairs": 2,
                    "measured_seed_pairs": 2,
                    "unknown_seed_pairs": 0,
                    "mean_completion_delta": -0.5,
                }
            ],
        )
        rows[-1]["complete"] = None
        actual = summarize(rows)
        self.assertIsNone(actual["paired_task_results"][0]["mean_completion_delta"])
        self.assertEqual(actual["arms"]["gru"]["false_success_unassessed"], 1)

    def test_duplicate_unpaired_and_invalid_cost_rows_are_rejected(self):
        for rows, message in (
            ([row(), row()], "duplicate"),
            ([row(), row("gru", seed=701)], "unpaired"),
            ([row(primitive_calls=-1)], "measurement"),
            ([row(selection_ns=True)], "measurement"),
            ([row(complete=1)], "outcome"),
            ([row(effect_knowledge="applied")], "knowledge"),
        ):
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValueError, message),
            ):
                summarize(rows)


if __name__ == "__main__":
    unittest.main()
