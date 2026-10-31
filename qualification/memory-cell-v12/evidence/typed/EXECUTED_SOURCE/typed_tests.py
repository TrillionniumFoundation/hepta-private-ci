"""Reader capability regressions; synthetic fixtures are not efficacy evidence."""

import copy
from pathlib import Path
import unittest

import numpy as np

from typed import TYPES, TypedMemory, build_tasks, build_typed_corpus, execute_checklist, procedures, sha


def fixture():
    identity = dict(id="identity", source_id="document", module="sample.module", path="guide",
        available_phase=0, heading="Identity, mission and ownership", version=1,
        text="The primary owner `team-a` controls changes. The deputy `team-b` reviews them.")
    plan = dict(id="plan", source_id="document", module="sample.module", path="guide", available_phase=0,
        heading="Runtime, concurrency and transaction model", version=1,
        text="sample.module\nRuntime plan\n\n1. Validate the request.\n2. Preserve the intent.\n"
             "3. Recheck the grant.\n4. Dispatch once.\n5. Record the observation.\n")
    return dict(records=[identity, plan], metadata=[dict(module="sample.module", fields=dict(owner="team-a", deputy="team-b"))],
                corpus_sha256="synthetic-test-corpus")


class TypedTests(unittest.TestCase):
    def test_exact_plan_execution_preserves_source_order_and_bounds(self):
        source = "Prose.\n\n1. First action;\n2. Second action with\n   continuation;\n3. Third action.\n\nOther prose."
        block = procedures(source)[0]
        self.assertEqual(source[block["start"]:block["end"]], block["raw"])
        self.assertEqual(block["steps"], ["First action;", "Second action with continuation;", "Third action."])
        self.assertEqual(execute_checklist(block["steps"], 1, 2), dict(before=1, after=3,
            actions=["Second action with continuation;", "Third action."], next_action=None, remaining=[], complete=True))
        self.assertIsNone(execute_checklist(block["steps"], 4, 1))
        self.assertIsNone(execute_checklist(block["steps"], 0, 5))

    def test_all_specialist_removals_execute_capable_generic_fallbacks(self):
        corpus = fixture()
        data = build_tasks(corpus)
        task = next(row for row in data["tasks"] if row["operation"] == "compose" and row["cut"] == 1)
        for removed in (None, *sorted(TYPES)):
            with self.subTest(removed=removed):
                enabled = TYPES if removed is None else TYPES - {removed}
                reader = TypedMemory(corpus["records"], data["events"], enabled)
                result, receipt = reader.solve(task, np.array([.6, .4]))
                self.assertEqual(result, task["expected"])
                self.assertEqual(receipt["evidence_reads"], 2)
                if removed == "semantic":
                    self.assertIn("generic_declaration_parse", receipt["operators"])
                if removed == "procedure":
                    self.assertIn("generic_procedure_parse", receipt["operators"])
                if removed == "event":
                    self.assertGreater(receipt["event_rows_examined"], 0)
        generic = TypedMemory(corpus["records"], data["events"], set())
        result, receipt = generic.solve(task, np.array([.6, .4]))
        self.assertEqual(result, task["expected"])
        self.assertGreater(receipt["parse_calls"], 0)

    def test_correction_withdrawal_and_evidence_budget_are_executed(self):
        corpus, scores = fixture(), np.array([.6, .4])
        data = build_tasks(corpus)
        for enabled in (TYPES, frozenset()):
            reader = TypedMemory(corpus["records"], data["events"], enabled)
            results = []
            for cut in (0, 1, 2):
                task = next(row for row in data["tasks"] if row["operation"] == "compose" and row["cut"] == cut)
                result, receipt = reader.solve(task, scores)
                self.assertEqual(result, task["expected"])
                self.assertLessEqual(receipt["evidence_reads"], 2)
                results.append(result)
            self.assertEqual(results[0]["execution"]["revision"], 1)
            self.assertEqual(results[1]["execution"]["revision"], 2)
            self.assertNotEqual(results[0]["execution"]["actions"], results[1]["execution"]["actions"])
            self.assertIsNone(results[2])
            task = next(row for row in data["tasks"] if row["operation"] == "compose" and row["cut"] == 1)
            self.assertIsNone(reader.solve(task, scores, evidence_limit=1)[0])
            self.assertIsNone(reader.solve(task, np.zeros(2))[0])

    def test_changed_event_content_is_rejected_before_caching_or_replay(self):
        corpus = fixture()
        data = build_tasks(corpus)
        events = copy.deepcopy(data["events"])
        events["plan"][1]["text"] += "changed"
        self.assertNotEqual(events["plan"][1]["text_sha256"], sha(events["plan"][1]["text"]))
        for enabled in (TYPES, frozenset()):
            with self.assertRaises(ValueError):
                TypedMemory(corpus["records"], events, enabled)

    def test_real_document_spans_and_oracle_evidence_task_contract(self):
        corpus = build_typed_corpus(Path(__file__).resolve().parents[2])
        data = build_tasks(corpus)
        records = {row["id"]: row for row in corpus["records"]}
        for span in data["procedure_source_spans"]:
            self.assertEqual(records[span["source_id"]]["text"][span["start"]:span["end"]], span["raw"])
        lookup = {row["id"]: i for i, row in enumerate(corpus["records"])}
        reader = TypedMemory(corpus["records"], data["events"], frozenset())
        for task in data["tasks"]:
            scores = np.zeros(len(records))
            for identity in task["target_ids"]:
                scores[lookup[identity]] = 1.
            self.assertEqual(reader.solve(task, scores)[0], task["expected"], task["id"])


if __name__ == "__main__":
    unittest.main()
