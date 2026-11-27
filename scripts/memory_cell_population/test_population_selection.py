"""Promotion is source-only, retention-preserving, budgeted and tie conservative."""

from copy import deepcopy
import unittest

from population_selection import choose_population


class PopulationSelectionTests(unittest.TestCase):
    def setUp(self):
        self.families = ["semantic"] * 16 + ["episode"] * 24 + ["procedure"] * 24
        self.scores = {
            arm: [i < count for i in range(64)]
            for arm, count in (("parent", 16), ("single", 18), ("split", 22))
        }
        self.costs = {
            arm: {
                "private_parameter_bytes": size,
                "retained_checkpoint_bytes": size + 1024,
                "optimizer_steps": steps,
                "router_artifact_bytes": router,
            }
            for arm, size, steps, router in (
                ("parent", 921600, 0, 0),
                ("single", 1843200, 1024, 0),
                ("split", 1843200, 1024, 7191),
            )
        }

    def choose(self):
        return choose_population(self.scores, self.families, self.costs)

    def test_four_gain_promotes_but_three_gain_and_ties_keep_cheaper(self):
        result = self.choose()
        self.assertEqual(
            (
                result["chosen_arm"],
                result["minimum_split_gain"],
                result["split_gain_over_single"],
            ),
            ("split", 4, 4),
        )
        self.scores["split"][21] = False
        self.assertEqual(self.choose()["chosen_arm"], "single")
        self.scores["split"] = self.scores["single"].copy()
        self.assertEqual(self.choose()["chosen_arm"], "single")

    def test_any_parent_correct_semantic_regression_blocks_that_candidate(self):
        self.scores["split"] = [True] * 64
        self.scores["split"][0] = False
        self.assertEqual(self.choose()["chosen_arm"], "single")
        self.scores["single"][1] = False
        result = self.choose()
        self.assertEqual(
            (result["chosen_arm"], result["single_eligible"], result["split_eligible"]),
            ("parent", False, False),
        )

    def test_parent_quality_gate_cannot_be_evaded_by_candidate_accuracy(self):
        self.scores["parent"] = [i < 11 for i in range(64)]
        self.scores["single"] = self.scores["split"] = [True] * 64
        result = self.choose()
        self.assertEqual(
            (result["parent_recall_gate"], result["chosen_arm"]), (False, "parent")
        )

    def test_split_compares_to_parent_when_single_did_not_improve(self):
        self.scores["single"] = self.scores["parent"].copy()
        self.scores["split"] = [i < 20 for i in range(64)]
        result = self.choose()
        self.assertEqual(
            (result["best_eligible_cheaper_arm"], result["chosen_arm"]),
            ("parent", "split"),
        )

    def test_measured_router_budget_boundary_and_matched_optimizer_work(self):
        self.costs["split"]["router_artifact_bytes"] = 18432
        self.assertEqual(self.choose()["chosen_arm"], "split")
        self.costs["split"]["router_artifact_bytes"] += 1
        self.assertEqual(self.choose()["chosen_arm"], "single")
        self.costs["split"]["router_artifact_bytes"] = 7191
        self.costs["split"]["private_parameter_bytes"] += 4
        self.assertEqual(self.choose()["chosen_arm"], "single")
        self.costs["split"]["private_parameter_bytes"] -= 4
        self.costs["split"]["optimizer_steps"] += 1
        self.assertEqual(self.choose()["chosen_arm"], "single")

    def test_malformed_outcomes_and_missing_or_nonfinite_costs_fail_closed(self):
        for value in (1, None, float("nan")):
            scores = deepcopy(self.scores)
            scores["split"][0] = value
            with self.assertRaises(ValueError):
                choose_population(scores, self.families, self.costs)
        for value in (0, -1, float("nan"), True):
            costs = deepcopy(self.costs)
            costs["split"]["retained_checkpoint_bytes"] = value
            with self.assertRaises(ValueError):
                choose_population(self.scores, self.families, costs)
        with self.assertRaises(ValueError):
            choose_population(None, self.families, self.costs)


if __name__ == "__main__":
    unittest.main()
