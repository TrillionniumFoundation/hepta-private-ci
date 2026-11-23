import tempfile
import unittest
from pathlib import Path

from scripts.cell_experiments.e5_scale_design import propose, read_plan


def fixture():
    points = []
    for count in (1, 4, 16, 64):
        for mode in ("fixed_total", "fixed_per_source"):
            units = 32 if mode == "fixed_total" else 32 * count
            points.append(
                {
                    "regime": mode,
                    "source_count": count,
                    "proposed_optimizer_updates_if_unit_binding_accepted": units,
                }
            )
    return {
        "points": points,
        "compute_budget_required": {"MAC_limit_per_point": None},
        "verification_budget_required": {"independent_future_B_tasks": None},
    }


class ScalingDesignTests(unittest.TestCase):
    def test_fixed_total_cannot_expose_sixty_four_users(self):
        result = propose(fixture(), [1, 2, 4])
        points = {point["id"]: point for point in result["points"]}
        blocked = points["fixed_total/u64/c1"]
        self.assertFalse(blocked["covers_every_user_under_unit_binding"])
        self.assertEqual(blocked["max_distinct_users_if_enrolled"], 32)
        diversity = [
            pair
            for pair in result["proposed_comparisons"]
            if pair["estimate"] == "diversity"
        ]
        self.assertEqual(
            {pair["treatment"] for pair in diversity},
            {"fixed_total/u4/c1", "fixed_total/u16/c1"},
        )
        for pair in diversity:
            self.assertEqual(pair["baseline"], "fixed_total/u1/c1")
            self.assertEqual(
                points[pair["baseline"]]["proposed_units"],
                points[pair["treatment"]]["proposed_units"],
            )

    def test_parallel_comparisons_hold_user_roster_size_and_budget(self):
        result = propose(fixture(), [4, 1, 2, 2])
        points = {point["id"]: point for point in result["points"]}
        comparisons = [
            pair
            for pair in result["proposed_comparisons"]
            if pair["estimate"] == "system"
        ]
        self.assertEqual(len(comparisons), 8)
        for pair in comparisons:
            baseline = points[pair["baseline"]]
            treatment = points[pair["treatment"]]
            self.assertEqual(baseline["proposed_users"], treatment["proposed_users"])
            self.assertEqual(baseline["proposed_units"], treatment["proposed_units"])
            self.assertEqual(
                treatment["proposed_units"], 32 * treatment["proposed_users"]
            )
            self.assertEqual(baseline["proposed_parallel_cells"], 1)
            self.assertIn(treatment["proposed_parallel_cells"], [2, 4])

    def test_plan_never_backfills_observations_or_cap(self):
        result = propose(fixture(), [1, 2])
        self.assertEqual(
            result["unbound_compute_fields_in_source_plan"], ["MAC_limit_per_point"]
        )
        self.assertEqual(result["measurements"], [])
        self.assertIsNone(result["observed_system_speedup"])
        self.assertIsNone(result["observed_diversity_effect"])
        self.assertEqual(result["runs_authorized_by_this_design"], 0)

    def test_reject_invalid_serial_baseline_and_worker_counts(self):
        for counts in ([], [1], [2, 4], [0, 1, 2], [1, 1.5], [False, 2], [1, True, 2]):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                propose(fixture(), counts)

    def test_reject_different_plan_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "digest differs"):
                read_plan(path)


if __name__ == "__main__":
    unittest.main()
