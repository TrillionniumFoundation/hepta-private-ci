"""Fixture/interface checks only; no model is evaluated on the new holdout."""

import argparse
import json
import unittest
from pathlib import Path

from semantic_data import SKILLS, TASKS, canonical, manifest, new_holdout, training_data


class SemanticContracts(unittest.TestCase):
    def test_authored_goldens_match_independent_executor(self):
        held = new_holdout()
        for row in held["rows"]:
            self.assertEqual(canonical(TASKS.execute(row["skill"], row["payload"])), canonical(row["expected"]))
        for case in held["compositions"]:
            value = case["payload"]
            for skill in case["oracle_skills"]:
                value = TASKS.execute(skill, value)
            self.assertEqual(canonical(value), canonical(case["expected"]))

    def test_frozen_training_and_new_entity_templates_are_disjoint(self):
        old = training_data()
        held = new_holdout()
        previous = {row["text"] for group in old.values() for row in group}
        new = {row["text"] for row in held["rows"]}
        self.assertEqual(len(new), len(held["rows"]))
        self.assertFalse(previous & new)
        for row in held["rows"]:
            self.assertEqual(SKILLS[row["label"]], row["skill"])
            self.assertFalse(any(row["unseen_project"] in text for text in previous))

    def test_predictor_does_not_receive_oracle_composition_fields(self):
        case = new_holdout()["compositions"][0]
        received = []
        selected = iter(case["oracle_skills"])
        def predict(text):
            received.append(text)
            return next(selected)
        result = TASKS.execute_composition(case, predict)
        self.assertEqual(received, case["steps"])
        self.assertTrue(result["correct"])
        self.assertFalse(TASKS.execute_composition(case, lambda _: "sort_numeric")["correct"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SemanticContracts))
    if args.output:
        args.output.write_text(json.dumps({"tests_run": result.testsRun, "successful": result.wasSuccessful(),
            "model_evaluation_on_new_holdout": False, "fixture_executor_checks_only": True,
            "manifest": manifest(), "failures": [str(x) for x in result.failures], "errors": [str(x) for x in result.errors]}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
