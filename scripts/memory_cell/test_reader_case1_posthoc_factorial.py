"""Adversarial source-only tests; every answer row here is MOCK, not inference."""

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import unittest

from native import digest
from reader_case1_posthoc_factorial import (
    ARMS,
    CASE_ID,
    HYBRID,
    QWEN_INVENTORY,
    SCHEMA,
    SMOL_ID,
    SUPPORT,
    audit_rows,
    choices,
    freeze_manifest_for_case,
    strict,
)


def fixture():
    candidates = list(HYBRID) + (
        ["event_cbfd4ba5_6", "event_cbfd4ba5_0", "event_cbfd4ba5_3"]
    )
    case = dict(
        query=dict(identity=CASE_ID, scope=CASE_ID, content="authored-task"),
        kind="correction",
        candidate_ids=candidates,
        candidate_digest=digest(tuple(candidates)),
        frontier="unchanged-public-source-frontier",
        controls=dict(
            program_support=dict(selected=[SUPPORT]),
            hybrid=dict(selected=list(HYBRID)),
        ),
    )
    docs = {
        key: SimpleNamespace(scope=CASE_ID, content=f"original:{key}")
        for key in candidates
    }
    return case, docs


def single_original_row(case, docs, arm=ARMS[0]):
    selected = list(choices(case, docs)[arm])
    receipt = dict(
        reader_identity=SMOL_ID,
        view_profile="hepta.controlled-event.schema-expansion.v1",
        query_digest=digest(case["query"]),
        token_limit=2048,
        trainable_parameters=0,
        answer_postprocessed=False,
        production_accepted=False,
        input_tokens=110,
        generated_tokens=8,
        input_ids_digest="a" * 64,
        generated_ids_digest="b" * 64,
        reader_profile="c" * 64,
        seconds=0.1,
        delivered_evidence=[
            dict(original_id=key, excerpt=docs[key].content)
            for key in selected
        ],
    )
    return dict(
        question_id=CASE_ID,
        kind="correction",
        candidate_digest=case["candidate_digest"],
        arm=arm,
        selected=selected,
        status="succeeded",
        answer="I do not have enough evidence.",
        receipt=receipt,
        citation_audit=dict(
            request=dict(
                query_id=CASE_ID,
                prompt_digest="a" * 64,
                answer="I do not have enough evidence.",
            ),
            semantic_precision=None,
        ),
    )


def shard(case, docs, *rows):
    manifest = freeze_manifest_for_case(case, choices(case, docs))
    return {
        "case-plan.json": json.dumps(manifest).encode(),
        "raw-answers.jsonl": b"".join(
            (json.dumps(r) + "\n").encode() for r in rows
        ),
    }


