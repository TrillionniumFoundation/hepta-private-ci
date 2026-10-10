"""Curriculum isolation and paired-intervention regression, not semantic scoring."""

import unittest

from memory_curriculum import project_curriculum
from test_reviewed_bundle import fixture
from native import digest


class MemoryCurriculumTests(unittest.TestCase):
    def project(self, plan, reviews, **overrides):
        args = dict(through="2024-07-01", training_ids=frozenset({"q"}),
                    forbidden_ids=frozenset(), forbidden_families=frozenset(),
                    forbidden_roots=frozenset(), revoked=set())
        return project_curriculum(plan, reviews, **(args | overrides))

    def test_complete_and_missing_requirements_share_the_same_question(self):
        plan, reviews = fixture()
        result = self.project(plan, reviews)
        rows = result["examples"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["query_digest"] for r in rows}), 1)
        self.assertEqual(len({r["paired_full_digest"] for r in rows}), 1)
        self.assertEqual([len(r["context"]) for r in rows], [2, 1, 1])
        self.assertEqual([r["target"] for r in rows], ["reviewer_claimed_complete",
                        "reviewer_claimed_missing", "reviewer_claimed_missing"])
        self.assertFalse(result["optimizer_executed"])
        self.assertFalse(result["gold_answers_accessed"])
        self.assertTrue(all(not r["label_independently_verified"] for r in rows))

    def test_no_review_is_not_unanswerability_supervision(self):
        plan, reviews = fixture()
        reviews["reviews"] = {}
        result = self.project(plan, reviews)
        self.assertEqual(result["examples"], [])
        self.assertEqual(result["dispositions"], [dict(query_id="q", status="missing_review_not_negative")])

    def test_future_review_query_and_forbidden_family_or_root_reject(self):
        plan, reviews = fixture()
        for args in (dict(through="2024-06-01"), dict(forbidden_ids=frozenset({"q"})),
                     dict(forbidden_families=frozenset({"f"})),
                     dict(forbidden_roots=frozenset({"r2"})), dict(revoked={"r1"})):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.project(plan, reviews, **args)
        reviews["base_plan_digest"] = "0"*64
        with self.assertRaises(ValueError):
            self.project(plan, reviews)

    def test_unused_source_leakage_is_rejected_too(self):
        plan, reviews = fixture()
        plan["cases"][0]["originals"].append(dict(plan["cases"][0]["originals"][0],
                                               identity="new", root="heldout"))
        reviews["base_plan_digest"] = digest(plan)
        with self.assertRaises(ValueError):
            self.project(plan, reviews, forbidden_roots=frozenset({"heldout"}))

    def test_test_only_case_does_not_change_training_projection(self):
        plan, reviews = fixture()
        expected = self.project(plan, reviews)["examples"]
        old = plan["cases"][0]
        plan["cases"].append(old | {"question": old["question"] | {"identity": "heldout"}})
        reviews["base_plan_digest"] = digest(plan)
        actual = self.project(plan, reviews, forbidden_ids=frozenset({"heldout"}))["examples"]
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
