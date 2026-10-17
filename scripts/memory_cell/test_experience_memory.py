"""Source-write invariants; these fixtures are not pretrained model evidence."""

from dataclasses import replace
import json
import unittest

from event_projection import PROFILE
from experience_memory import source_examples, render
from native import Document, Question


def source(identity, value, revision=1, supersedes=(), scope="s"):
    body = dict(
        schema=PROFILE,
        id=identity,
        entity="service",
        attribute="location",
        value=value,
        revision=revision,
        supersedes=list(supersedes),
    )
    return Document(
        identity,
        "root_" + identity,
        scope,
        scope,
        "2026-10-10T00:00:00+00:00",
        json.dumps(body),
    )


def project(rows, revision=2, revoked=frozenset()):
    return source_examples(
        rows, revision=revision, allowed_roots={r.root for r in rows}, revoked=revoked
    )


class SourceWriteTests(unittest.TestCase):
    def test_only_source_facts_make_targets_no_query_or_answer_input(self):
        rows = (
            source("a", "site_old"),
            source("b", "site_new", 2, ("a",)),
            source("c", "site_future", 3),
        )
        examples, _ = project(rows)
        self.assertEqual([r["target"] for r in examples], ["site_new"])
        self.assertEqual(examples[0]["sources"], ["b"])
        self.assertEqual([r["target"] for r in project(rows, 1)[0]], ["site_old"])
        self.assertEqual(project(rows), project(tuple(reversed(rows))))

    def test_conflicts_unknown_and_not_arbitrary_last_value(self):
        rows = (source("a", "site_a"), source("b", "site_b", 2))
        with self.assertRaises(ValueError):
            project(rows)

    def test_multihop_correction_and_no_newer_unlinked_override(self):
        rows = (
            source("a", "site_a"),
            source("b", "site_b", 2, ("a",)),
            source("c", "site_c", 3, ("b",)),
        )
        self.assertEqual(project(rows, 3)[0][0]["sources"], ["c"])

    def test_no_removed_future_or_revoked_root_laundered_through_writer(self):
        rows = (source("a", "site_a"), source("b", "site_b", 3))
        with self.assertRaises(ValueError):
            project(rows, revoked={"root_b"})
        with self.assertRaises(ValueError):
            source_examples(rows, revision=2, allowed_roots={"root_a"}, revoked=set())

    def test_bad_revision_duplicate_source_and_unzoned_time_reject(self):
        a = source("a", "site_a")
        for rows, rev in (
            ((a, a), 2),
            ((a,), True),
            ((a,), -1),
            ((replace(a, observed_at="2026-10-10"),), 2),
        ):
            with self.assertRaises(ValueError):
                project(rows, rev)

    def test_prompt_permits_parameter_only_but_does_not_invent_sources(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                self.messages = messages
                return [1, 2, 3]

        tokenizer = Tokenizer()
        q = Question("q", "f", "s", "Where?", "2026-10-10")
        self.assertEqual(render(tokenizer, q, [], []), [1, 2, 3])
        body = json.loads(tokenizer.messages[1]["content"])
        self.assertEqual(body["evidence"], [])
        self.assertEqual(body["controlled_schema_expansions"], [])
        self.assertNotIn("answer", body)


if __name__ == "__main__":
    unittest.main()
