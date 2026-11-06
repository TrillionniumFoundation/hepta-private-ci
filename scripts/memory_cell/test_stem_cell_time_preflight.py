"""Tiny chronological corpus fixtures, not future observations or QA judgments."""

from dataclasses import dataclass
import unittest

from stem_cell_time_preflight import native_chronology


@dataclass(frozen=True)
class Document:
    identity: str
    root: str
    scope: str
    observed_at: str


@dataclass(frozen=True)
class Question:
    identity: str
    scope: str
    observed_at: str


@dataclass
class Corpus:
    source_sha256: str
    documents: tuple
    questions: tuple


class NativeTimePreflightTests(unittest.TestCase):
    def test_native_month_times_are_not_lexically_compared(self):
        documents = (
            Document("a", "a", "scope", "9:36 am on 2 April, 2023"),
            Document("b", "b", "scope", "1:56 pm on 8 May, 2023"),
        )
        questions = (
            Question("first", "scope", "1:56 pm on 8 May, 2023"),
            Question("duplicate", "scope", "1:56 pm on 8 May, 2023"),
        )
        result = native_chronology({"locomo": Corpus("sha", documents, questions)})
        self.assertEqual(result["datasets"]["locomo"]["source_observation_checks"], 2)
        self.assertEqual(result["datasets"]["locomo"]["accepted"], 2)
        self.assertTrue(result["all_observations_comparable_and_nonfuture"])
        self.assertFalse(result["production_chronology_qualified"])

    def test_future_and_unknown_not_silently_counted_as_eligible(self):
        docs = (
            Document("a", "a", "scope", "1:56 pm on 8 May, 2023"),
            Document("b", "b", "scope", "9:36 pm on 9 May, 2023"),
            Document("c", "c", "scope", "invalid"),
        )
        result = native_chronology(
            {
                "locomo": Corpus(
                    "sha", docs, (Question("first", "scope", "1:56 pm on 8 May, 2023"),)
                )
            }
        )
        self.assertEqual(result["datasets"]["locomo"]["accepted"], 1)
        self.assertEqual(result["datasets"]["locomo"]["future"], 1)
        self.assertEqual(result["datasets"]["locomo"]["unknown"], 1)
        self.assertFalse(result["all_observations_comparable_and_nonfuture"])
        self.assertEqual(
            len(result["datasets"]["locomo"]["example_identity_digests"]["future"]), 1
        )
        self.assertEqual(
            len(result["datasets"]["locomo"]["example_identity_digests"]["unknown"]), 1
        )

    def test_scope_does_not_leak_into_another_question(self):
        docs = (
            Document("a", "a", "first", "2023-01-01"),
            Document("b", "b", "second", "2024-01-01"),
        )
        qs = (Question("q", "first", "2023-02-01"),)
        res = native_chronology({"benchmark": Corpus("sha", docs, qs)})
        self.assertEqual(res["datasets"]["benchmark"]["source_observation_checks"], 1)
        self.assertEqual(res["datasets"]["benchmark"]["accepted"], 1)

    def test_duplicate_observable_time_not_pseudo_independent(self):
        doc = (Document("a", "a", "same", "2022-01-01"),)
        qs = tuple(Question(str(i), "same", "2023-01-01") for i in range(200))
        res = native_chronology({"corpus": Corpus("sha", doc, qs)})
        self.assertEqual(
            res["datasets"]["corpus"]["unique_scope_question_timestamp_pairs"], 1
        )
        self.assertEqual(res["datasets"]["corpus"]["source_observation_checks"], 1)
        self.assertEqual(res["actual_future_window_count"], 0)

    def test_longmemeval_native_weekday_census_does_not_hide_future(self):
        docs = (
            Document("a", "a", "scope", "2023/04/10 (Mon) 14:47"),
            Document("b", "b", "scope", "2023/04/10 (Mon) 21:04"),
            Document("c", "c", "scope", "2023/04/10 (Tue) 10:00"),
        )
        qs = (Question("q", "scope", "2023/04/10 (Mon) 17:50"),)
        result = native_chronology({"longmemeval": Corpus("sha", docs, qs)})
        summary = result["datasets"]["longmemeval"]
        self.assertEqual(summary["accepted"], 1)
        self.assertEqual(summary["future"], 1)
        self.assertEqual(summary["unknown"], 1)
        self.assertFalse(result["all_observations_comparable_and_nonfuture"])
        self.assertEqual(result["actual_future_window_count"], 0)

    def test_longmemeval_original_minute_grammar_is_comparable(self):
        doc = (Document("a", "root", "scope", "2023/05/20 (Sat) 02:21"),)
        q = (Question("q", "scope", "2023/05/30 (Tue) 23:40"),)
        report = native_chronology({"longmemeval": Corpus("sha", doc, q)})
        self.assertEqual(report["datasets"]["longmemeval"]["accepted"], 1)
        self.assertEqual(report["datasets"]["longmemeval"]["unknown"], 0)


if __name__ == "__main__":
    unittest.main()
