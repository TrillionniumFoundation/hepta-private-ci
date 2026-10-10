"""Receipt integrity tests use explicit non-pretrained records."""

import copy
import unittest

from frozen_policy_receipt import ARMS, align, replay, strict_json


def fixture(kind="new_fact"):
    case = dict(query=dict(identity="q", content="unchanged"), kind=kind, candidate_digest="pool")
    rows = [dict(question_id="q", query=copy.deepcopy(case["query"]), arm=arm,
                 kind=kind, candidate_digest="pool", status="succeeded", answer="original")
            for arm in ARMS]
    scored = [r | {"strict_task_success": True} for r in copy.deepcopy(rows)]
    if kind == "procedure":
        for row in scored:
            row["procedure_verification"] = dict(exit_code=0)
    return rows, scored, {"q": case}


class FrozenPolicyReceiptTests(unittest.TestCase):
    def test_original_answers_survive_only_declared_score_annotations(self):
        for kind in ("new_fact", "procedure"):
            rows, scored, cases = fixture(kind)
            self.assertEqual(align(rows, scored, cases), scored)
            self.assertNotIn("strict_task_success", rows[0])

    def test_answer_or_query_cannot_be_repaired_in_the_scored_view(self):
        for field, value in (("answer", "repaired [E1]"), ("candidate_digest", "different"),
                             ("query", dict(identity="q", content="substituted")),
                             ("kind", "procedure"), ("added", "hidden")):
            rows, scored, cases = fixture()
            scored[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                align(rows, scored, cases)

    def test_partial_or_duplicate_census_rejects(self):
        rows, scored, cases = fixture()
        for a, b in ((rows[:-1], scored[:-1]), (rows + rows[:1], scored + scored[:1]),
                     (rows[:-1] + rows[:1], scored)):
            with self.assertRaises(ValueError):
                align(a, b, cases)

    def test_failures_are_not_imputed_as_successful_or_deleted(self):
        rows, scored, cases = fixture()
        rows[0].update(status="failed", answer=None, error="original failure")
        scored[0] = copy.deepcopy(rows[0])
        self.assertEqual(align(rows, scored, cases), scored)
        scored[0]["strict_task_success"] = True
        with self.assertRaises(ValueError):
            align(rows, scored, cases)

    def test_early_label_access_or_missing_procedural_receipt_rejects(self):
        rows, scored, cases = fixture()
        rows[0]["strict_task_success"] = True
        with self.assertRaises(ValueError):
            align(rows, scored, cases)
        rows, scored, cases = fixture("procedure")
        del scored[0]["procedure_verification"]
        with self.assertRaises(ValueError):
            align(rows, scored, cases)

    def test_sequence_json_is_not_the_tensor_object_only_parser(self):
        self.assertEqual(strict_json('[{"result": 1}]'), [{"result": 1}])
        for payload in ('{"a": 1, "a": 2}', '[NaN]', '[Infinity]'):
            with self.assertRaises(ValueError):
                strict_json(payload)

    def test_generating_source_is_not_exporter_head(self):
        files = {"tested-commit.txt": ("a" * 40 + "\n").encode()}
        with self.assertRaisesRegex(ValueError, "generating source mismatch"):
            replay(files, "b" * 40)
        with self.assertRaisesRegex(ValueError, "exact generating source required"):
            replay(files, "main")


if __name__ == "__main__":
    unittest.main()
