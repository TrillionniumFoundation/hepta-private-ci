"""Leakage, contradiction and source-boundary checks for free-text integration."""

from dataclasses import replace
import unittest

import torch

from .open_domain import (DevelopmentCase, GenerationRequest, independent_development_score,
                          public_documentation_cases, text_public_input, validate_source_isolation)


class OpenDomainContractTests(unittest.TestCase):
    def test_source_reuse_across_roles_is_rejected(self):
        cases = public_documentation_cases()
        reused = replace(cases[-1], request=replace(cases[-1].request, source_id=cases[0].request.source_id))
        with self.assertRaisesRegex(ValueError, "both fit and evaluation"):
            validate_source_isolation([*cases[:-1], reused])

    def test_reference_never_enters_generation_request(self):
        request = GenerationRequest("a", "Explain this source.", "A real source passage.", "source-a")
        case = DevelopmentCase(request, "fit", "FORBIDDEN_REFERENCE_SENTINEL", ())
        public = text_public_input(case.request)
        decoded = bytes(public["tokens"][0].tolist()).decode("ascii")
        self.assertNotIn(case.reference, case.request.prompt() + decoded)
        self.assertEqual(tuple(case.request.__dataclass_fields__), ("case_id", "question", "context", "source_id"))
        self.assertEqual({m: int(public[m + "_mask"].count_nonzero()) for m in ("image", "audio", "video")},
                         {"image": 0, "audio": 0, "video": 0})

    def test_same_keywords_with_negated_semantics_do_not_pass(self):
        case = next(c for c in public_documentation_cases() if c.request.case_id == "statistics.mean")
        good = independent_development_score(case, "It computes the arithmetic average and raises StatisticsError for empty data.")
        wrong = independent_development_score(case, "It computes the arithmetic mean but does not raise StatisticsError for empty data.")
        self.assertEqual((good["all_fixed_facts_without_flagged_contradiction"],
                          wrong["all_fixed_facts_without_flagged_contradiction"]), (True, False))

    def test_synonyms_and_wrong_return_type_are_distinguished(self):
        case = next(c for c in public_documentation_cases() if c.request.case_id == "csv.reader")
        texts = ("It gives an iterator that returns one CSV row at a time.",
                 "It returns the entire file as one iterator row.")
        self.assertEqual([independent_development_score(case, text)["all_fixed_facts_without_flagged_contradiction"]
                          for text in texts], [True, False])

    def test_text_encoding_is_content_sensitive_and_bounded(self):
        a = GenerationRequest("a", "Question?", "First passage.", "a")
        b = replace(a, context="Different text.")
        left, right = text_public_input(a), text_public_input(b)
        self.assertFalse(torch.equal(left["tokens"], right["tokens"]))
        with self.assertRaisesRegex(ValueError, "input bound"):
            text_public_input(replace(a, context="x" * 2049))

    def test_non_development_role_is_rejected(self):
        case = public_documentation_cases()[0]
        with self.assertRaisesRegex(ValueError, "public development"):
            validate_source_isolation([replace(case, role="fresh_calibration")])


if __name__ == "__main__":
    unittest.main()
