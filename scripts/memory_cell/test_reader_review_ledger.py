"""Signed per-question review-census invariants, not human semantic judgment."""

import copy
from pathlib import Path
import tempfile
import unittest

from full_cell_matrix import evaluate_reader_gate, plan
from reader_review_ledger import audit_case_ledger
from test_full_cell_matrix import fingerprint, gate_fixture, original_fixture


class SignedReaderCaseLedgerTests(unittest.TestCase):
    def setUp(self):
        self.gate, self.manifest, self.roster = gate_fixture()

    def audit(self, gate=None):
        data = gate if gate is not None else self.gate
        return audit_case_ledger(
            data["cohort"],
            data["conditions"],
            data.get("reviewed_items"),
        )

    def test_complete_four_arm_case_ledger_reconciles_to_counts(self):
        self.assertIsNone(self.audit())
        self.assertEqual(len(self.gate["reviewed_items"]), 80)
        self.assertTrue(
            evaluate_reader_gate(
                self.gate,
                self.manifest,
                trusted_review_sha256=fingerprint(self.manifest),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
                original_sources=original_fixture(self.gate),
                trusted_originals_sha256=fingerprint(original_fixture(self.gate)),
            ).passed
        )

    def test_aggregate_only_self_review_is_rejected_even_with_old_signature(self):
        old = copy.deepcopy(self.gate)
        del old["reviewed_items"]
        self.assertEqual(
            evaluate_reader_gate(
                old,
                self.manifest,
                trusted_review_sha256=fingerprint(self.manifest),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
            ).reason,
            "missing-case-level-review-ledger",
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = plan(
                Path(tmp),
                reader_gate=old,
                trust_manifest=self.manifest,
                trusted_review_sha256=fingerprint(self.manifest),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
            )
        self.assertEqual(
            (result["blocked_reader_records"], result["planned_neural_records"]),
            (768, 0),
        )

    def test_partial_case_list_is_not_implicitly_a_negative_example(self):
        rows = self.gate["reviewed_items"]
        self.gate["reviewed_items"] = rows[:-1]
        self.assertEqual(self.audit(), "missing-or-incomplete-case-review-ledger")

    def test_duplicate_item_cannot_replace_an_unreviewed_question(self):
        self.gate["reviewed_items"][-1] = copy.deepcopy(self.gate["reviewed_items"][0])
        self.assertEqual(self.audit(), "duplicate-or-unregistered-reviewed-case")

    def test_boolean_verdict_must_be_boolean_not_integer(self):
        self.gate["reviewed_items"][0]["grounded_and_cited"] = 0
        self.assertEqual(self.audit(), "invalid-reviewed-verdict-type")

    def test_non_sha_answer_and_prompt_receipts_fail(self):
        for field in (
            "raw_answer_sha256",
            "prompt_input_ids_sha256",
            "question_sha256",
        ):
            with self.subTest(field=field):
                variant = copy.deepcopy(self.gate)
                variant["reviewed_items"][0][field] = "not-a-digest"
                self.assertEqual(
                    self.audit(variant), "unbound-reviewed-question-prompt-or-answer"
                )

    def test_question_fingerprint_must_remain_same_across_all_conditions(self):
        self.gate["reviewed_items"][20]["question_sha256"] = "f" * 64
        self.assertEqual(
            self.audit(), "question-identity-changed-across-review-conditions"
        )

    def test_delivered_evidence_cannot_be_credited_in_no_evidence(self):
        self.gate["reviewed_items"][0]["delivered_source_sha256"] = ["a" * 64]
        self.assertEqual(self.audit(), "no-evidence-condition-delivered-source")

    def test_grounded_claim_requires_cited_original_source(self):
        row = next(
            x
            for x in self.gate["reviewed_items"]
            if x["condition"] == "human_sufficient" and x["grounded_and_cited"]
        )
        row["cited_source_sha256"] = []
        self.assertEqual(self.audit(), "grounded-verdict-without-valid-source-citation")
        row["cited_source_sha256"] = ["f" * 64]
        self.assertEqual(self.audit(), "citation-not-bound-to-delivered-source")

    def test_duplicate_source_or_citation_fingerprint_is_rejected(self):
        row = next(
            x
            for x in self.gate["reviewed_items"]
            if x["condition"] == "human_sufficient"
        )
        row["delivered_source_sha256"].append(row["delivered_source_sha256"][0])
        self.assertEqual(self.audit(), "invalid-reviewed-source-fingerprints")

    def test_premise_is_actually_removed_from_reviewed_source_set(self):
        rows = self.gate["reviewed_items"]
        human = next(x for x in rows if x["condition"] == "human_sufficient")
        removed = next(x for x in rows if x["condition"] == "critical_premise_removed")
        removed["delivered_source_sha256"] = list(human["delivered_source_sha256"])
        self.assertEqual(self.audit(), "critical-premise-not-actually-removed")

    def test_removed_premise_must_not_inject_an_additional_source(self):
        row = next(
            x
            for x in self.gate["reviewed_items"]
            if x["item_id"] == self.gate["cohort"][0]
            and x["condition"] == "critical_premise_removed"
        )
        row["delivered_source_sha256"].append("f" * 64)
        self.assertEqual(self.audit(), "critical-premise-not-actually-removed")

    def test_removed_premise_must_not_swap_in_a_different_source(self):
        row = next(
            x
            for x in self.gate["reviewed_items"]
            if x["item_id"] == self.gate["cohort"][0]
            and x["condition"] == "critical_premise_removed"
        )
        row["delivered_source_sha256"] = ["f" * 64]
        self.assertEqual(self.audit(), "critical-premise-not-actually-removed")

    def test_false_aggregate_is_rejected_even_when_row_schema_is_valid(self):
        self.gate["conditions"]["human_sufficient"]["grounded_and_cited"] = 19
        self.assertEqual(
            self.audit(), "review-ledger-aggregate-disagrees-with-signed-cases"
        )

    def test_case_raw_answer_change_breaks_pinned_signature_content(self):
        self.gate["reviewed_items"][0]["raw_answer_sha256"] = "f" * 64
        self.assertIsNone(self.audit())
        self.assertEqual(
            evaluate_reader_gate(
                self.gate,
                self.manifest,
                trusted_review_sha256=fingerprint(self.manifest),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
            ).reason,
            "review-not-bound-to-observed-reader-results",
        )

    def test_invalid_unhashable_question_denominator_fails_closed(self):
        malformed = copy.deepcopy(self.gate)
        malformed["cohort"] = [{"unhashable": True}]
        self.assertEqual(
            evaluate_reader_gate(malformed).reason, "invalid-reader-cohort"
        )

    def test_float_condition_total_cannot_pass_integer_census(self):
        self.gate["conditions"]["human_sufficient"]["total"] = 20.0
        self.assertEqual(
            evaluate_reader_gate(self.gate).reason,
            "reader-arm-denominator-or-cohort-mismatch",
        )

    def test_refusal_and_grounded_claim_cannot_both_hold(self):
        row = next(
            x
            for x in self.gate["reviewed_items"]
            if x["condition"] == "human_sufficient" and x["grounded_and_cited"]
        )
        row["exact_refusal"] = True
        self.assertEqual(self.audit(), "grounded-verdict-without-valid-source-citation")

    def test_extra_arbitrary_fields_do_not_silently_change_review_grammar(self):
        self.gate["reviewed_items"][0]["reviewer_guess"] = True
        self.assertEqual(self.audit(), "invalid-case-review-row-schema")

    def test_signed_case_ledger_cannot_bypass_missing_original_bytes(self):
        self.assertEqual(
            evaluate_reader_gate(
                self.gate,
                self.manifest,
                trusted_review_sha256=fingerprint(self.manifest),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
            ).reason,
            "out-of-band-originals-required",
        )
        with tempfile.TemporaryDirectory() as tmp:
            summary = plan(
                Path(tmp),
                reader_gate=self.gate,
                trust_manifest=self.manifest,
                trusted_review_sha256=fingerprint(self.manifest),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
            )
        self.assertEqual(
            (
                summary["blocked_reader_records"],
                summary["planned_neural_records"],
                summary["neural_calls"],
            ),
            (768, 0, 0),
        )

    def test_original_owner_pin_mismatch_is_not_readable_neural_evidence(self):
        originals = original_fixture(self.gate)
        originals["items"][0]["input_ids"][0] += 1
        self.assertEqual(
            evaluate_reader_gate(
                self.gate,
                self.manifest,
                trusted_review_sha256=fingerprint(self.manifest),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
                original_sources=originals,
                trusted_originals_sha256=fingerprint(originals),
            ).reason,
            "original-evidence-pin-mismatch",
        )

    def test_reapproved_source_pin_still_cannot_forge_actual_prompt_or_answer(self):
        originals = original_fixture(self.gate)
        originals["items"][0]["raw_answer"] = "changed after reviewer signed"
        trust = copy.deepcopy(self.manifest)
        trust["originals_sha256"] = fingerprint(originals)
        gate = copy.deepcopy(self.gate)
        gate["independent_review"]["trust_manifest_sha256"] = fingerprint(trust)
        self.assertEqual(
            evaluate_reader_gate(
                gate,
                trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
                original_sources=originals,
                trusted_originals_sha256=fingerprint(originals),
            ).reason,
            "original-question-prompt-answer-or-citation-drift",
        )

    def test_reapproved_source_pin_must_preserve_byte_scope_and_asof_cut(self):
        originals = original_fixture(self.gate)
        source = next(
            item["delivered_sources"][0]
            for item in originals["items"]
            if item["condition"] == "human_sufficient"
        )
        source["scope"] = "unauthorized"
        trust = copy.deepcopy(self.manifest)
        trust["originals_sha256"] = fingerprint(originals)
        gate = copy.deepcopy(self.gate)
        gate["independent_review"]["trust_manifest_sha256"] = fingerprint(trust)
        self.assertEqual(
            evaluate_reader_gate(
                gate,
                trust,
                trusted_review_sha256=fingerprint(trust),
                reviewer_roster=self.roster,
                trusted_roster_sha256=fingerprint(self.roster),
                original_sources=originals,
                trusted_originals_sha256=fingerprint(originals),
            ).reason,
            "original-source-scope-time-or-identity-invalid",
        )


if __name__ == "__main__":
    unittest.main()
