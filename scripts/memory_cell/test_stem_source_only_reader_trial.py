"""Falsification tests: post-policy source-only Reader controls never become gold QA."""

from dataclasses import asdict, replace
from types import ModuleType
import sys
import unittest
from unittest.mock import patch

from stem_source_only_reference import make_publisher_source_cases
from stem_source_only_reader_trial import (
    ARMS,
    PHASES,
    SOURCE,
    TREE,
    ZIP_SHA256,
    READER_INVENTORY,
    evaluate,
    pinned_original,
)
from test_stem_source_only_reference import fixture


class FakeOriginalArchive:
    def __init__(self):
        plan, queries, sources = fixture()
        plan.update(
            source_commit=SOURCE,
            reader_inventory=READER_INVENTORY,
            curriculum_attempted_examples=[16, 32, 48],
        )
        self.plan, self.queries, self.sources = plan, queries, sources
        self.rows = []
        self.empty = []
        for stage in (16, 32, 48):
            for phase in PHASES:
                for qid in plan["questions"][phase]:
                    q = queries[qid]
                    for arm in ARMS:
                        self.rows.append(
                            dict(
                                stage=stage,
                                phase=phase,
                                question_id=qid,
                                arm=arm,
                                status="succeeded",
                                family="family-pinned",
                                answer="Frozen answer",
                                receipt=dict(
                                    generator_identity="model-sha",
                                    generator_profile="prompt-sha",
                                    observable_query=asdict(q),
                                    delivered_evidence=[dict(label="E1")],
                                ),
                            )
                        )
        for phase in PHASES:
            for qid in plan["questions"][phase]:
                q = queries[qid]
                self.empty.append(
                    dict(
                        phase=phase,
                        question_id=qid,
                        status="succeeded",
                        evidence_count=0,
                        answer="No evidence",
                        receipt=dict(
                            generator_identity="model-sha",
                            generator_profile="prompt-sha",
                            observable_query=asdict(q),
                            delivered_evidence=[],
                        ),
                    )
                )

    def read(self, name):
        return {
            "tested-commit.txt": SOURCE.encode(),
            "tested-tree.txt": TREE.encode(),
        }[name]

    def json(self, name):
        if name != "comparison/preregistered.json":
            raise AssertionError(name)
        return self.plan

    def jsonl(self, name):
        return {
            "comparison/policy-predictions.jsonl": self.rows,
            "comparison/reader-no-evidence.jsonl": self.empty,
        }[name]


def fake_capacity_data():
    archive = FakeOriginalArchive()
    plan, frozen, zero = pinned_original(archive)
    planned = make_publisher_source_cases(
        plan,
        archive.queries,
        archive.sources,
    )
    results = []
    coverage = []
    for q, evidence, meta in planned:
        results.append(
            dict(
                phase=meta["phase"],
                question_id=q.identity,
                source_family=meta["source_family"],
                status="succeeded",
                answer="Reader evidence source",
                receipt=dict(
                    generator_identity="model-sha",
                    generator_profile="prompt-sha",
                    observable_query=asdict(q),
                    delivered_evidence=list(evidence),
                ),
            )
        )
        coverage.append(
            dict(
                phase=meta["phase"],
                question_id=q.identity,
                source_family=meta["source_family"],
                native_source_unanswerable=False,
                weak_native_support_resolved=True,
                native_support_available_in_pool=True,
                frozen_selected_native_support=True,
            )
        )
    ceiling = dict(
        schema="hepta.stem-post-policy-native-source-ceiling.v1",
        production_accepted=False,
        decisions=coverage,
    )
    targets = {qid: corpus.targets[qid] for qid, corpus in archive.sources.items()}
    return archive, [plan, planned, frozen, zero, results, targets, ceiling]


