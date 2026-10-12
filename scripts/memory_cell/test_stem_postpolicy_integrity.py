"""Synthetic attack fixtures for 576-case post-policy scorer provenance."""

from dataclasses import asdict, replace
from types import SimpleNamespace as Obj
import copy
import unittest

from native import Question, Target, digest
from stem_postpolicy_integrity import (
    audit_policy_scoring, _diagnostic_f1, _expected_evidence,
)

PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)
ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")


class Pool:
    def __init__(self, scope):
        self.windows = (
            Obj(
                source_id="positive-" + scope, root="root", scope=scope,
                observed_at="2023-01-01", start=0, end=4,
                text="Blue", inspected_sha256="sha-source",
                identity=lambda: "window-id-positive-" + scope,
            ),
            Obj(
                source_id="distractor-" + scope, root="root", scope=scope,
                observed_at="2023-01-01", start=0, end=3,
                text="Red", inspected_sha256="sha-distractor",
                identity=lambda: "window-id-negative-" + scope,
            ),
        )

    def seal(self):
        return "fixed-pool-" + self.windows[0].scope


def fixture():
    qs = {phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES}
    plan = dict(
        arms=list(ARMS), curriculum_attempted_examples=list(STAGES),
        questions=qs, question_families={q: "family-" + q for p in PHASES for q in qs[p]},
    )
    questions = {
        q: Question(q, "source-group", "scope-" + q, "What color?", "2024-01-01")
        for phase in PHASES for q in qs[phase]
    }
    pools = {q: Pool(questions[q].scope) for q in questions}
    targets = {
        q: Target("Blue", "fixture", ("positive-" + questions[q].scope,), False)
        for q in questions
    }
    raw = []
    for stage in STAGES:
        for phase in PHASES:
            for qid in qs[phase]:
                query = questions[qid]
                pool = pools[qid]
                evidence = _expected_evidence(pool, 0)
                receipt = dict(
                    delivered_evidence=evidence, observable_query=asdict(query),
                    generator_identity="frozen-reader-v1",
                    generator_profile="frozen-prompt-v1",
                    canonical_request_digest=digest((
                        "frozen-reader-v1", "frozen-prompt-v1",
                        asdict(query), evidence,
                    )),
                    question_digest=digest(asdict(query)),
                    input_ids_digest="a" * 64,
                    generated_ids_digest="b" * 64,
                    actual_reader_execution=True,
                    reused_from=None,
                )
                for arm in ARMS:
                    raw.append(dict(
                        stage=stage, phase=phase, question_id=qid, arm=arm,
                        status="succeeded", family=plan["question_families"][qid],
                        selected=0, pool_digest=pool.seal(),
                        answer="Blue. [E1]", receipt=copy.deepcopy(receipt),
                    ))
    return plan, raw, score(raw, targets), pools, questions, targets


def score(raw, targets):
    scored = []
    for row in raw:
        qid = row["question_id"]
        if row["status"] == "failed":
            scored.append(dict(
                row, source_choice_correct=1 if "selected" in row else 0,
                diagnostic_answer_f1=0.0,
                citation_structure=dict(
                    markers=0, delivered_markers=0,
                    precision=None, semantic_precision=None,
                ),
            ))
        else:
            scored.append(dict(
                row, source_choice_correct=1,
                diagnostic_answer_f1=_diagnostic_f1(row["answer"], targets[qid]),
                citation_structure=dict(
                    markers=1, delivered_markers=1,
                    precision=1.0, semantic_precision=None,
                ),
            ))
    return scored


