"""Synthetic pair-opportunity cuts cannot be misread as LoRA updates."""

from types import SimpleNamespace as Row
import unittest

from stem_cell_adapter_opportunity import eligible_pairs_by_stage


def fixture():
    questions = tuple(Row(identity="train-%d" % i) for i in range(48))
    routes = {
        q.identity: ("general" if i % 2 == 0 else "temporal")
        for i, q in enumerate(questions)
    }
    skipped = {1, 3, 19, 23, 34, 35, 40, 47}
    no_pair = {2, 4, 5, 6, 30}
    rows = []
    for i, q in enumerate(questions):
        if i in skipped:
            continue
        feature = Row(
            question_id=q.identity,
            family="family-%d" % (i % 6),
            candidate_ids=("evidence-0", "evidence-1"),
        )
        rows.append(
            Row(
                features=feature,
                positive_indices=() if i in no_pair else (0,),
            )
        )
    warm = {
        x.features.question_id
        for x in rows
        if int(x.features.question_id.split("-")[1]) < 16 and x.positive_indices
    }
    adapters = {
        "lineage": dict(prepared_questions=sorted(warm)),
        "independent-general": dict(
            prepared_questions=sorted(x for x in warm if routes[x] == "general")
        ),
        "independent-temporal": dict(
            prepared_questions=sorted(x for x in warm if routes[x] == "temporal")
        ),
    }
    return questions, rows, routes, adapters


class OpportunityTests(unittest.TestCase):
    def test_cumulative_pair_eligibility_is_not_adapter_continual_learning(self):
        output = eligible_pairs_by_stage(*fixture())
        self.assertEqual(output["actual_adapter_warm_pair_count"], 10)
        self.assertEqual(output["observed_admitted_unique_count"], 40)
        first = output["checkpoint_prefixes"]["16"]
        last = output["checkpoint_prefixes"]["48"]
        self.assertEqual(first["positive_negative_pair_eligible_questions"], 10)
        self.assertEqual(first["admitted_weak_source_questions"], 14)
        self.assertGreater(
            last["positive_negative_pair_eligible_questions"],
            first["positive_negative_pair_eligible_questions"],
        )
        self.assertFalse(output["adapter_updated_after_warm_start"])
        self.assertFalse(output["unseen_task_gain_measured_here"])

    def test_missing_or_extra_prepared_questions_not_laundered(self):
        for mode in ("missing", "extra"):
            qs, rows, routes, adapters = fixture()
            if mode == "missing":
                adapters["lineage"]["prepared_questions"].pop()
            else:
                adapters["lineage"]["prepared_questions"].append("train-46")
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "lineage"):
                eligible_pairs_by_stage(qs, rows, routes, adapters)

    def test_independent_cell_cross_routing_is_rejected(self):
        qs, rows, routes, adapters = fixture()
        adapters["independent-general"]["prepared_questions"].append(
            adapters["independent-temporal"]["prepared_questions"][0]
        )
        with self.assertRaisesRegex(ValueError, "independent"):
            eligible_pairs_by_stage(qs, rows, routes, adapters)

    def test_unregistered_duplicate_and_invalid_positive_rejected(self):
        for mode in ("duplicate", "unregistered", "invalid"):
            qs, rows, routes, adapters = fixture()
            if mode == "duplicate":
                rows.append(rows[0])
            elif mode == "unregistered":
                rows[0] = Row(
                    features=Row(
                        question_id="test-leak", family="test", candidate_ids=("a", "b")
                    ),
                    positive_indices=(0,),
                )
            else:
                rows[0] = Row(features=rows[0].features, positive_indices=(2,))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                eligible_pairs_by_stage(qs, rows, routes, adapters)

    def test_zero_candidate_and_all_positive_are_not_contrastive(self):
        qs, rows, routes, adapters = fixture()
        original = rows[0]
        rows[0] = Row(
            features=Row(
                question_id=original.features.question_id,
                family=original.features.family,
                candidate_ids=original.features.candidate_ids,
            ),
            positive_indices=(0, 1),
        )
        with self.assertRaisesRegex(ValueError, "lineage"):
            eligible_pairs_by_stage(qs, rows, routes, adapters)


if __name__ == "__main__":
    unittest.main()
