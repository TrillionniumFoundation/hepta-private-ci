"""Timestamp admission is strict and cache hits cannot bypass it.

Synthetic tests verify the documented native date grammar; they do not
retroactively alter the original failed benchmark or prove chronology quality.
"""

from dataclasses import replace
import unittest

from stem_cell_time import source_not_after_question
from stem_cell_runtime import ExactReaderCache
from test_stem_cell_runtime import Reader, evidence, query


class NativeChronologyTests(unittest.TestCase):
    def test_locomo_native_months_not_lexicographic_strings(self):
        # Raw LoCoMo format; lexicographically "9" > "1", but April precedes May.
        self.assertTrue(
            source_not_after_question(
                "9:36 am on 2 April, 2023", "1:56 pm on 8 May, 2023"
            )
        )
        # Lexicographically "1" < "9", but May follows April.
        self.assertFalse(
            source_not_after_question(
                "1:56 pm on 8 May, 2023", "9:36 am on 2 April, 2023"
            )
        )

    def test_exact_native_timestamps_are_comparable_without_rewriting(self):
        self.assertTrue(
            source_not_after_question(
                "1:56 pm on 8 May, 2023", "1:56 pm on 8 May, 2023"
            )
        )
        self.assertTrue(source_not_after_question("2023-10-01", "2024-01-01"))
        self.assertFalse(source_not_after_question("2024-01-01", "2023-10-01"))
        self.assertTrue(source_not_after_question("2023", "2024"))
        self.assertFalse(source_not_after_question("2025", "2024"))
        self.assertTrue(source_not_after_question("2023/10/01", "2023-10-01"))

    def test_longmemeval_native_weekday_and_minute_chronology(self):
        self.assertTrue(
            source_not_after_question(
                "2023/04/10 (Mon) 17:50",
                "2023/04/10 (Mon) 23:07",
            )
        )
        self.assertTrue(
            source_not_after_question(
                "2023/04/10 (Mon) 23:59",
                "2023/04/11 (Tue) 00:00",
            )
        )
        self.assertFalse(
            source_not_after_question(
                "2023/04/10 (Mon) 23:07",
                "2023/04/10 (Mon) 17:50",
            )
        )

    def test_longmemeval_weekday_drift_and_invalid_calendar_reject(self):
        for native in (
            "2023/04/10 (Tue) 17:50",
            "2023/02/30 (Thu) 10:00",
            "2023/04/10 (Mon) 24:00",
            "2023/04/10 (Mon) 17:99",
            "2023/04/10 (Xyz) 17:50",
            "2023/04/10 Mon 17:50",
        ):
            with self.subTest(native=native), self.assertRaises(ValueError):
                source_not_after_question(native, "2023/04/10 (Mon) 23:07")

    def test_longmemeval_precision_conflict_and_future_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "incomparable"):
            source_not_after_question("2023/04/10 (Mon) 17:50", "2023/04/10")
        reader = Reader()
        cache = ExactReaderCache(reader)
        q = replace(query(), observed_at="2023/05/28 (Sun) 06:47")
        too_late = (
            dict(
                evidence()[0],
                observed_at="2023/05/28 (Sun) 07:17",
            ),
        )
        with self.assertRaisesRegex(ValueError, "future evidence"):
            cache.answer(q, too_late, "denied", revoked=set())
        self.assertEqual(reader.calls, 0)

    def test_longmemeval_exact_reader_request_and_reuse(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        q = replace(query(), observed_at="2023/04/10 (Mon) 23:07")
        valid = (dict(evidence()[0], observed_at="2023/04/10 (Mon) 17:50"),)
        first, receipt = cache.answer(q, valid, "first", revoked=set())
        self.assertTrue(receipt["actual_reader_execution"])
        self.assertEqual(receipt["delivered_evidence"], list(valid))
        self.assertEqual(reader.calls, 1)
        second, reused = cache.answer(q, valid, "repeat", revoked=set())
        self.assertEqual(first, second)
        self.assertEqual(reused["reused_from"], "first")
        self.assertEqual(reader.calls, 1)

    def test_utc_offsets_use_same_instant_not_text_order(self):
        self.assertTrue(
            source_not_after_question(
                "2024-01-01T01:00:00+01:00", "2024-01-01T00:30:00Z"
            )
        )
        self.assertFalse(
            source_not_after_question(
                "2024-01-01T02:00:00+01:00", "2024-01-01T00:30:00Z"
            )
        )

    def test_unknown_invalid_and_mixed_precision_fail_closed(self):
        for a, b in (
            ("8 Foo 2023", "1:56 pm on 8 May, 2023"),
            ("2023-99-01", "2024-01-01"),
            ("2023/01-02", "2024-01-01"),
            ("2023-10-01", "2023"),
            ("2023-10-01T01:00:00", "2023-10-01T02:00:00Z"),
            ("9:36 am on 2 April, 2023", "2023-05-08"),
            ("", "2024"),
            (None, "2024"),
        ):
            with self.subTest(source=a, query=b), self.assertRaises(ValueError):
                source_not_after_question(a, b)

    def test_original_native_format_reaches_same_reader_without_forgery(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        q = replace(query(), observed_at="1:56 pm on 8 May, 2023")
        source = (dict(evidence()[0], observed_at="9:36 am on 2 April, 2023"),)
        raw, receipt = cache.answer(q, source, "first", revoked=set())
        self.assertEqual(reader.calls, 1)
        self.assertTrue(receipt["actual_reader_execution"])
        self.assertEqual(receipt["delivered_evidence"], list(source))
        self.assertEqual(receipt["observable_query"]["observed_at"], q.observed_at)
        again, reused = cache.answer(q, source, "second", revoked=set())
        self.assertEqual(again, raw)
        self.assertEqual(reused["reused_from"], "first")
        self.assertEqual(reader.calls, 1)

    def test_true_future_and_unknown_dates_never_enter_reader(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        q = replace(query(), observed_at="1:56 pm on 8 May, 2023")
        for observed in ("9:36 pm on 9 May, 2023", "not a date", "2024-01-01"):
            with self.subTest(observed=observed), self.assertRaises(ValueError):
                cache.answer(
                    q,
                    (dict(evidence()[0], observed_at=observed),),
                    "denied",
                    revoked=set(),
                )
        self.assertEqual(reader.calls, 0)

    def test_time_check_is_not_an_access_control_bypass(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        q = replace(query(), observed_at="1:56 pm on 8 May, 2023")
        source = (dict(evidence()[0], observed_at="9:36 am on 2 April, 2023"),)
        for bad, revoked in (
            ((dict(source[0], scope="other"),), set()),
            (source, {"root"}),
        ):
            with self.assertRaises(ValueError):
                cache.answer(q, bad, "denied", revoked=revoked)
        self.assertEqual(reader.calls, 0)


if __name__ == "__main__":
    unittest.main()
