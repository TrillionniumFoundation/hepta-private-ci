"""Exact-source input comparisons; no pretrained inference in unit fixtures."""

from dataclasses import asdict, replace
import json
import unittest

from bundle_reader import FrozenBundleReader, PromptBudgetError, compile_prompt
from event_projection import EventProjection
from event_reader_view import event_prompt
from evidence_bundle import EvidenceBundle, EvidenceSpan
from native import Question, digest
from test_event_projection import doc


class Tokenizer:
    def __init__(self):
        self.calls = []

    def apply_chat_template(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        # Explicit four-byte token stand-in, NOT real model token accounting.
        raw = json.dumps(messages, ensure_ascii=False).encode()
        return [sum(raw[i : i + 4]) for i in range(0, len(raw), 4)]


def context(rows=None):
    rows = rows or (doc("a", value="site_12345678"),)
    q = Question(
        "question", "family", "scope", "Where is service?", "2026-01-02T00:00:00Z"
    )
    projection = EventProjection(rows)
    spans = tuple(
        EvidenceSpan(
            d.identity, d.root, d.scope, d.session, d.observed_at,
            0, len(d.content.encode()), d.content, digest(d.content),
        )
        for d in rows
    )
    bundle = EvidenceBundle(digest(asdict(q)), projection.frontier, spans, "fixture")
    return q, bundle, {d.identity: d for d in rows}, projection.frontier


class EventViewTests(unittest.TestCase):
    def render(self, q, bundle, originals, frontier, tokenizer=None, **kwargs):
        return event_prompt(
            tokenizer or Tokenizer(),
            q,
            bundle,
            originals,
            frontier=frontier,
            revoked=kwargs.get("revoked", set()),
            token_limit=kwargs.get("limit", 2048),
        )

    def test_default_reader_compilation_is_byte_identical(self):
        q, bundle, originals, frontier = context()
        reader = object.__new__(FrozenBundleReader)
        reader.tokenizer = Tokenizer()
        expected = compile_prompt(
            reader.tokenizer, q, bundle, originals,
            frontier=frontier, revoked=set(), token_limit=2048,
        )
        actual = reader.compile_input(
            q, bundle, originals, frontier=frontier, revoked=set(), token_limit=2048
        )
        self.assertEqual(actual, expected)

    def test_original_json_is_not_replaced_with_a_summary(self):
        q, bundle, originals, frontier = context()
        tokenizer = Tokenizer()
        ids, receipt = self.render(q, bundle, originals, frontier, tokenizer)
        raw = json.loads(tokenizer.calls[0][0][1]["content"])
        explained = json.loads(tokenizer.calls[1][0][1]["content"])
        self.assertEqual(raw["evidence"], explained["evidence"])
        self.assertEqual(raw["question"], explained["question"])
        self.assertEqual(receipt["input_ids_digest"], digest(ids))
        self.assertEqual(receipt["delivered_evidence"], bundle.delivered())
        derived = receipt["derived_evidence"][0]
        self.assertIn("site_12345678", derived["text"])
        self.assertEqual(derived["original_digest"], digest(originals["a"].content))
        self.assertGreater(receipt["input_tokens"], receipt["raw_view_input_tokens"])

    def test_question_wording_does_not_change_evidence_derivation(self):
        q, bundle, originals, frontier = context()
        _, first = self.render(q, bundle, originals, frontier)
        changed = replace(q, content="Unrelated question, with no answer hint")
        other = replace(bundle, query_digest=digest(asdict(changed)))
        _, second = self.render(changed, other, originals, frontier)
        self.assertEqual(first["derived_evidence"], second["derived_evidence"])

    def test_unselected_withdrawal_and_frontier_drift_reject(self):
        q, bundle, originals, frontier = context((doc("a"), doc("b", entity="other")))
        with self.assertRaises(ValueError):
            self.render(
                q, replace(bundle, selected=bundle.selected[:1]), originals,
                frontier, revoked={"root_b"},
            )
        changed = replace(bundle, source_frontier="changed")
        with self.assertRaises(ValueError):
            self.render(q, changed, originals, "changed")

    def test_empty_context_remains_empty(self):
        q, bundle, originals, frontier = context()
        tokenizer = Tokenizer()
        _, receipt = self.render(
            q, replace(bundle, selected=()), originals, frontier, tokenizer
        )
        body = json.loads(tokenizer.calls[-1][0][1]["content"])
        self.assertEqual(body["evidence"], [])
        self.assertEqual(body["controlled_schema_expansions"], [])
        self.assertEqual(receipt["delivered_evidence"], [])

    def test_withdrawn_changed_and_partial_sources_reject(self):
        q, bundle, originals, frontier = context()
        with self.assertRaises(ValueError):
            self.render(q, bundle, originals, frontier, revoked={"root_a"})
        changed = {"a": replace(originals["a"], content="changed")}
        with self.assertRaises(ValueError):
            self.render(q, bundle, changed, frontier)
        partial = replace(bundle.selected[0], end=1, excerpt="{")
        with self.assertRaises(ValueError):
            self.render(q, replace(bundle, selected=(partial,)), originals, frontier)

    def test_derived_tokens_are_included_in_budget_no_silent_trim(self):
        q, bundle, originals, frontier = context()

        class BoundedTokenizer(Tokenizer):
            def apply_chat_template(self, messages, **kwargs):
                result = super().apply_chat_template(messages, **kwargs)
                return result if len(self.calls) == 1 else [1] * 2049

        with self.assertRaises(PromptBudgetError):
            self.render(q, bundle, originals, frontier, BoundedTokenizer())

    def test_explicit_correction_names_preserved_not_answer_labels(self):
        q, bundle, originals, frontier = context(
            (doc("a"), doc("b", value="site_abcdefgh", revision=2, supersedes=("a",)))
        )
        _, receipt = self.render(q, bundle, originals, frontier)
        self.assertIn("Superseded event IDs: a.", receipt["derived_evidence"][1]["text"])
        self.assertEqual(len(receipt["derived_evidence"]), 2)
        self.assertFalse(receipt["independent_semantic_review"])


if __name__ == "__main__":
    unittest.main()
