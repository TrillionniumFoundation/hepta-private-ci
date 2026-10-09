"""Byte/permission mechanics, not a semantic citation acceptance test."""

from dataclasses import replace
import unittest

from native import Document, Question, Target
from selector_windows import WindowBudget, candidate_windows
from selector_evaluation import coverage


class SelectorWindowTests(unittest.TestCase):
    def setUp(self):
        self.q = Question("q", "family", "scope", "Which city did Mara move to?", "2025")
        self.doc = Document("native/doc", "root", "scope", "session", "2024",
                            ("序言 introduction. " * 100) + "Mara moved to Kyoto in 2024. 后记。")

    def test_tail_window_preserves_original_unicode_bytes_not_prefix_guess(self):
        prefix = candidate_windows((self.doc,), self.q, revoked=set(), profile="prefix")
        full = candidate_windows((self.doc,), self.q, revoked=set())
        self.assertFalse(any("Kyoto" in w.text for w in prefix.windows))
        self.assertTrue(any("Kyoto" in w.text for w in full.windows))
        for w in full.windows:
            self.assertEqual(self.doc.content.encode()[w.start:w.end].decode(), w.text)
        target = Target("Kyoto", "single", (self.doc.identity,), False)
        self.assertFalse(coverage((self.doc,), prefix, target)["candidate_literal_answer"])
        self.assertTrue(coverage((self.doc,), full, target)["candidate_literal_answer"])
        self.assertEqual(full.seal(), candidate_windows((self.doc,), self.q, revoked=set()).seal())

    def test_scan_candidate_caps_and_unread_suffix_are_explicit(self):
        budget = WindowBudget(scan_bytes=2048, per_source_bytes=1024, candidates=3)
        docs = tuple(replace(self.doc, identity=str(i), content="🙂甲word " * 10000) for i in range(8))
        result = candidate_windows(docs, self.q, revoked=set(), budget=budget)
        self.assertLessEqual(result.scanned_bytes, 2048)
        self.assertLessEqual(len(result.windows), 3)
        self.assertTrue(all(s["unscanned_characters"] > 0 for s in result.inspected))
        self.assertLessEqual(result.enumerated_windows, 2048 // budget.stride_bytes + 8)
        self.assertEqual(result.scanned_bytes, sum(len(s["excerpt"].encode()) for s in result.inspected))

    def test_wrong_scope_query_withdrawal_and_normalized_chunk_reject(self):
        for doc in (replace(self.doc, scope="private"), replace(self.doc, identity="doc#chunk:0")):
            with self.assertRaises(ValueError):
                candidate_windows((doc,), self.q, revoked=set())
        with self.assertRaises(ValueError):
            candidate_windows((self.doc,), self.q, revoked={"root"})
        with self.assertRaises(ValueError):
            candidate_windows((self.doc, self.doc), self.q, revoked=set())
        result = candidate_windows((self.doc,), self.q, revoked=set())
        with self.assertRaises(ValueError):
            result.revalidate(replace(self.q, content="a different question"), set())
        with self.assertRaises(ValueError):
            result.revalidate(self.q, {"root"})

    def test_mutated_excerpt_is_not_bound_by_a_self_asserted_window(self):
        result = candidate_windows((self.doc,), self.q, revoked=set())
        result.inspected[0]["excerpt"] = "changed"
        with self.assertRaises(ValueError):
            result.revalidate(self.q, set())

    def test_empty_pool_is_valid_but_not_evidence(self):
        result = candidate_windows((), self.q, revoked=set())
        self.assertEqual((result.windows, result.scanned_bytes), ((), 0))
        with self.assertRaises(ValueError):
            candidate_windows((replace(self.doc, content="\0bad"),), self.q, revoked=set())
        with self.assertRaises(ValueError):
            candidate_windows((self.doc,), self.q, revoked=set(), budget=WindowBudget(candidates=True))

    def test_annotation_values_cannot_change_candidates(self):
        before = candidate_windows((self.doc,), self.q, revoked=set())
        for answer in ("Kyoto", "Osaka", "poison"):
            coverage((self.doc,), before, Target(answer, "single", (self.doc.identity,), False))
        self.assertEqual(before, candidate_windows((self.doc,), self.q, revoked=set()))


if __name__ == "__main__":
    unittest.main()
