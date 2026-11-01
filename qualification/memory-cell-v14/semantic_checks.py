"""Fixture/interface checks only; no model is evaluated on the new holdout."""

import argparse
import ast
import copy
import hashlib
import json
import unittest
from pathlib import Path

from semantic_costs import query_timings
from semantic_data import HERE, SKILLS, TASKS, canonical, manifest, new_holdout, sha, training_data
from semantic_project_ids import PROJECT_SALT, project_for_body, repair_row, request_body


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

    def test_repair_changes_only_project_fields_of_the_same_requests(self):
        original = json.loads((HERE / "semantic_holdout_labelcue_original.json").read_text())
        fixed = new_holdout()
        self.assertEqual(sha(original), "36d87fb2f4dc05967fe5868f52dfbd0ce208be0173e8fb17783e4e3f167edea1")
        self.assertEqual(fixed["rows"], [repair_row(row) for row in original["rows"]])
        self.assertEqual(fixed["compositions"], original["compositions"])
        allowed = {"text", "query", "unseen_project"}
        for before, after in zip(original["rows"], fixed["rows"]):
            self.assertEqual({k: v for k, v in before.items() if k not in allowed},
                             {k: v for k, v in after.items() if k not in allowed})
            self.assertEqual(request_body(before["text"]), request_body(after["text"]))

    def test_project_mapping_is_independent_of_oracle_metadata_and_order(self):
        rows = new_holdout()["rows"]
        mapping = {request_body(row["text"]): row["unseen_project"] for row in rows}
        self.assertEqual(len(set(mapping.values())), len(rows))
        self.assertEqual(mapping, {request_body(row["text"]): project_for_body(request_body(row["text"]))
                                   for row in reversed(rows)})
        for row in rows:
            poisoned = copy.deepcopy(row)
            for field in set(row) - {"text", "query"}:
                poisoned[field] = {"forbidden_oracle": "changed"}
            self.assertEqual(repair_row(poisoned)["unseen_project"], row["unseen_project"])
        frozen = json.loads((HERE / "semantic_project_id_mapping.json").read_text())
        self.assertEqual(frozen["salt"], PROJECT_SALT)
        self.assertEqual(frozen["body_to_project"], mapping)

    def test_repair_preserves_training_calibration_models_and_selection(self):
        original = json.loads((HERE / "semantic_protocol_labelcue_original.json").read_text())
        fixed = json.loads((HERE / "semantic_protocol.json").read_text())
        self.assertEqual(sha(original), "ca780c0444e116b1bdfcfdb237b29cff3ae52f14c4ee2e8415e477361bf7791f")
        allowed = {"status", "sources", "paired_bugfix"}
        self.assertEqual({k: v for k, v in original.items() if k not in allowed},
                         {k: v for k, v in fixed.items() if k not in allowed})
        original_sources, fixed_sources = copy.deepcopy(original["sources"]), copy.deepcopy(fixed["sources"])
        original_sources.pop("new_project_names")
        fixed_sources.pop("new_project_names")
        self.assertEqual(original_sources, fixed_sources)
        observed = manifest()
        self.assertEqual(observed["train_sha256"], "19ebe0c1c2686688df7327baf7334165b18d5d95c8fac4f3ce013809a8ae328f")
        self.assertEqual(observed["calibration_sha256"], "41e2835f9b3a466212ce810f4935c85686ea0a2bea4517b3d2dbefcdc6799f94")
        self.assertEqual(observed["shared_executor_file_sha256"], "b2e9942631aa645b3e9e2d77ecd7bb8092fa4c7a2a3fa96efae0b9e6bbb49b54")
        self.assertEqual({name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                          for name in fixed["paired_bugfix"]["unchanged_source_sha256"]},
                         fixed["paired_bugfix"]["unchanged_source_sha256"])

    def test_actual_inference_argument_expressions_exclude_oracle_metadata(self):
        class TextOnlyRow(dict):
            def __getitem__(self, key):
                if key != "text":
                    raise AssertionError(f"Predictor read forbidden field: {key}")
                return super().__getitem__(key)

        held = {"rows": [TextOnlyRow(row) for row in new_holdout()["rows"]]}
        tree = ast.parse((HERE / "semantic_run.py").read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "predict"]
        self.assertEqual(len(calls), 4)
        for call in calls:
            self.assertEqual(len(call.args), 1)
            self.assertFalse(call.keywords)
            argument = ast.Expression(body=copy.deepcopy(call.args[0]))
            texts = eval(compile(argument, "<actual-inference-argument>", "eval"),
                         {"__builtins__": {}, "held": held, "text": "composition text only"})
            self.assertIn(texts, [[row["text"] for row in held["rows"]], ["composition text only"]])
        received = []
        def spy_predict(texts):
            received.append(texts)
            return [-1]
        query_timings([{"text": "timing text only", "payload": [],
                        "label": "forbidden", "expected": "forbidden", "query": "forbidden"}], spy_predict)
        self.assertEqual(received, [["timing text only"]] * 3)


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
