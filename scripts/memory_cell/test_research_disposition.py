"""Candidate triage fixtures are not model observations or preregistration."""

from copy import deepcopy
import unittest

from research_disposition import CONTROLS, decide


def pair(wins, losses=0, missing=0, n=8):
    return dict(
        wins=wins,
        losses=losses,
        missing_pairs=missing,
        all_planned_effect_bounds=[
            (wins - losses - missing) / n,
            (wins - losses + missing) / n,
        ],
    )


def policy():
    return dict(hybrid=pair(4), organized=pair(0), initial=pair(3))


class DispositionTests(unittest.TestCase):
    def test_beating_initialization_but_tying_organization_rejects(self):
        result = decide("learned_policy", policy(), 8)
        self.assertEqual(result["disposition"], "reject_no_increment_over_controls")
        self.assertEqual(result["no_increment_controls"], ["organized"])
        self.assertFalse(result["continue_training_on_same_census"])
        self.assertFalse(result["population_superiority_established"])

    def test_positive_net_gain_cannot_hide_actual_task_regression(self):
        comparisons = {name: pair(4, 1) for name in CONTROLS["learned_policy"]}
        result = decide("learned_policy", comparisons, 8)
        self.assertEqual(result["disposition"], "reject_observed_task_regression")
        self.assertEqual(
            result["regression_controls"], list(CONTROLS["learned_policy"])
        )

    def test_missing_pair_is_inconclusive_not_a_reduced_success_census(self):
        comparisons = policy() | {"organized": pair(1, missing=1)}
        result = decide("learned_policy", comparisons, 8)
        self.assertEqual(result["disposition"], "inconclusive_incomplete_execution")
        self.assertEqual(result["comparisons"]["organized"]["planned"], 8)
        self.assertEqual(result["comparisons"]["organized"]["ties"], 6)

    def test_even_all_observed_wins_only_require_fresh_evaluation(self):
        comparisons = {name: pair(8) for name in CONTROLS["learned_policy"]}
        result = decide("learned_policy", comparisons, 8)
        self.assertEqual(result["disposition"], "fresh_evaluation_required")
        self.assertFalse(result["independent_confirmation"])
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["modifies_serving_state"])

    def test_module_only_boundary_does_not_require_beating_rag(self):
        comparisons = dict(empty=pair(4), organized=pair(0, 4))
        result = decide("parameter_only", comparisons, 8)
        self.assertEqual(result["disposition"], "compression_boundary_only")
        self.assertEqual(result["regression_controls"], ["organized"])
        self.assertFalse(result["production_accepted"])

    def test_missing_strong_control_cannot_be_replaced_by_weaker_control(self):
        for candidate in CONTROLS:
            comparisons = {name: pair(1) for name in CONTROLS[candidate]}
            comparisons.pop("organized")
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                decide(candidate, comparisons, 8)
        with self.assertRaises(ValueError):
            decide("learned_policy", policy() | {"unregistered": pair(1)}, 8)

    def test_invalid_counts_and_changed_bounds_fail_closed(self):
        for key, value in (
            ("wins", True),
            ("losses", -1),
            ("missing_pairs", 9),
            ("all_planned_effect_bounds", [float("nan"), 1]),
            ("all_planned_effect_bounds", [0, 1]),
            ("planned_pairs", 7),
            ("planned_pairs", True),
        ):
            comparisons = deepcopy(policy())
            comparisons["hybrid"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                decide("learned_policy", comparisons, 8)
        with self.assertRaises(ValueError):
            decide("learned_policy", policy() | {"organized": pair(8, 1)}, 8)

    def test_unregistered_candidate_or_denominator_is_not_a_decision(self):
        for candidate, count in (
            ("unknown", 8),
            ("learned_policy", True),
            ("knowledge", 0),
        ):
            with self.subTest(candidate=candidate, count=count):
                with self.assertRaises(ValueError):
                    decide(candidate, policy(), count)

    def test_control_mapping_order_does_not_change_decision(self):
        comparisons = policy()
        self.assertEqual(
            decide("learned_policy", comparisons, 8),
            decide("learned_policy", dict(reversed(list(comparisons.items()))), 8),
        )


if __name__ == "__main__":
    unittest.main()
