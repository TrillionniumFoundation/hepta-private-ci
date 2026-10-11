"""No future source may enter a native retrieval index or any Encoder."""

import unittest
from pathlib import Path
import sys
import tempfile
import types
from types import SimpleNamespace
from unittest.mock import patch

from native import Document, Question
from stem_cell_temporal import admit_history, build_as_of_index


def query(date="2023/05/28 (Sun) 06:47", scope="scope"):
    return Question("qid", "family", scope, "What happened?", date)


def document(identity, date, *, scope="scope", root="root"):
    return Document(identity, root, scope, "session", date, "Original source text.")


class AsOfAdmissionTests(unittest.TestCase):
    def test_future_longmemeval_session_excluded_before_retrieval(self):
        docs = (
            document("past", "2023/05/28 (Sun) 05:47"),
            document("future", "2023/05/28 (Sun) 21:04"),
            document("same", "2023/05/28 (Sun) 06:47"),
        )
        admitted, receipt = admit_history(query(), docs, revoked=set())
        self.assertEqual([d.identity for d in admitted], ["past", "same"])
        self.assertEqual(receipt["original_count"], 3)
        self.assertEqual(receipt["admitted_count"], 2)
        self.assertEqual(receipt["excluded_future_count"], 1)
        self.assertFalse(receipt["native_gold_targets_inspected"])
        self.assertFalse(receipt["source_content_rewritten"])

    def test_empty_as_of_history_is_not_replaced_with_a_guess(self):
        with self.assertRaisesRegex(ValueError, "no as-of-admissible"):
            admit_history(
                query(),
                (document("future", "2023/05/28 (Sun) 21:04"),),
                revoked=set(),
            )

    def test_unknown_calendar_or_weekday_fails_entire_index(self):
        for observed_at in (
            "2023/05/28 (Mon) 05:47",
            "2023/05/42 (Sun) 05:47",
            "source time unavailable",
        ):
            with (
                self.subTest(observed_at=observed_at),
                self.assertRaisesRegex(ValueError, "uncomparable native"),
            ):
                admit_history(
                    query(),
                    (
                        document("past", "2023/05/28 (Sun) 05:47"),
                        document("invalid", observed_at),
                    ),
                    revoked=set(),
                )

    def test_scope_withdrawal_duplicate_and_invalid_arguments_reject(self):
        for documents, revoked in (
            ((document("a", "2023/05/28 (Sun) 05:47", scope="other"),), set()),
            ((document("a", "2023/05/28 (Sun) 05:47"),), {"root"}),
            (
                (
                    document("a", "2023/05/28 (Sun) 05:47"),
                    document("a", "2023/05/28 (Sun) 06:00"),
                ),
                set(),
            ),
            ((), set()),
        ):
            with self.subTest(docs=len(documents)), self.assertRaises(ValueError):
                admit_history(query(), documents, revoked=revoked)

    def test_nonfuture_locomo_native_source_keeps_same_original_bytes(self):
        q = query("1:56 pm on 8 May, 2023")
        d = document("old", "9:36 am on 2 April, 2023")
        allowed, receipt = admit_history(q, (d,), revoked=set())
        self.assertEqual(allowed, (d,))
        self.assertEqual(allowed[0].content, d.content)
        self.assertEqual(receipt["excluded_future_count"], 0)

    def test_scope_and_question_time_bind_admission_receipt(self):
        d = document("old", "2023-05-20")
        q1 = query("2023-05-28")
        q2 = query("2023-05-29")
        _, first = admit_history(q1, (d,), revoked=set())
        _, second = admit_history(q2, (d,), revoked=set())
        self.assertNotEqual(first["source_query_digest"], second["source_query_digest"])

    def test_as_of_filter_executes_before_encoder_and_seals_index_cut(self):
        # Fake Index and Encoder prove the source boundary without pretrained
        # models or a real SQLite file. This is a data-flow safety regression.
        seen = {}

        class FakeEncoder:
            identity = "pinned-encoder"

            def encode(self, texts):
                seen["encoded"] = list(texts)
                self_outer.assertNotIn("FUTURE_NEVER_ENCODE", str(texts))
                return [[0.25, 0.75] for _ in texts]

        class FakeIndex:
            @staticmethod
            def build(path, documents, vectors, encoder, cut):
                seen["indexed"] = tuple(d.identity for d in documents)
                seen["index_cut"] = cut
                seen["index_vectors"] = len(vectors)
                self_outer.assertEqual(encoder, "pinned-encoder")
                path.write_bytes(b"bounded-mock-index")
                return "pinned-test-artifact"

            def __init__(
                self,
                path,
                expected_cut,
                revoked,
                *,
                expected_file_digest,
                expected_encoder,
            ):
                self_outer.assertEqual(expected_cut, seen["index_cut"])
                self_outer.assertEqual(expected_file_digest, "pinned-test-artifact")
                self_outer.assertEqual(expected_encoder, "pinned-encoder")

        self_outer = self
        mock_index = types.ModuleType("index")
        mock_index.PersistentIndex = FakeIndex
        source = SimpleNamespace(
            source_sha256="frozen-source-sha",
            history=lambda _: (
                Document(
                    "before",
                    "r1",
                    "scope",
                    "session",
                    "2023/05/28 (Sun) 05:47",
                    "EARLIER_VALID",
                ),
                Document(
                    "after",
                    "r2",
                    "scope",
                    "session",
                    "2023/05/28 (Sun) 21:04",
                    "FUTURE_NEVER_ENCODE",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sys.modules, {"index": mock_index}):
                index, result = build_as_of_index(
                    source,
                    query(),
                    FakeEncoder(),
                    Path(directory),
                    revoked=set(),
                )
            self.assertIsInstance(index, FakeIndex)
            self.assertEqual(seen["indexed"], ("before",))
            self.assertEqual(seen["index_vectors"], 1)
            self.assertEqual(result["receipt"]["excluded_future_count"], 1)
            self.assertEqual(result["as_of_cut"], seen["index_cut"])
            self.assertEqual(result["index_cost"]["documents"], 1)


if __name__ == "__main__":
    unittest.main()