class PolicyIntegrityTests(unittest.TestCase):
    def test_complete_576_case_native_support_and_citation_receipts(self):
        result = audit_policy_scoring(*fixture())
        self.assertEqual(result["raw_policy_attempts"], 576)
        self.assertEqual(result["census"]["reader_success"], 576)
        self.assertEqual(result["census"]["source_scored"], 576)
        self.assertEqual(result["census"]["delivered_markers"], 576)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["independent_citation_quality_verified"])

    def test_raw_prediction_mutation_after_scoring_rejected(self):
        a, b, c, d, e, f = fixture()
        c[0]["answer"] = "Changed answer, target-dependent."
        with self.assertRaisesRegex(ValueError, "rewritten"):
            audit_policy_scoring(a, b, c, d, e, f)

    def test_forged_native_support_score_rejected(self):
        a, b, c, d, e, f = fixture()
        c[0]["source_choice_correct"] = 0
        with self.assertRaisesRegex(ValueError, "native source correctness"):
            audit_policy_scoring(a, b, c, d, e, f)

    def test_forged_citation_precision_rejected(self):
        a, b, c, d, e, f = fixture()
        c[0]["citation_structure"]["semantic_precision"] = 1.0
        with self.assertRaisesRegex(ValueError, "citation count"):
            audit_policy_scoring(a, b, c, d, e, f)

    def test_future_source_in_candidate_pool_is_rejected_even_if_unused(self):
        a, b, c, d, e, f = fixture()
        pool = d["test-1"]
        pool.windows[1].observed_at = "2025-01-01"
        with self.assertRaisesRegex(ValueError, "future or cross-scope"):
            audit_policy_scoring(a, b, c, d, e, f)

    def test_failed_reader_preserves_prior_correct_source_decision(self):
        a, b, c, d, e, f = fixture()
        b[0]["status"] = "failed"
        del b[0]["answer"]
        del b[0]["receipt"]
        c[0] = dict(
            b[0], source_choice_correct=1, diagnostic_answer_f1=0.0,
            citation_structure=dict(
                markers=0, delivered_markers=0,
                precision=None, semantic_precision=None,
            ),
        )
        result = audit_policy_scoring(a, b, c, d, e, f)
        self.assertEqual(result["census"]["reader_failed"], 1)
        self.assertEqual(result["census"]["source_scored"], 576)

    def test_unanswerable_never_counts_selected_evidence_as_correct_refusal(self):
        a, b, c, d, e, f = fixture()
        qid = "test-0"
        f[qid] = replace(f[qid], unanswerable=True)
        for item in c:
            if item["question_id"] == qid:
                item["source_choice_correct"] = 0
        result = audit_policy_scoring(a, b, c, d, e, f)
        self.assertEqual(result["census"]["native_unanswerable_attempts"], 18)

    def test_unresolved_support_remains_null_not_a_success(self):
        a, b, c, d, e, f = fixture()
        qid = "transfer-0"
        f[qid] = replace(f[qid], unresolved_evidence=("unseen",))
        for item in c:
            if item["question_id"] == qid:
                item["source_choice_correct"] = None
        out = audit_policy_scoring(a, b, c, d, e, f)
        self.assertEqual(out["census"]["source_unresolved"], 18)

    def test_missing_duplicate_and_heldout_extra_rows_rejected(self):
        for corrupt in ("missing", "duplicate", "extra"):
            a, b, c, d, e, f = fixture()
            if corrupt == "missing":
                b.pop()
            elif corrupt == "duplicate":
                b[-1] = dict(b[0])
            else:
                c[-1]["question_id"] = "leaked-training"
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                audit_policy_scoring(a, b, c, d, e, f)

    def test_changed_reader_request_or_source_excerpt_is_not_accepted(self):
        for key in ("generator_profile", "delivered_evidence"):
            a, b, c, d, e, f = fixture()
            b[0]["receipt"][key] = (
                "mismatched" if key == "generator_profile" else []
            )
            c[0] = dict(b[0], **{x: c[0][x] for x in (
                "source_choice_correct", "diagnostic_answer_f1",
                "citation_structure",
            )})
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_policy_scoring(a, b, c, d, e, f)


    def test_forged_reader_identity_and_prompt_cannot_evade_by_rehashing(self):
        for field in ("generator_identity", "generator_profile"):
            a, b, c, d, e, f = fixture()
            x = b[0]["receipt"]
            x[field] = "alternate-reader"
            x["canonical_request_digest"] = digest((
                x["generator_identity"], x["generator_profile"],
                x["observable_query"], x["delivered_evidence"],
            ))
            c[0] = dict(b[0], **{
                k: c[0][k] for k in (
                    "source_choice_correct", "diagnostic_answer_f1",
                    "citation_structure",
                )
            })
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "Reader prompt, model"
            ):
                audit_policy_scoring(a, b, c, d, e, f)

    def test_bad_token_or_question_digest_or_cache_reuse_rejected(self):
        for field, bad in (
            ("input_ids_digest", "fake"),
            ("generated_ids_digest", "fake"),
            ("question_digest", "0" * 64),
            ("actual_reader_execution", False),
            ("reused_from", "previous-execution"),
        ):
            a, b, c, d, e, f = fixture()
            b[0]["receipt"][field] = bad
            c[0] = dict(b[0], **{
                k: c[0][k] for k in (
                    "source_choice_correct", "diagnostic_answer_f1",
                    "citation_structure",
                )
            })
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "Reader prompt, model"
            ):
                audit_policy_scoring(a, b, c, d, e, f)

    def test_identical_request_cannot_change_answer_or_decoded_token_digest(self):
        a, b, c, d, e, f = fixture()
        other = b[1]
        self.assertEqual(
            b[0]["receipt"]["canonical_request_digest"],
            other["receipt"]["canonical_request_digest"],
        )
        other["answer"] = "Red. [E1]"
        other["receipt"]["generated_ids_digest"] = "c" * 64
        c[1] = dict(other, **{
            "source_choice_correct": 1,
            "diagnostic_answer_f1": _diagnostic_f1(other["answer"], f[other["question_id"]]),
            "citation_structure": c[1]["citation_structure"],
        })
        with self.assertRaisesRegex(ValueError, "inconsistent raw answer"):
            audit_policy_scoring(a, b, c, d, e, f)

    def test_original_cache_reuse_is_valid_if_receipt_and_answer_match(self):
        a, b, c, d, e, f = fixture()
        b[1]["receipt"]["actual_reader_execution"] = False
        b[1]["receipt"]["reused_from"] = "16/select/q/frozen_rerank"
        c[1] = dict(b[1], **{
            k: c[1][k] for k in (
                "source_choice_correct", "diagnostic_answer_f1",
                "citation_structure",
            )
        })
        receipt = audit_policy_scoring(a, b, c, d, e, f)
        self.assertTrue(
            receipt["identical_reader_requests_yield_identical_answer_and_token_ids"]
        )


if __name__ == "__main__":
    unittest.main()
