"""Mechanism tests, not human oracle labels or production authorization."""

from dataclasses import asdict, replace
import unittest

from evidence_bundle import (EvidenceBundle, EvidenceSpan, build_windows, observed_time,
                             retrieve_bundle, select_set)
from native import Document, Question, digest
from bundle_reader import compile_prompt, PromptBudgetError


def fixture():
    q = Question("q", "family", "scope", "When did Nera move and start training?", "2024-06-02T00:00:00Z")
    docs = tuple(Document(f"d{i}", f"root{i}", "scope", f"s{i}", "2024-06-01T00:00:00Z", text)
                 for i, text in enumerate(("Nera moved in May.", "Nera started training in March.",
                                           "Irrelevant other person.")))
    spans, _ = build_windows(docs)
    return q, {d.identity: d for d in docs}, spans


class Tokenizer:
    def apply_chat_template(self, messages, **kwargs):
        self.messages = messages
        return list(range(len(str(messages).split())))


class BundleTests(unittest.TestCase):
    def test_utf8_windows_retain_original_bytes_and_tail(self):
        q, originals, _ = fixture()
        d = replace(originals["d0"], content="这是事实。"*90 + "tail evidence")
        spans, receipt = build_windows((d,), window_bytes=128, stride_bytes=64)
        for s in spans:
            s.validate(d, q, set())
            self.assertEqual(s.excerpt, d.content.encode()[s.start:s.end].decode())
        self.assertEqual(spans[-1].end, len(d.content.encode()))
        self.assertEqual(receipt["source_bytes"], len(d.content.encode()))
        self.assertIn("tail evidence", spans[-1].excerpt)

    def test_revoked_drifted_cross_scope_and_future_sources_fail(self):
        q, originals, spans = fixture()
        span, d = spans[0], originals["d0"]
        for bad, revoked in ((replace(d, content=d.content+"changed"), set()),
                             (replace(d, root="other"), set()),
                             (replace(d, scope="other"), set()), (d, {d.root})):
            with self.assertRaises(ValueError): span.validate(bad, q, revoked)
        future = replace(d, observed_at="2025-01-01T00:00:00Z")
        f, _ = build_windows((future,))
        with self.assertRaises(ValueError): f[0].validate(future, q, set())

    def test_invalid_boundaries_and_manifest_reject(self):
        q, originals, spans = fixture()
        for bad in (replace(spans[0], start=True), replace(spans[0], end=99999),
                    replace(spans[0], excerpt="invented"), replace(spans[0], source_digest="changed")):
            with self.assertRaises(ValueError): bad.validate(originals["d0"], q, set())
        b = EvidenceBundle(digest(asdict(q)), "frontier", tuple(spans[:2]), "ranked")
        b.validate(q, originals, frontier="frontier", revoked=set())
        with self.assertRaises(ValueError): b.validate(q, originals, frontier="other", revoked=set())
        with self.assertRaises(ValueError): replace(b, selected=(spans[0], spans[0])).validate(q, originals, frontier="frontier", revoked=set())

    def test_two_sources_render_in_one_prompt_not_two_reader_calls(self):
        q, originals, spans = fixture()
        b = EvidenceBundle(digest(asdict(q)), "frontier", tuple(spans[:2]), "coverage")
        tokenizer = Tokenizer()
        _, rec = compile_prompt(tokenizer, q, b, originals, frontier="frontier", revoked=set(), token_limit=2048)
        self.assertEqual([s["label"] for s in rec["delivered_evidence"]], ["E1", "E2"])
        self.assertIn(spans[0].excerpt, tokenizer.messages[1]["content"])
        self.assertIn(spans[1].excerpt, tokenizer.messages[1]["content"])
        self.assertNotIn("annotation", tokenizer.messages[1]["content"])

    def test_prompt_overflow_is_not_silent_truncation(self):
        q, originals, spans = fixture()
        b = EvidenceBundle(digest(asdict(q)), "frontier", spans[:1], "ranked")
        class Long(Tokenizer):
            def apply_chat_template(self, *a, **kw): return [1]*2049
        with self.assertRaises(PromptBudgetError) as exc:
            compile_prompt(Long(), q, b, originals, frontier="frontier", revoked=set(), token_limit=2048)
        self.assertEqual((exc.exception.actual, exc.exception.maximum), (2049, 2048))

    def test_coverage_prefers_complement_over_overlapping_fragment(self):
        q, originals, spans = fixture()
        duplicate = replace(spans[0], start=1, excerpt=spans[0].excerpt[1:])
        chosen = select_set(q, [spans[0], duplicate, spans[1]], count=2, mode="coverage")
        self.assertEqual(set(chosen), {spans[0], spans[1]})
        self.assertEqual(select_set(q, [spans[0], duplicate, spans[1]], count=2, mode="ranked"),
                         (spans[0], duplicate))

    def test_missing_query_terms_trigger_bounded_extra_read(self):
        q, originals, spans = fixture(); calls = []
        def read(query, count):
            calls.append(query.content)
            return ([spans[0]] if len(calls) == 1 else [spans[1]]), dict(queries=1)
        b, receipt = retrieve_bundle(q, read, originals, frontier="frontier", revoked=set(), rounds=3)
        self.assertEqual({s.source_id for s in b.selected}, {"d0", "d1"})
        self.assertLessEqual(len(calls), 3)
        self.assertIn("Additional retrieval cues:", calls[1])
        self.assertIsNone(receipt["semantic_sufficiency"])

    def test_duplicate_supplemental_results_do_not_grow_context(self):
        q, originals, spans = fixture()
        b, rec = retrieve_bundle(q, lambda q,k: ([spans[0]], {}), originals,
                                frontier="frontier", revoked=set(), rounds=3)
        self.assertEqual(b.selected, (spans[0],))
        self.assertEqual(rec["rounds"], 2)

    def test_registered_dates_and_unregistered_or_cross_scope_reject(self):
        self.assertEqual(observed_time("2024/06/01 (Sat) 12:00"), observed_time("12:00 pm on 1 June, 2024"))
        with self.assertRaises(ValueError): observed_time("sometime yesterday")
        q, originals, _ = fixture()
        with self.assertRaises(ValueError): build_windows((originals['d0'], replace(originals['d1'], scope="other")))
        with self.assertRaises(ValueError): build_windows(tuple(originals.values()), window_bytes=True)

    def test_empty_bundle_is_rendered_not_replaced_with_a_fake_answer(self):
        q, originals, _ = fixture()
        b = EvidenceBundle(digest(asdict(q)), "f", (), "empty", 0)
        t = Tokenizer(); ids, rec = compile_prompt(t, q, b, originals, frontier="f", revoked=set(), token_limit=2048)
        self.assertTrue(ids); self.assertEqual(rec["delivered_evidence"], [])
        self.assertIn('"evidence": []', t.messages[1]["content"])


if __name__ == "__main__": unittest.main()
