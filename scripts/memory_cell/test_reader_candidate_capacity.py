"""Reader scoring and answer-space/original-source failure regressions."""

import json
import unittest

import torch

from reader_candidate_capacity import candidates, candidate_score, CHOICE


def source(identity, value, *, scope="scope_a", observed_at="2026-10-01T00:00:00Z"):
    return dict(
        identity=identity,
        scope=scope,
        observed_at=observed_at,
        content=json.dumps(
            dict(
                schema="hepta.controlled-event.v1",
                id=identity,
                value=value,
            )
        ),
    )


class ReaderCandidateCapacityTests(unittest.TestCase):
    def setUp(self):
        self.case = dict(
            query=dict(
                identity="question_a",
                scope="scope_a",
                observed_at="2026-10-15T00:00:00Z",
            )
        )
        self.sources = {
            "one": source("one", "site_11111111"),
            "two": source("two", "site_22222222"),
            "three": source("three", "site_33333333"),
        }

    def test_answer_space_has_multiple_label_free_distractors(self):
        values = candidates(self.case, self.sources)
        self.assertEqual(
            set(values),
            {
                "site_11111111",
                "site_22222222",
                "site_33333333",
            },
        )
        self.assertTrue(all(CHOICE.fullmatch(value) for value in values))
        self.assertEqual(candidates(self.case, self.sources), values)

    def test_isolate_other_scope_distractors(self):
        baseline = candidates(self.case, self.sources)
        changed = self.sources | {
            "outside": source("outside", "site_ffffffff", scope="other")
        }
        self.assertEqual(candidates(self.case, changed), baseline)

    def test_future_calendar_observation_fails_closed(self):
        changed = self.sources | {
            "one": source("one", "site_11111111", observed_at="2999-01-01T00:00:00Z")
        }
        with self.assertRaisesRegex(ValueError, "future source"):
            candidates(self.case, changed)

    def test_candidate_likelihood_uses_actual_logits_each_step(self):
        class Tokenizer:
            def encode(self, phrase):
                return [1, 2, 3]

        class Reader:
            tokenizer = Tokenizer()

            def __init__(self):
                self.calls = []

            def forward(self, ids, cache):
                self.calls.append((ids, cache))
                return torch.tensor([0.0, 4.0, 2.0, 1.0]), (cache or 0) + 1

        reader = Reader()
        first = torch.tensor([0.0, 2.0, 0.0, 0.0])
        result = candidate_score(reader, first, 0, "site_abcdef12")
        self.assertEqual(result["token_count"], 3)
        self.assertEqual(reader.calls, [([1], 0), ([2], 1)])
        self.assertTrue(result["log_likelihood"] <= 0)
        self.assertAlmostEqual(
            result["mean_log_likelihood"] * 3, result["log_likelihood"]
        )

    def test_out_of_bounds_candidate_tokens_rejected(self):
        class Tokenizer:
            def encode(self, text):
                return list(range(33))

        reader = type("Reader", (), {"tokenizer": Tokenizer()})()
        with self.assertRaisesRegex(ValueError, "bounded forced continuation"):
            candidate_score(reader, torch.ones(40), None, "site_00000000")


if __name__ == "__main__":
    unittest.main()