class SourceOnlyReaderTrialTests(unittest.TestCase):
    def evaluate(self, inputs):
        # The Reader source selection is already complete. Pure synthetic
        # evaluator injection prevents importing any torch/model package.
        score = ModuleType("selector_evaluation")
        score.diagnose = lambda answer, target: (
            1.0 if answer == "Reader evidence source" else 0.0
        )
        with patch.dict(sys.modules, {"selector_evaluation": score}):
            return evaluate(*inputs)

    def test_all_32_saved_reader_comparisons_have_matching_identity(self):
        _, inputs = fake_capacity_data()
        receipt = self.evaluate(inputs)
        self.assertEqual(receipt["matched_original_questions"], 32)
        self.assertEqual(receipt["phase_counts"]["test"]["model_answers"], 8)
        self.assertEqual(
            receipt["phase_counts"]["transfer"]["matched_answer_f1_pairs"], 8
        )
        self.assertEqual(
            receipt["by_original_weak_native_source_coverage"]["native-support-chosen"][
                "conditional_token_f1_gain_mean"
            ],
            1.0,
        )
        self.assertFalse(receipt["production_accepted"])
        self.assertIsNone(receipt["semantic_citation_precision"])

    def test_original_success_census_cannot_be_truncated(self):
        archive = FakeOriginalArchive()
        archive.rows.pop()
        with self.assertRaisesRegex(ValueError, "missing originally sealed answer"):
            pinned_original(archive)

    def test_model_or_question_profile_mismatch_cannot_be_called_support_gain(self):
        for field, replacement in (
            ("generator_identity", "unmatched-weight"),
            ("generator_profile", "unmatched-prompt"),
            ("observable_query", {"identity": "different-question"}),
        ):
            _, entries = fake_capacity_data()
            entries[4][0]["receipt"][field] = replacement
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "model/prompt/source drift"),
            ):
                self.evaluate(entries)

    def test_frozen_original_support_absent_remains_distinct_posthoc_bucket(self):
        _, entries = fake_capacity_data()
        coverage = entries[-1]["decisions"][0]
        coverage["native_support_available_in_pool"] = False
        coverage["frozen_selected_native_support"] = None
        receipt = self.evaluate(entries)
        buckets = receipt["by_original_weak_native_source_coverage"]
        self.assertEqual(buckets["native-support-not-retrieved"]["planned"], 1)
        self.assertEqual(buckets["native-support-chosen"]["planned"], 31)
        self.assertFalse(
            buckets["native-support-not-retrieved"][
                "independently_certified_sufficient_evidence"
            ]
        )

    def test_failed_extra_reader_call_is_not_imputed_as_a_perfect_answer(self):
        _, entries = fake_capacity_data()
        row = entries[4][0]
        row["status"] = "failed"
        del row["answer"]
        del row["receipt"]
        receipt = self.evaluate(entries)
        select = receipt["phase_counts"]["select"]
        self.assertEqual(select["model_or_admission_failed"], 1)
        self.assertEqual(select["matched_answer_f1_pairs"], 7)
        self.assertEqual(select["unscored_or_unavailable_pairs"], 1)
        self.assertEqual(select["original_planned_f1_delta_bounds"], [0.75, 1.0])

    def test_published_source_unanswerable_cannot_be_fake_reader_success(self):
        archive, entries = fake_capacity_data()
        q, _, _ = entries[1][0]
        corpus = archive.sources[q.identity]
        corpus.targets[q.identity] = replace(
            corpus.targets[q.identity], unanswerable=True
        )
        fresh = make_publisher_source_cases(
            archive.plan,
            archive.queries,
            archive.sources,
        )
        self.assertEqual(fresh[0][2]["reason"], "native-unanswerable")
        self.assertEqual(fresh[0][1], ())
        entries[1] = fresh
        entries[4][0] = dict(
            phase=fresh[0][2]["phase"],
            question_id=q.identity,
            source_family=fresh[0][2]["source_family"],
            status="unavailable",
            reason="native-unanswerable",
        )
        entries[5][q.identity] = corpus.targets[q.identity]
        entries[-1]["decisions"][0].update(
            native_source_unanswerable=True,
            weak_native_support_resolved=False,
            native_support_available_in_pool=None,
            frozen_selected_native_support=None,
        )
        receipt = self.evaluate(entries)
        self.assertEqual(receipt["phase_counts"]["select"]["unavailable"], 1)
        self.assertEqual(
            receipt["by_original_weak_native_source_coverage"]["native-unanswerable"][
                "planned"
            ],
            1,
        )
        self.assertTrue(
            receipt["source_window_selected_from_question_not_target_answer"]
        )

    def test_fake_success_for_unavailable_source_is_a_hard_error(self):
        _, entries = fake_capacity_data()
        q, ev, summary = entries[1][0]
        entries[1][0] = (
            q,
            (),
            dict(summary, status="unavailable", reason="native-unanswerable"),
        )
        with self.assertRaisesRegex(ValueError, "cohort identity"):
            self.evaluate(entries)


if __name__ == "__main__":
    unittest.main()
