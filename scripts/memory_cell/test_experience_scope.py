"""Explicit source-schema fixtures, not a pretrained capability result."""

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest

from experience_memory import ExperienceReader, render, source_examples
from native import Question
from test_experience_memory import source


class Tokenizer:
    def __init__(self):
        self.messages = None

    def apply_chat_template(self, messages, **kwargs):
        self.messages = messages
        return list(json.dumps(messages, ensure_ascii=False).encode())


class ExperienceScopeTests(unittest.TestCase):
    def test_same_entity_and_time_with_distinct_scopes_have_distinct_inputs(self):
        docs = (
            source("a", "site_a", scope="alpha"),
            source("b", "site_b", scope="beta"),
        )
        examples, _ = source_examples(
            docs, revision=2, allowed_roots={d.root for d in docs}, revoked=set()
        )
        left, right = (Question(**item["query"]) for item in examples)
        self.assertEqual(left.content, right.content)
        self.assertEqual(left.observed_at, right.observed_at)
        self.assertNotEqual(examples[0]["target"], examples[1]["target"])
        a, b = Tokenizer(), Tokenizer()
        self.assertNotEqual(render(a, left, [], []), render(b, right, [], []))
        for tokenizer, query in ((a, left), (b, right)):
            body = json.loads(tokenizer.messages[1]["content"])
            self.assertEqual(body["memory_scope"], query.scope)
            self.assertEqual(body["evidence"], [])
            self.assertNotIn("site_a", body["question"])
            self.assertNotIn("site_b", body["question"])

    def test_annotation_or_question_identity_is_not_a_memory_feature(self):
        query = Question("train_id", "train_family", "scope", "Where?", "2026")
        later = replace(query, identity="future_id", family="future_family")
        self.assertEqual(
            render(Tokenizer(), query, [], []), render(Tokenizer(), later, [], [])
        )

    def test_scope_is_exact_utf8_not_normalized_or_inferred_from_time(self):
        query = Question("q", "f", "東京", "Where?", "2026")
        tokenizer = Tokenizer()
        render(tokenizer, query, [], [])
        self.assertEqual(
            json.loads(tokenizer.messages[1]["content"])["memory_scope"], "東京"
        )
        for value in (None, True, "", "界" * 342):
            tokenizer = Tokenizer()
            with self.assertRaises(ValueError):
                render(tokenizer, replace(query, scope=value), [], [])
            self.assertIsNone(tokenizer.messages)

    def test_prompt_scope_does_not_replace_owner_admission(self):
        reader = SimpleNamespace(scopes={"admitted"})
        query = Question("q", "f", "other", "Where?", "2026")
        with self.assertRaisesRegex(ValueError, "outside written/admitted"):
            ExperienceReader.compile_input(reader, query, None, {})


if __name__ == "__main__":
    unittest.main()
