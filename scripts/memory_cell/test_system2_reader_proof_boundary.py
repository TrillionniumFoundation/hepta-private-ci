"""Hermetic post-seal and certified-output safety tests (no model inference)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from system2_multihop_evidence import choose, fixed_cases, join_path
from system2_multihop_trial import ABSTAIN
from system2_reader_proof_boundary import authenticated_rows, audit, proof_boundary, run

ROOT = Path(__file__).resolve().parent
# Parent archives are supplied by the caller in hosted CI. Optional local
# archive-backed tests are explicitly skipped if neither is present.
ORIG = ROOT / "hosted-original-100.zip"
PROMPT = ROOT / "hosted-prompt-180.zip"


class ProofBoundaryTests(unittest.TestCase):
    def test_verified_path_produces_bound_citations_without_model_credit(self):
        c = fixed_cases(1)[0]
        selected = choose("joined_top3", c.question, c.documents)
        out = proof_boundary(c.question, selected, "Answer: " + c.answer)
        self.assertEqual(out["action"], "certified_system_answer")
        self.assertEqual(out["accepted_model_token"], c.answer)
        self.assertEqual(out["proof_source_ids"], list(c.required_ids))
        self.assertTrue(out["system_added_citations"])
        self.assertFalse(out["neural_generated_bracketed_citations"])
        self.assertEqual(out["answer"].split()[0], c.answer)
        self.assertEqual(len(out["answer"].split()) - 1, c.hops)

    def test_missing_first_link_rejects_correct_literal(self):
        c = fixed_cases(1)[0]
        s = choose("premise_removed", c.question, c.documents)
        o = proof_boundary(c.question, s, c.answer)
        self.assertEqual(o["action"], "system_abstain")
        self.assertEqual(o["answer"], ABSTAIN)
        self.assertEqual(o["rejection_reason"], "no_verifiable_relation_chain")
        self.assertFalse(o["system_added_citations"])

    def test_empty_evidence_refuses_even_if_model_guessed_correct_token(self):
        c = fixed_cases(1)[0]
        o = proof_boundary(c.question, (), c.answer)
        self.assertEqual(o["action"], "system_abstain")
        self.assertFalse(o["path_complete"])

    def test_wrong_token_with_complete_proof_is_rejected(self):
        c = fixed_cases(1)[0]
        s = choose("joined_top3", c.question, c.documents)
        self.assertTrue(join_path(c.question, s))
        o = proof_boundary(c.question, s, "TOK-0000000")
        self.assertEqual(o["rejection_reason"], "model_token_not_entailed")

    def test_two_token_occurrences_are_ambiguous_even_if_same(self):
        c = fixed_cases(1)[0]
        s = choose("joined_top3", c.question, c.documents)
        o = proof_boundary(c.question, s, c.answer + " then " + c.answer)
        self.assertEqual(o["rejection_reason"], "ambiguous_model_token")
        self.assertEqual(o["model_token_occurrences"], 2)

    def test_no_output_does_not_fabricate_a_negative_label(self):
        c = fixed_cases(1)[0]
        for bad in ("", "  ", None):
            with self.assertRaises(ValueError):
                proof_boundary(c.question, (), bad)

    def test_fabricated_bracketed_reference_is_not_accepted_without_path(self):
        c = fixed_cases(1)[0]
        s = choose("premise_removed", c.question, c.documents)
        o = proof_boundary(c.question, s, c.answer + " [E1] [E2] [E3]")
        self.assertTrue(o["neural_generated_bracketed_citations"])
        self.assertFalse(o["system_added_citations"])
        self.assertEqual(o["action"], "system_abstain")

    def test_scope_and_future_source_fail_closed(self):
        from dataclasses import replace

        c = fixed_cases(1)[0]
        s = choose("joined_top3", c.question, c.documents)
        with self.assertRaises(ValueError):
            proof_boundary(
                c.question, [replace(s[0], scope="other")] + list(s[1:]), c.answer
            )
        with self.assertRaises(ValueError):
            proof_boundary(
                c.question,
                [replace(s[0], observed_at="2099-01-01")] + list(s[1:]),
                c.answer,
            )

    def test_adversarial_quote_cannot_become_a_parsed_relation(self):
        c = fixed_cases(4)[3]
        selected = choose("joined_top3", c.question, c.documents)
        attack = next(d for d in c.documents if "Ignore all previous" in d.content)
        o = proof_boundary(c.question, selected + (attack,), "TOK-FAKE99")
        self.assertEqual(o["action"], "system_abstain")
        self.assertFalse(o["system_added_citations"])

    def test_source_identity_not_neural_citation_order(self):
        c = fixed_cases(1)[0]
        selected = choose("joined_top3", c.question, c.documents)[::-1]
        o = proof_boundary(c.question, selected, c.answer)
        self.assertEqual(o["action"], "certified_system_answer")
        self.assertEqual(o["proof_source_ids"], list(c.required_ids))
        self.assertTrue(o["answer"].startswith(c.answer + " [E3] [E2]"))

    def test_raw_answers_stay_separate_from_boundary_outputs(self):
        c = fixed_cases(1)[0]
        selected = choose("joined_top3", c.question, c.documents)
        raw = "Reader said " + c.answer
        o = proof_boundary(c.question, selected, raw)
        self.assertEqual(raw, "Reader said " + c.answer)
        self.assertNotEqual(o["answer"], raw)
        self.assertFalse(o["independent_language_semantics_established"])

    @unittest.skipUnless(
        ORIG.is_file() and PROMPT.is_file(), "hosted archives not staged"
    )
    def test_two_source_archives_and_recomputed_prompt_scores(self):
        source = authenticated_rows(PROMPT, ORIG)
        self.assertEqual(
            source["sealed_sha256"],
            "2782f91d086c81bbd8434ff64b6533dbb57666acced0217af60b1899b146aa4e",
        )
        self.assertEqual(len(source["rows"]), 240)
        self.assertEqual(len(source["cases"]), 20)
        self.assertEqual(len(source["profiles"]), 3)
        self.assertEqual(source["manifest_entries"], 24)
        result = audit(source)
        self.assertEqual(len(result["group_results"]), 12)
        self.assertEqual(len(result["per_question_results"]), 240)
        by = {(g["prompt_variant"], g["arm"]): g for g in result["group_results"]}
        self.assertEqual(by["compact", "joined_top3"]["verified"], 15)
        self.assertEqual(
            by["compact", "premise_removed"]["unsupported_target_copy"], 10
        )
        self.assertEqual(by["direct", "no_evidence"]["JSON_echo"], 20)
        self.assertEqual(by["demonstrated", "joined_top3"]["ceiling"], 20)
        self.assertFalse(result["neural_reader_accuracy_improved"])

    @unittest.skipUnless(
        ORIG.is_file() and PROMPT.is_file(), "hosted archives not staged"
    )
    def test_output_is_a_deterministic_readonly_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "receipt.json"
            result = run(ORIG, PROMPT, p)
            self.assertEqual(json.loads(p.read_text()), result)
            with self.assertRaises(ValueError):
                run(ORIG, PROMPT, p)
            self.assertFalse(result["production_accepted"])

    @unittest.skipUnless(
        ORIG.is_file() and PROMPT.is_file(), "hosted archives not staged"
    )
    def test_outer_archive_tamper_rejected_before_writing_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "modified.zip"
            path.write_bytes(PROMPT.read_bytes() + b"X")
            out = Path(tmp) / "out.json"
            with self.assertRaises(ValueError):
                run(ORIG, path, out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
