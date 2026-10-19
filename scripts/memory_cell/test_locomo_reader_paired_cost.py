"""Synthetic paired prompt-cost fixtures; no Qwen weights or target answers."""

from copy import deepcopy
import hashlib
import json
import math
import unittest

from locomo_reader_paired_cost import (
    audit_matched_costs,
    verify_immutable_generation_record,
)


def fixture():
    cases, rows = [], []
    for i in range(16):
        qid = f"evaluation-{i}"
        family = "family-A" if i < 8 else "family-B"
        case = dict(
            question_id=qid,
            family_proxy_digest=family,
            source_census_sha256=f"immutable-source-{i}",
        )
        cases.append(case)
        for k, arm in ((4, "lexical_k4"), (8, "lexical_k8")):
            selected = [f"doc-{j}" for j in range(k)]
            rows.append(
                dict(
                    question_id=qid,
                    arm=arm,
                    family_proxy_digest=family,
                    source_census_sha256=case["source_census_sha256"],
                    selected=selected,
                    status="succeeded",
                    answer="synthetic [E1]",
                    receipt=dict(
                        reader_identity="1" * 64,
                        reader_profile="2" * 64,
                        input_tokens=300 if k == 4 else 440,
                        generated_tokens=8 if k == 4 else 10,
                        seconds=0.4 if k == 4 else 0.65,
                        delivered_evidence=[
                            dict(original_id=doc, excerpt="evidence body " + doc)
                            for doc in selected
                        ],
                    ),
                )
            )
    return cases, rows


def pinned_manifest(rows):
    raw = b"".join(
        json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
        + bytes((10,))
        for row in rows
    )
    return dict(
        schema="hepta.memorycell.locomo-frozen-reader-pair.v1",
        generating_commit="a" * 40,
        original_source_sha256="b" * 64,
        original_six_decisions_sha256="c" * 64,
        raw_journal_sha256=hashlib.sha256(raw).hexdigest(),
        model_stage_sha256="d" * 64,
        model_identity="1" * 64,
        model_profile="2" * 64,
        planned_questions=16,
        planned_arms=["lexical_k4", "lexical_k8"],
        planned_model_calls=32,
        actual_model_calls=32,
        succeeded=sum(row["status"] == "succeeded" for row in rows),
        failed=sum(row["status"] == "failed" for row in rows),
        input_token_ceiling=2048,
        generated_token_ceiling=64,
        weight_updates=0,
        labels_seen_during_generation=False,
        original_answers_rewritten=False,
        semantic_citation_precision=None,
        production_accepted=False,
    ), raw


def check_manifest(manifest, raw, rows):
    return verify_immutable_generation_record(
        manifest,
        raw,
        rows,
        expected_commit="a" * 40,
        public_zip_sha256="b" * 64,
        decisions_zip_sha256="c" * 64,
    )


