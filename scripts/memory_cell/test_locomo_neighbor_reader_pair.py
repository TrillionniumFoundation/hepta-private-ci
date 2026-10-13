"""Source-only pair and complete-denominator tests; no pretrained model results."""

from copy import deepcopy
import hashlib
import unittest

from locomo_neighbor_reader_pair import (
    CASES,
    NEW_ARM,
    OLD_ARM,
    SCHEMA,
    checked_generation,
    pairs,
    selected_for_evaluation,
)
from locomo_ninearm_source_replay import ZIPS, canonical
from locomo_refusal_attribution import EXPECTED_ZIPS


def roster():
    cases = []
    ranking = []
    for i in range(80):
        qid = f"q{i}"
        case = dict(
            question_id=qid,
            family_proxy_digest=f"family{i // 40}",
            source_census_sha256=f"pool{i}",
            source_ids=[f"{qid}/D1:{k}" for k in range(1, 11)],
        )
        if i < 16:
            cases.append(case)
        for arm, chosen, used in (
            (OLD_ARM, case["source_ids"][:8], 800),
            (NEW_ARM, case["source_ids"][2:6], 400),
        ):
            ranking.append(
                dict(
                    question_id=qid,
                    arm=arm,
                    split="evaluation" if i < 16 else "train",
                    family_proxy_digest=case["family_proxy_digest"],
                    source_census_sha256=case["source_census_sha256"],
                    selected=chosen,
                    selected_source_bytes=used,
                )
            )
    return cases, ranking


def answers():
    cases, ranking = roster()
    new = []
    old = []
    targets = {}
    for i, case in enumerate(cases):
        qid = case["question_id"]
        unanswerable = i == 0
        targets[qid] = dict(
            unanswerable=unanswerable,
            answer="blue" if not unanswerable else "",
        )
        response = "I do not have enough evidence." if unanswerable else "blue"
        new.append(
            dict(
                question_id=qid,
                arm=NEW_ARM,
                status="succeeded",
                answer=response,
                receipt=dict(input_tokens=100),
            )
        )
        for arm in ("lexical_k4", OLD_ARM):
            old.append(
                dict(
                    question_id=qid,
                    arm=arm,
                    status="succeeded",
                    answer="red" if not unanswerable else response,
                    receipt=dict(input_tokens=140),
                )
            )
    return cases, ranking, new, old, targets


def failed_journal(cases, selection):
    rows = [
        dict(
            question_id=c["question_id"],
            arm=NEW_ARM,
            family_proxy_digest=c["family_proxy_digest"],
            source_census_sha256=c["source_census_sha256"],
            selected=r["selected"],
            status="failed",
            error_type="HostUnavailable",
        )
        for c, r in zip(cases, selection, strict=True)
    ]
    raw = b"".join(canonical(r) + b"\n" for r in rows)
    commit = "a" * 40
    receipt = dict(
        schema=SCHEMA,
        source_commit=commit,
        raw_answers_sha256=hashlib.sha256(raw).hexdigest(),
        original_public_sha256=ZIPS["public"][1],
        original_decisions_sha256=ZIPS["decisions"][1],
        original_reference_reader_zip_sha256=EXPECTED_ZIPS["reader"],
        planned=CASES,
        succeeded=0,
        failed=CASES,
        input_token_limit=2048,
        max_generated_tokens=64,
        adaptation_steps=0,
        same_frozen_reader=True,
        original_gold_accessible_during_generation=False,
        answer_postprocessing=False,
        independently_reviewed_sufficiency=False,
        semantic_citation_precision=None,
        production_accepted=False,
        model_identity="b" * 64,
        model_profile="c" * 64,
    )
    return receipt, raw, rows, commit


class NeighborReaderTests(unittest.TestCase):
    def test_selection_uses_only_original_pool_and_byte_budget(self):
        cases, ranking = roster()
        chosen = selected_for_evaluation(cases, ranking)
        self.assertEqual(len(chosen), CASES)
        self.assertTrue(
            all(len(row["selected"]) == 4 for row in chosen)
        )

    def test_missing_duplicate_and_overbudget_candidate_rejected(self):
        for flaw in ("missing", "duplicate", "extra_source", "overbudget"):
            cases, ranking = roster()
            if flaw == "missing":
                ranking.pop()
            elif flaw == "duplicate":
                ranking[-1] = deepcopy(ranking[0])
            elif flaw == "extra_source":
                ranking[1]["selected"].append("unknown")
            else:
                ranking[1]["selected_source_bytes"] = 801
            with self.subTest(flaw=flaw), self.assertRaises(ValueError):
                selected_for_evaluation(cases, ranking)

    def test_paired_quality_is_not_document_coverage(self):
        cases, _, new, old, targets = answers()
        report = pairs(cases, new, old, targets)
        self.assertEqual(report["all"]["planned"], 16)
        self.assertEqual(report["all"]["wins"], 15)
        self.assertEqual(report["all"]["ties"], 1)
        self.assertEqual(report["unanswerable"]["planned"], 1)
        self.assertEqual(report["all"]["extra_input_tokens_on_complete"], -640)

    def test_refusal_and_answer_quality_are_reported_separately(self):
        cases, _, new, old, targets = answers()
        new[0]["answer"] += " Unsupported guess."
        report = pairs(cases, new, old, targets)
        self.assertEqual(report["unanswerable"]["losses"], 1)
        self.assertEqual(report["answerable"]["wins"], 15)

    def test_generation_failure_retains_worst_case_effect_bounds(self):
        cases, _, new, old, targets = answers()
        new[2] = dict(question_id="q2", status="failed")
        report = pairs(cases, new, old, targets)
        item = report["all"]
        self.assertEqual(item["missing_or_unscored"], 1)
        self.assertEqual(item["complete"], 15)
        self.assertLess(item["all_planned_delta_bounds"][0], 0.875)

    def test_all_failure_journal_is_not_fabricated_as_a_model_result(self):
        cases, ranking = roster()
        selection = selected_for_evaluation(cases, ranking)
        ready, raw, rows, commit = failed_journal(cases, selection)
        checked_generation(cases, {}, selection, ready, raw, rows, commit=commit)
        changed = deepcopy(ready)
        changed["succeeded"] = 1
        with self.assertRaises(ValueError):
            checked_generation(cases, {}, selection, changed, raw, rows, commit=commit)

    def test_raw_model_answer_or_pretrained_identity_cannot_be_rewritten(self):
        cases, ranking = roster()
        selection = selected_for_evaluation(cases, ranking)
        ready, raw, rows, commit = failed_journal(cases, selection)
        modified = deepcopy(rows)
        modified[0]["answer"] = "invented"
        with self.assertRaises(ValueError):
            checked_generation(
                cases, {}, selection, ready, raw, modified, commit=commit
            )
        modified = deepcopy(ready)
        modified["original_gold_accessible_during_generation"] = True
        with self.assertRaises(ValueError):
            checked_generation(cases, {}, selection, modified, raw, rows, commit=commit)

    def test_two_family_proxy_cases_are_not_independent_acceptance(self):
        cases, _, new, old, targets = answers()
        result = pairs(cases, new, old, targets)
        self.assertEqual(len({q["family_proxy_digest"] for q in cases}), 1)
        self.assertTrue(
            result["all"]["bounds_are_missing_outcome_not_statistical_confidence"]
        )
        self.assertNotIn("production_accepted", result)


if __name__ == "__main__":
    unittest.main()
