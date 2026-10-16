"""Negative checks for original-score reader verification."""

import unittest

from offline_smol_reader import digest
from verify_reader_candidate_capacity import validate_choice_scores


class DummyTokenizer:
    def encode(self, text):
        return [1, 2]


def evidence():
    names = ("site_11111111", "site_22222222")
    rows = [
        dict(
            value=name,
            token_count=2,
            token_digest=digest([1, 2]),
            log_likelihood=-float(n + 1),
            mean_log_likelihood=-float(n + 1) / 2,
        )
        for n, name in enumerate(names)
    ]
    return names, dict(candidates=rows, ranking=list(names), chosen=names[0])


class ScoreReplayTests(unittest.TestCase):
    def test_exact_scorer_receipt(self):
        names, row = evidence()
        validate_choice_scores(row, names, DummyTokenizer())

    def test_reject_changed_candidate_and_ranking(self):
        for field, value in (
            ("chosen", "site_22222222"),
            ("ranking", ["site_22222222", "site_11111111"]),
        ):
            names, row = evidence()
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_choice_scores(row, names, DummyTokenizer())
        names, row = evidence()
        row["candidates"][0]["value"] = "site_ffffffff"
        with self.assertRaises(ValueError):
            validate_choice_scores(row, names, DummyTokenizer())

    def test_reject_nonfinite_or_tampered_likelihood(self):
        for value in (float("nan"), float("inf"), 1.0, -100.0):
            names, row = evidence()
            row["candidates"][0]["mean_log_likelihood"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_choice_scores(row, names, DummyTokenizer())


if __name__ == "__main__":
    unittest.main()