class CaseOnePosthocMaskTests(unittest.TestCase):
    def test_all_eight_original_source_inclusion_masks_are_distinct(self):
        case, docs = fixture()
        masks = choices(case, docs)
        self.assertEqual(len(masks), 8)
        self.assertEqual(len(set(masks.values())), 8)
        self.assertEqual(masks[ARMS[0]], (SUPPORT,))
        self.assertEqual(masks[ARMS[-1]], HYBRID)
        for name, selected in masks.items():
            self.assertIn(SUPPORT, selected)
            self.assertEqual(
                selected, tuple(k for k in HYBRID if k in selected)
            )
            self.assertEqual(len(selected), 1 + name.count("1"))

    def test_author_declared_support_is_not_called_human_review(self):
        case, docs = fixture()
        frozen = freeze_manifest_for_case(case, choices(case, docs))
        self.assertTrue(frozen["registered_after_observing_original_answer"])
        self.assertFalse(frozen["author_declared_support_not_human_reviewed"] is False)
        self.assertFalse(frozen["original_eighty_call_matrix_membership"])
        self.assertEqual(frozen["independent_source_family_count"], 0)
        self.assertEqual(frozen["trainable_parameters"], 0)
        self.assertFalse(frozen["production_accepted"])

    def test_any_plan_or_candidate_source_change_fails_closed(self):
        for failure in ("support", "hybrid", "digest", "scope", "kind"):
            with self.subTest(failure=failure):
                case, docs = fixture()
                if failure == "support":
                    case["controls"]["program_support"]["selected"] = [HYBRID[0]]
                if failure == "hybrid":
                    case["controls"]["hybrid"]["selected"].reverse()
                if failure == "digest":
                    case["candidate_digest"] = "0" * 64
                if failure == "scope":
                    docs[SUPPORT].scope = "wrong-scope"
                if failure == "kind":
                    case["kind"] = "procedure"
                with self.assertRaises(ValueError):
                    choices(case, docs)

    def test_duplicate_and_nonfinite_json_rejected(self):
        for value in (b'{"x":1,"x":2}', b'{"y":NaN}', b'{"z":Infinity}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                strict(value)

    def test_no_model_journal_does_not_invent_generations(self):
        case, docs = fixture()
        result = audit_rows(
            {}, case=case, docs=docs,
            tier="smol-1.7b", checkout="1" * 40
        )
        self.assertEqual(result["attempted"], 0)
        self.assertFalse(result["complete"])

    def test_raw_answer_without_frozen_plan_is_illegal(self):
        case, docs = fixture()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            audit_rows(
                {"raw-answers.jsonl": b"{}\n"},
                case=case, docs=docs, tier="smol-1.7b", checkout="1" * 40
            )

    def test_one_synthetic_row_cannot_claim_eight_model_calls(self):
        case, docs = fixture()
        files = shard(case, docs, single_original_row(case, docs))
        result = audit_rows(
            files, case=case, docs=docs,
            tier="smol-1.7b", checkout="1" * 40
        )
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["succeeded"], 1)
        self.assertFalse(result["complete"])

    def test_original_model_identity_cannot_be_swapped(self):
        case, docs = fixture()
        forged = single_original_row(case, docs)
        forged["receipt"]["reader_identity"] = QWEN_INVENTORY
        with self.assertRaises(ValueError):
            audit_rows(
                shard(case, docs, forged), case=case, docs=docs,
                tier="smol-1.7b", checkout="1" * 40
            )

    def test_prompt_or_delivered_source_forgery_is_rejected(self):
        for error in ("prompt", "source", "citation", "budget"):
            with self.subTest(error=error):
                case, docs = fixture()
                forged = single_original_row(case, docs)
                if error == "prompt":
                    forged["receipt"]["input_ids_digest"] = "d" * 64
                if error == "source":
                    forged["receipt"]["delivered_evidence"][0]["excerpt"] = "fake"
                if error == "citation":
                    forged["citation_audit"]["request"]["answer"] = "rewritten"
                if error == "budget":
                    forged["receipt"]["generated_tokens"] = 10000
                with self.assertRaises(ValueError):
                    audit_rows(
                        shard(case, docs, forged), case=case, docs=docs,
                        tier="smol-1.7b", checkout="1" * 40
                    )

    def test_changed_arm_order_and_gold_scores_are_illegal(self):
        for error in ("arm", "gold", "selected"):
            with self.subTest(error=error):
                case, docs = fixture()
                forged = single_original_row(case, docs)
                if error == "arm":
                    forged["arm"] = ARMS[1]
                if error == "gold":
                    forged["strict_task_success"] = True
                if error == "selected":
                    forged["selected"] = list(HYBRID)
                with self.assertRaises(ValueError):
                    audit_rows(
                        shard(case, docs, forged), case=case, docs=docs,
                        tier="smol-1.7b", checkout="1" * 40
                    )

    def test_run_receipt_must_match_actual_raw_shard(self):
        case, docs = fixture()
        files = shard(case, docs, single_original_row(case, docs))
        files["run.json"] = b'{"attempted":8}\n'
        with self.assertRaises(ValueError):
            audit_rows(
                files, case=case, docs=docs,
                tier="smol-1.7b", checkout="1" * 40
            )


if __name__ == "__main__":
    unittest.main()
