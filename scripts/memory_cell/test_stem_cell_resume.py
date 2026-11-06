"""Multi-example continuation and canonical request provenance regressions."""

from dataclasses import asdict
import unittest

from native import digest
from selector_head import Supervision, TrainingCut
from stem_cell import StemHead, sha256
from stem_cell_runtime import ExactReaderCache
from test_stem_cell import features
from test_stem_cell_runtime import Reader, evidence, query


class ResumeTests(unittest.TestCase):
    def test_non_epoch_boundary_resume_matches_uninterrupted_training(self):
        rows = tuple(
            Supervision(features(name), positive)
            for name, positive in (("a", (0,)), ("b", (1,)), ("c", (0,)))
        )
        cut = TrainingCut(
            frozenset({"a", "b", "c"}),
            frozenset({"family"}),
            frozenset({"root"}),
            frozenset({"held-out"}),
            "admission",
        )
        for kind in ("linear", "gated"):
            with self.subTest(kind=kind):
                whole = StemHead(4, "encoder-v1", kind=kind)
                split = StemHead(4, "encoder-v1", kind=kind)
                whole.fit(rows, cut, revoked=set(), steps=12, pair_ceiling=24)
                first = split.fit(rows, cut, revoked=set(), steps=5, pair_ceiling=24)
                self.assertEqual(first["sample_cursor"], 2)
                payload = split.export()
                resumed = StemHead.restore(
                    payload,
                    expected_sha256=sha256(payload),
                    encoder_identity="encoder-v1",
                    allowed_roots={"root"},
                    revoked=set(),
                )
                # The caller's row order is not hidden state either.
                second = resumed.fit(
                    tuple(reversed(rows)), cut, revoked=set(), steps=7, pair_ceiling=24
                )
                self.assertEqual(second["sample_cursor"], 0)
                self.assertEqual(resumed.steps, 12)
                self.assertEqual(resumed.pair_evaluations, 24)
                self.assertEqual(resumed.export(), whole.export())

    def test_reader_receipt_retains_exact_observable_query_and_request_digest(self):
        reader = Reader()
        cache = ExactReaderCache(reader)
        q, sources = query(), evidence()
        _, first = cache.answer(q, sources, "first", revoked=set())
        self.assertEqual(first["observable_query"], asdict(q))
        expected = digest((reader.identity, reader.profile, asdict(q), sources))
        self.assertEqual(first["canonical_request_digest"], expected)
        first["observable_query"]["content"] = "caller changed its receipt"
        _, second = cache.answer(q, sources, "second", revoked=set())
        self.assertEqual(second["observable_query"], asdict(q))
        self.assertEqual(second["canonical_request_digest"], expected)
        self.assertEqual(second["reused_from"], "first")


if __name__ == "__main__":
    unittest.main()
