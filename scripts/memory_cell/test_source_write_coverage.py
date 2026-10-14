"""Synthetic source-only curriculum exposure, not pretrained model evidence."""

from copy import deepcopy
import unittest

from source_write_coverage import TWO_HOP, audit_coverage
from source_write_schedule import schedule


def fixture():
    prepared = [
        ([1, 2, 3, 4], [-100, -100, -100, 4]),
        ([1, 2, 3, 4, 5, 6], [-100, -100, -100, 4, 5, 6]),
        ([1, 2, 3, 4, 5], [-100, -100, -100, -100, 5]),
    ]
    scopes = ["alpha", "alpha", "beta"]
    examples = [
        dict(
            query=dict(identity=f"q{i}", scope=scope),
            sources=[f"s{i}"],
            source_digest=f"sha{i}",
            target=f"value{i}",
            **({"curriculum": TWO_HOP} if i == 1 else {}),
        )
        for i, scope in enumerate(scopes)
    ]
    plan = schedule(
        prepared,
        {"alpha": [0, 1], "beta": [2]},
        maximum_steps=6,
        token_ceiling=32,
    )
    return examples, prepared, plan


class SourceCoverageTests(unittest.TestCase):
    def test_original_schedule_exposes_both_types_without_double_count(self):
        examples, prepared, plan = fixture()
        result = audit_coverage(examples, prepared, plan, curriculum="source_two_hop")
        direct, two = result["by_kind"]["direct"], result["by_kind"]["two_hop"]
        self.assertEqual(direct["available_source_examples"], 2)
        self.assertEqual(two["available_source_examples"], 1)
        self.assertEqual(
            sum(r["planned_updates"] for r in (direct, two)),
            plan["planned_steps"],
        )
        self.assertEqual(
            sum(r["planned_input_tokens"] for r in (direct, two)),
            plan["planned_input_tokens"],
        )
        self.assertEqual(
            sum(r["planned_supervised_tokens"] for r in (direct, two)),
            plan["planned_supervised_tokens"],
        )
        self.assertFalse(result["independent_semantic_support_review"])
        self.assertFalse(result["production_accepted"])

    def test_single_hop_cannot_claim_untrained_composition(self):
        examples, prepared, plan = fixture()
        only = deepcopy(examples)
        only[1].pop("curriculum")
        result = audit_coverage(only, prepared, plan, curriculum="single_hop")
        self.assertEqual(result["by_kind"]["two_hop"]["planned_updates"], 0)
        self.assertEqual(
            result["source_exposure"]["unscheduled_source_scope_pairs"], 1
        )
        self.assertEqual(
            result["source_exposure"]["scheduled_source_scope_pairs"], 2
        )
        self.assertEqual(result["source_exposure"]["eligible_source_scope_pairs"], 3)
        self.assertEqual(
            result["by_kind"]["direct"]["planned_updates"],
            plan["planned_steps"],
        )

    def test_unvisited_composition_retained_in_denominator(self):
        examples, prepared, _ = fixture()
        plan = schedule(
            prepared,
            {"alpha": [0, 1], "beta": [2]},
            maximum_steps=6,
            token_ceiling=9,
        )
        result = audit_coverage(examples, prepared, plan, curriculum="source_two_hop")
        self.assertEqual(plan["entries"], [0, 2])
        self.assertEqual(result["by_kind"]["two_hop"]["source_examples_unvisited"], 1)
        self.assertEqual(result["by_kind"]["two_hop"]["planned_updates"], 0)

    def test_shared_source_is_not_falsely_counted_as_new_knowledge(self):
        examples, prepared, plan = fixture()
        examples[1]["sources"] = ["s0", "s1"]
        result = audit_coverage(examples, prepared, plan, curriculum="source_two_hop")
        census = result["source_exposure"]
        self.assertEqual(census["eligible_source_scope_pairs"], 3)
        self.assertEqual(census["scheduled_source_scope_pairs"], 3)
        self.assertEqual(census["unscheduled_source_scope_pairs"], 0)
        self.assertEqual(census["total_scheduled_source_references"], 7)
        self.assertEqual(census["minimum_visits_per_eligible_source"], 1)
        self.assertEqual(census["maximum_visits_per_eligible_source"], 3)
        self.assertEqual(census["unique_training_examples_scheduled"], 3)
        self.assertEqual(census["repeated_example_update_steps"], 3)
        self.assertFalse(result["independent_semantic_support_review"])
        self.assertFalse(result["production_accepted"])

    def test_source_scope_without_an_update_is_not_silently_omitted(self):
        examples, prepared, _ = fixture()
        plan = schedule(
            prepared,
            {"alpha": [0, 1], "beta": [2]},
            maximum_steps=1,
            token_ceiling=32,
        )
        census = audit_coverage(
            examples, prepared, plan, curriculum="source_two_hop"
        )["source_exposure"]
        self.assertEqual(census["eligible_source_scopes"], 2)
        self.assertEqual(census["source_scopes_with_scheduled_updates"], 1)
        self.assertEqual(census["source_scopes_without_scheduled_updates"], 1)
        self.assertEqual(census["unscheduled_source_scope_pairs"], 2)
        self.assertTrue(census["only_planned_source_exposure_not_gradient_or_task_success"])

    def test_audit_does_not_modify_training_examples_or_budget(self):
        examples, prepared, plan = fixture()
        before = deepcopy((examples, prepared, plan))
        audit_coverage(examples, prepared, plan, curriculum="source_two_hop")
        self.assertEqual((examples, prepared, plan), before)

    def test_curriculum_duplicate_question_and_invalid_sources_reject(self):
        examples, prepared, plan = fixture()
        for mode in (
            "wrong_curriculum",
            "duplicate",
            "unknown_kind",
            "duplicate_source",
        ):
            altered = deepcopy(examples)
            kind = "single_hop" if mode == "wrong_curriculum" else "source_two_hop"
            if mode == "duplicate":
                altered[1]["query"]["identity"] = altered[0]["query"]["identity"]
            elif mode == "unknown_kind":
                altered[1]["curriculum"] = "unregistered"
            elif mode == "duplicate_source":
                altered[1]["sources"] = ["duplicate", "duplicate"]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_coverage(altered, prepared, plan, curriculum=kind)

    def test_changed_prepared_tokens_or_plan_cannot_claim_coverage(self):
        examples, prepared, plan = fixture()
        for mode in (
            "prepared",
            "visits",
            "budget",
            "token_count",
            "negative_index",
            "boolean_index",
        ):
            ex, pr, sp = deepcopy((examples, prepared, plan))
            if mode == "prepared":
                pr[0][0][0] = 7
            elif mode == "visits":
                sp["visits_per_example"][0] += 1
            elif mode == "budget":
                sp["token_ceiling"] = 1
            elif mode == "token_count":
                sp["planned_input_tokens"] += 1
            elif mode == "negative_index":
                sp["entries"][0] = -1
            elif mode == "boolean_index":
                sp["entries"][0] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_coverage(ex, pr, sp, curriculum="source_two_hop")


if __name__ == "__main__":
    unittest.main()
