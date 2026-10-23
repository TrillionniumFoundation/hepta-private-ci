"""Fault/accounting fixtures; no assertions of pretrained task benefit."""

from dataclasses import replace
import unittest

from native import Question
from stem_cell import StemHead
from stem_cell_runtime import ExactReaderCache, healthy_peer_snapshots


def query():
    return Question("q", "family", "scope", "What happened?", "2024")


def evidence():
    return (
        dict(
            root="root",
            scope="scope",
            observed_at="2023",
            label="E1",
            id="source",
            excerpt="Original evidence.",
        ),
    )


class Reader:
    identity, profile = "test-reader", "test-profile"
    quarantined = False

    def __init__(self):
        self.calls = 0
        self.fail = False
        self.corrupt = False

    def answer(self, q, sources, *, revoked):
        self.calls += 1
        if self.fail:
            raise ValueError("fixture generation failure")
        return "Fixture answer. [E1]", dict(
            generator_identity="wrong" if self.corrupt else self.identity,
            generator_profile=self.profile,
            delivered_evidence=list(sources),
            generation_seconds=0.001,
        )


class RuntimeTests(unittest.TestCase):
    def test_cached_answers_are_not_counted_as_new_reader_executions(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        first, receipt = cache.answer(query(), evidence(), "first", revoked=set())
        self.assertTrue(receipt["actual_reader_execution"])
        for i in range(6):
            raw, repeated = cache.answer(query(), evidence(), str(i), revoked=set())
            self.assertEqual(raw, first)
            self.assertEqual(repeated["reused_from"], "first")
            self.assertEqual(repeated["incremental_generation_seconds"], 0.0)
            self.assertFalse(repeated["actual_reader_execution"])
        self.assertEqual(reader.calls, 1)
        self.assertEqual(cache.summary()["actual_attempts"], 1)
        self.assertEqual(cache.summary()["cache_hits"], 6)

    def test_failed_actual_call_is_charged_not_discarded(self):
        reader = Reader()
        reader.fail = True
        cache = ExactReaderCache(reader)
        with self.assertRaises(ValueError):
            cache.answer(query(), evidence(), "failed", revoked=set())
        summary = cache.summary()
        self.assertEqual(summary["actual_attempts"], 1)
        self.assertEqual(summary["actual_failed_attempts"], 1)
        self.assertEqual(summary["retained_entries"], 0)
        self.assertGreater(summary["measured_call_seconds"], 0)

    def test_hit_still_checks_scope_revocation_future_and_quarantine(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        cache.answer(query(), evidence(), "first", revoked=set())
        for q, sources, revoked in (
            (query(), evidence(), {"root"}),
            (replace(query(), scope="other"), evidence(), set()),
            (replace(query(), observed_at="2022"), evidence(), set()),
        ):
            with self.assertRaises(ValueError):
                cache.answer(q, sources, "denied", revoked=revoked)
        reader.quarantined = True
        with self.assertRaises(ValueError):
            cache.answer(query(), evidence(), "denied", revoked=set())
        self.assertEqual(reader.calls, 1)

    def test_model_profile_or_evidence_change_requires_new_execution(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        cache.answer(query(), evidence(), "first", revoked=set())
        reader.profile = "changed-profile"
        cache.answer(query(), evidence(), "second", revoked=set())
        changed = (dict(evidence()[0], excerpt="Different original text."),)
        cache.answer(query(), changed, "third", revoked=set())
        self.assertEqual(reader.calls, 3)

    def test_returned_receipts_do_not_mutate_cached_source(self):
        cache = ExactReaderCache(Reader())
        _, receipt = cache.answer(query(), evidence(), "first", revoked=set())
        receipt["delivered_evidence"][0]["excerpt"] = "caller mutation"
        _, again = cache.answer(query(), evidence(), "second", revoked=set())
        self.assertEqual(again["delivered_evidence"], list(evidence()))

    def test_cache_has_byte_and_entry_bounds(self):
        reader = Reader()
        cache = ExactReaderCache(reader, maximum_bytes=1)
        for i in range(3):
            cache.answer(query(), evidence(), str(i), revoked=set())
        self.assertEqual(reader.calls, 3)
        self.assertEqual(cache.summary()["retained_entries"], 0)
        self.assertEqual(cache.summary()["retained_serialized_bytes"], 0)

    def test_detached_reader_receipt_cannot_enter_cache(self):
        reader = Reader()
        reader.corrupt = True
        cache = ExactReaderCache(reader)
        with self.assertRaises(ValueError):
            cache.answer(query(), evidence(), "bad", revoked=set())
        self.assertEqual(cache.summary()["actual_failed_attempts"], 1)
        self.assertEqual(cache.summary()["retained_entries"], 0)

    def test_quarantined_cell_does_not_poison_unrelated_cell_snapshot(self):
        failed, healthy, current = (StemHead(4, "encoder") for _ in range(3))
        failed.quarantined = True
        heads = {"failed": failed, "healthy": healthy, "current": current}
        snapshots = healthy_peer_snapshots(heads, "current", {"failed": "recorded"})
        self.assertEqual(snapshots, {"healthy": healthy.export()})
        self.assertTrue(failed.quarantined)


if __name__ == "__main__":
    unittest.main()