class ReaderCostTests(unittest.TestCase):
    def test_complete_16_matched_costs_per_family(self):
        cases, rows = fixture()
        result = audit_matched_costs(cases, rows)
        self.assertEqual(result["original_planned_question_pairs"], 16)
        self.assertEqual(result["logical_reader_attempts"], 32)
        self.assertEqual(result["completed_paired_questions"], 16)
        self.assertEqual(result["matched_only_cost"]["mean_extra_prompt_tokens"], 140)
        self.assertAlmostEqual(
            result["matched_only_cost"]["mean_extra_generation_seconds"], 0.25
        )
        self.assertEqual(
            result["per_family_proxy_matched_only"]["family-A"][
                "complete_paired_question_count"
            ],
            8,
        )
        self.assertEqual(
            result["per_family_proxy_matched_only"]["family-B"][
                "complete_paired_question_count"
            ],
            8,
        )
        self.assertFalse(result["independent_source_family_significance"])
        self.assertFalse(result["production_accepted"])

    def test_missing_reader_result_widens_denominator_not_zero_cost(self):
        cases, rows = fixture()
        row = rows[1]
        row.update(status="failed", error_type="PromptBudgetError")
        row.pop("answer")
        row.pop("receipt")
        result = audit_matched_costs(cases, rows)
        self.assertEqual(result["completed_paired_questions"], 15)
        self.assertEqual(result["k4_success_k8_failure"], 1)
        self.assertEqual(result["per_arm"]["lexical_k8"]["failed"], 1)
        self.assertEqual(result["error_type_counts"]["lexical_k8/PromptBudgetError"], 1)
        self.assertTrue(result["missing_pair_costs_not_treated_as_zero"])
        self.assertEqual(len(result["paired_cost_rows"]), 15)

    def test_reverse_failure_and_both_failed_are_accounted(self):
        cases, rows = fixture()
        for index in (0, 2, 3):
            row = rows[index]
            row.update(status="failed", error_type="ValueError")
            row.pop("receipt")
            row.pop("answer")
        result = audit_matched_costs(cases, rows)
        self.assertEqual(result["k8_success_k4_failure"], 1)
        self.assertEqual(result["both_reader_calls_failed"], 1)
        self.assertEqual(result["completed_paired_questions"], 14)
        self.assertEqual(
            result["per_family_proxy_matched_only"]["family-A"][
                "complete_paired_question_count"
            ],
            6,
        )

    def test_detect_changed_prompt_reader_and_source_order(self):
        for key, changed in (
            ("reader_profile", "another-prompt"),
            ("reader_identity", "another-weights"),
            ("selected", ["bad"] * 8),
            ("family_proxy_digest", "borrowed-family"),
        ):
            cases, rows = fixture()
            if key in ("reader_identity", "reader_profile"):
                rows[1]["receipt"][key] = changed
            else:
                rows[1][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_matched_costs(cases, rows)

    def test_success_cost_and_failure_receipt_tampering_rejected(self):
        for corruption in ("nan", "bool", "too_many_tokens", "forged_failure"):
            cases, rows = fixture()
            if corruption == "nan":
                rows[1]["receipt"]["seconds"] = math.nan
            elif corruption == "bool":
                rows[1]["receipt"]["input_tokens"] = True
            elif corruption == "too_many_tokens":
                rows[1]["receipt"]["input_tokens"] = 2049
            else:
                rows[1]["status"] = "failed"
                rows[1]["error_type"] = "PromptBudgetError"
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                audit_matched_costs(cases, rows)

    def test_misaligned_or_incomplete_census_rejected(self):
        cases, rows = fixture()
        for damaged in (rows[:-1], list(reversed(rows)), rows[:-1] + [rows[0]]):
            with self.assertRaisesRegex(ValueError, "census"):
                audit_matched_costs(cases, damaged)
        with self.assertRaisesRegex(ValueError, "census"):
            audit_matched_costs(cases[:-1], rows)

    def test_only_source_bytes_not_citation_or_dollar_cost_is_claimed(self):
        cases, rows = fixture()
        result = audit_matched_costs(cases, rows)
        self.assertTrue(result["source_utf8_bytes_not_actual_prompt_tokens"])
        self.assertTrue(result["generation_time_does_not_include_cold_load"])
        self.assertIsNone(result["independently_adjudicated_citation_precision"])
        self.assertFalse(result["reader_task_gain_measured_by_this_module"])

    def test_source_pins_commit_census_and_bytes_verified_before_scoring(self):
        _, rows = fixture()
        manifest, raw = pinned_manifest(rows)
        result = check_manifest(manifest, raw, rows)
        self.assertEqual(result["actual_completed_answers"], 32)
        self.assertEqual(result["actual_failed_or_rejected_requests"], 0)
        self.assertTrue(result["source_zip_and_decisions_sha256_verified"])
        self.assertFalse(result["production_accepted"])

    def test_forged_raw_journal_commit_or_failure_count_is_rejected(self):
        _, rows = fixture()
        manifest, raw = pinned_manifest(rows)
        for changed in ("commit", "source", "failed", "raw", "model", "budget"):
            x = deepcopy(manifest)
            if changed == "commit":
                x["generating_commit"] = "f" * 40
            elif changed == "source":
                x["original_source_sha256"] = "f" * 64
            elif changed == "failed":
                x["failed"] = 1
            elif changed == "raw":
                raw_corrupted = raw + bytes((10,))
            elif changed == "model":
                x["model_profile"] = "another-reader"
            else:
                x["input_token_ceiling"] = 4096
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                check_manifest(x, raw_corrupted if changed == "raw" else raw, rows)

    def test_mutated_rows_with_unchanged_raw_bytes_cannot_be_scored(self):
        _, rows = fixture()
        manifest, raw = pinned_manifest(rows)
        changed = deepcopy(rows)
        changed[1]["answer"] = "post-hoc cherry-picked answer"
        with self.assertRaisesRegex(ValueError, "immutable raw bytes"):
            check_manifest(manifest, raw, changed)

    def test_real_failure_is_not_a_success_or_a_zero_cost_sample(self):
        _, rows = fixture()
        row = rows[1]
        row["status"] = "failed"
        row["error_type"] = "PromptBudgetError"
        row.pop("answer")
        row.pop("receipt")
        manifest, raw = pinned_manifest(rows)
        outcome = check_manifest(manifest, raw, rows)
        self.assertEqual(outcome["actual_completed_answers"], 31)
        self.assertEqual(outcome["actual_failed_or_rejected_requests"], 1)
        self.assertTrue(outcome["model_executions_not_equated_to_logical_attempts"])


if __name__ == "__main__":
    unittest.main()
