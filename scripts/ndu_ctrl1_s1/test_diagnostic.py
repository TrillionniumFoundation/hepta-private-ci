"""Regression for duplicate rosters that previously inflated fixed-rule means."""

from copy import deepcopy
from itertools import product
import unittest

from ndu_ctrl1.model import ACTIONS
from ndu_ctrl1.run import ROSTER

from .diagnostic import summarize, validate_roster
from .rules import RuleController


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "profiles": [{"digest": str(i)} for i in range(4)],
            "scenarios": {"confirmation": [{"id": str(i)} for i in range(8)]},
            "training_seeds": [17, 23, 41],
            "controller_roster": list(ROSTER),
        }

    def test_duplicate_plan_entries_fail_before_evaluation(self):
        for field in ("profiles", "scenarios", "training_seeds", "controller_roster"):
            plan = deepcopy(self.plan)
            values = (
                plan[field]["confirmation"] if field == "scenarios" else plan[field]
            )
            values.append(deepcopy(values[0]))
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_roster(plan)

    def test_duplicate_and_missing_results_cannot_change_denominator(self):
        profiles, scenarios, seeds, controllers = validate_roster(self.plan)
        new = [
            {"profile_id": p, "scenario_id": s, "controller": c, "value": 0.5}
            for p, s, c in product(profiles, scenarios, RuleController.RULES)
        ]
        old = [
            {
                "profile_id": p,
                "scenario_id": s,
                "controller": c,
                "training_seed": t,
                "value": 0.4,
                "actions": dict.fromkeys(ACTIONS, 0.0),
            }
            for p, s, t, c in product(profiles, scenarios, seeds, controllers)
        ]
        report = summarize(self.plan, old, new)
        self.assertEqual(
            (report["new_exact_rule_evaluations"], report["historical_rows"]), (96, 864)
        )
        for retained, fresh in (
            (old, new + [new[0]]),
            (old, new[:-1]),
            (old + [old[0]], new),
            (old[:-1], new),
        ):
            with self.assertRaises(ValueError):
                summarize(self.plan, retained, fresh)


if __name__ == "__main__":
    unittest.main()
