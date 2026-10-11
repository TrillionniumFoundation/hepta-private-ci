"""Fixture-only post-policy candidate ceiling cannot become a gold oracle."""

from dataclasses import replace
from types import SimpleNamespace as Obj
import unittest

from native import Question, Target
from stem_cell_source_ceiling import retrospective_pool_ceiling


PHASES = ("select", "retention", "test", "transfer")


class Pool:
    def __init__(self, scope):
        self.windows = (
            Obj(source_id="source-positive", scope=scope),
            Obj(source_id="source-distractor", scope=scope),
        )
        self.scope = scope

    def seal(self):
        return "sealed-pool-" + self.scope


def fixture():
    questions, pools, targets, families, attempts = {}, {}, {}, {}, []
    for phase in PHASES:
        questions[phase] = []
        for i in range(8):
            qid = f"{phase}-{i}"
            q = Question(
                qid, "registered", "scope-" + qid, "What happened?", "2023-05-08"
            )
            questions[phase].append(q)
            pools[qid] = Pool(q.scope)
            targets[qid] = Target("answer", "fixture", ("source-positive",), False)
            families[qid] = "source-family-" + qid
            attempts.append(
                dict(
                    stage=48,
                    arm="frozen_rerank",
                    phase=phase,
                    question_id=qid,
                    family=families[qid],
                    selected=0,
                    status="succeeded",
                    pool_digest=pools[qid].seal(),
                )
            )
    return questions, pools, targets, families, attempts


class RetrospectiveCeilingTests(unittest.TestCase):
    def test_complete_oracle_is_only_weak_source_ceiling(self):
        result = retrospective_pool_ceiling(*fixture())
        self.assertEqual(sum(r["attempted"] for r in result["phases"].values()), 32)
        self.assertEqual(result["phases"]["select"]["support_available_within_pool"], 8)
        self.assertEqual(
            result["phases"]["transfer"]["frozen_correct_source_choices"], 8
        )
        self.assertFalse(result["independent_semantic_review_performed"])
        self.assertFalse(result["production_accepted"])

    def test_retrieval_shortage_and_rerank_miss_are_separate(self):
        qs, pools, targets, families, attempts = fixture()
        targets["select-0"] = replace(targets["select-0"], evidence=("outside-pool",))
        original = next(x for x in attempts if x["question_id"] == "select-1")
        original["selected"] = 1
        report = retrospective_pool_ceiling(
            qs,
            pools,
            targets,
            families,
            attempts,
        )["phases"]["select"]
        self.assertEqual(report["support_missing_from_pool"], 1)
        self.assertEqual(report["frozen_missed_available_support"], 1)
        self.assertEqual(report["frozen_correct_source_choices"], 6)
        self.assertEqual(report["support_available_within_pool"], 7)

    def test_unanswerable_and_unresolved_never_claim_rerank_opportunity(self):
        qs, pools, targets, families, attempts = fixture()
        targets["select-0"] = replace(targets["select-0"], unanswerable=True)
        targets["select-1"] = replace(
            targets["select-1"], unresolved_evidence=("unresolved",)
        )
        report = retrospective_pool_ceiling(qs, pools, targets, families, attempts)
        row = report["phases"]["select"]
        self.assertEqual(row["native_unanswerable"], 1)
        self.assertEqual(row["native_unresolved_support"], 1)
        self.assertEqual(row["native_source_resolved"], 6)
        self.assertEqual(row["frozen_correct_source_choices"], 6)

    def test_missing_pool_or_failed_reader_does_not_disappear(self):
        qs, pools, targets, families, attempts = fixture()
        pools.pop("select-0")
        observed = next(x for x in attempts if x["question_id"] == "select-0")
        observed.pop("selected")
        observed.pop("pool_digest")
        observed["status"] = "failed"
        report = retrospective_pool_ceiling(qs, pools, targets, families, attempts)
        row = report["phases"]["select"]
        self.assertEqual(row["attempted"], 8)
        self.assertEqual(row["candidate_pool_missing"], 1)
        self.assertEqual(row["frozen_reader_failed"], 1)
        self.assertEqual(row["frozen_not_chosen_or_unobserved"], 1)

    def test_pool_drift_and_cross_scope_are_rejected(self):
        for corruption in ("pool_hash", "cross_scope"):
            qs, pools, targets, families, attempts = fixture()
            if corruption == "pool_hash":
                attempts[0]["pool_digest"] = "changed-after-answer"
            else:
                pools["select-0"].windows = (
                    Obj(source_id="source-positive", scope="outside"),
                )
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                retrospective_pool_ceiling(qs, pools, targets, families, attempts)

    def test_duplicate_and_forged_family_fail_closed(self):
        qs, pools, targets, families, attempts = fixture()
        with self.assertRaises(ValueError):
            retrospective_pool_ceiling(
                qs,
                pools,
                targets,
                families,
                attempts + [dict(attempts[0])],
            )
        attempts[0]["family"] = "cross-family"
        with self.assertRaisesRegex(ValueError, "family"):
            retrospective_pool_ceiling(qs, pools, targets, families, attempts)

    def test_duplicate_question_across_phases_is_not_an_independent_case(self):
        questions, pools, targets, families, attempts = fixture()
        questions["transfer"][0] = replace(
            questions["transfer"][0], identity="select-0"
        )
        with self.assertRaisesRegex(ValueError, "32-question cohort"):
            retrospective_pool_ceiling(
                questions,
                pools,
                targets,
                families,
                attempts,
            )

    def test_successful_forced_top1_cannot_hide_missing_selection(self):
        questions, pools, targets, families, attempts = fixture()
        attempts[0].pop("selected")
        with self.assertRaisesRegex(ValueError, "forced-top1"):
            retrospective_pool_ceiling(
                questions,
                pools,
                targets,
                families,
                attempts,
            )


if __name__ == "__main__":
    unittest.main()
