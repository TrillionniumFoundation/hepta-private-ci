"""Precommitted-identity checks only; these tests do not execute model inference."""
import copy
import json
from pathlib import Path
import unittest
from native_lora_ood_probe import check_plan, family_summary


PLAN = Path(__file__).with_name("HPCA_V2_OOD_PLAN.json")


class OODPlanContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(PLAN.read_text())

    def test_original_published_plan_has_balanced_four_families(self):
        rows = check_plan(self.plan)
        self.assertEqual(len(rows), 24)
        self.assertEqual(len(set(x["question"] for x in rows)), 24)

    def test_plan_cannot_claim_independence_or_adoption(self):
        for key, value in (("claimed_independent_evaluator", True), ("selection", "ADOPT")):
            changed = copy.deepcopy(self.plan)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_plan(changed)

    def test_duplicated_questions_and_missing_families_are_rejected(self):
        for mutation in ("duplicate_question", "drop_task", "change_truth"):
            changed = copy.deepcopy(self.plan)
            if mutation == "duplicate_question":
                changed["tasks"][1]["question"] = changed["tasks"][0]["question"]
            if mutation == "drop_task":
                changed["tasks"].pop()
            if mutation == "change_truth":
                changed["tasks"][0]["truth"] = "no"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check_plan(changed)

    def test_target_conditions_are_exactly_frozen(self):
        changed = copy.deepcopy(self.plan)
        changed["target_conditions"].reverse()
        with self.assertRaises(ValueError):
            check_plan(changed)

    def test_score_summary_can_report_bad_model(self):
        rows = [
            {"family":"arithmetic","correct":False,"prediction":"no","log_loss":2.,
             "brier":.75},
            {"family":"arithmetic","correct":True,"prediction":"no","log_loss":.1,
             "brier":.01},
        ]
        summary = family_summary(rows)
        self.assertEqual(summary["overall"]["accuracy"], .5)
        self.assertEqual(summary["by_family"]["arithmetic"]["yes_predictions"], 0)


if __name__ == "__main__":
    unittest.main()
