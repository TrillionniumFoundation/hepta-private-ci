"""Transferred-policy lifetime tests; reader is explicitly a test fixture."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from frozen_memory_session import FrozenMemorySession, freeze
from native import Document, Question, digest
from policy_ancestry import SCHEMA, source_references, validate_support
from test_frozen_memory_session import Reader, select


class PolicyAncestryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "session"
        self.documents = (
            Document(
                "test-doc", "test-root", "test", "s", "2024-01-01", "visible source"
            ),
        )
        self.train = (
            Document(
                "train-doc",
                "train-root",
                "train",
                "s",
                "2023-12-01",
                "hidden training text",
            ),
        )
        self.q = Question("q", "family", "test", "What?", "2024-02-01")

    def frozen(self, **changes):
        options = dict(
            through="2024-01-02",
            policy_bytes=b'{"weights":[1]}',
            policy_roots={"train-root"},
            policy_sources=self.train,
            reader_identity=Reader.identity,
            source_commit="a" * 40,
        )
        options.update(changes)
        sha = freeze(self.root, self.documents, **options)
        return FrozenMemorySession(self.root, expected_snapshot=sha), sha

    def test_transfer_preserves_ancestors_without_delivering_training_text(self):
        session, sha = self.frozen()
        self.assertEqual(session.state["schema"], SCHEMA)
        self.assertEqual(session.documents, self.documents)
        self.assertEqual(session.roots, {"train-root", "test-root"})
        self.assertNotIn(
            "hidden training text", (self.root / "snapshot.json").read_text()
        )
        seen = []

        def selector(q, docs, *args):
            seen.extend(docs)
            return select(q, docs, *args)

        reader = Reader()
        result = session.answer(self.q, selector, reader, withdrawals=lambda: set())
        self.assertEqual(seen, list(self.documents))
        reopened = FrozenMemorySession(self.root, expected_snapshot=sha)
        self.assertEqual(
            reopened.replay(
                self.q,
                withdrawals=lambda: set(),
                expected_result_sha256=result["result_sha256"],
            ),
            result,
        )
        with self.assertRaisesRegex(ValueError, "revoked snapshot"):
            reopened.replay(
                self.q,
                withdrawals=lambda: {"train-root"},
                expected_result_sha256=result["result_sha256"],
            )
        self.assertEqual(reader.calls, 1)

    def test_ancestor_withdrawal_during_generation_never_publishes_success(self):
        session, _ = self.frozen()
        withdrawn = set()
        reader = Reader()
        reader.after = lambda: withdrawn.add("train-root")
        with self.assertRaisesRegex(ValueError, "revoked snapshot"):
            session.answer(self.q, select, reader, withdrawals=lambda: withdrawn)
        result = json.loads(
            (
                self.root / (digest((self.q.scope, self.q.identity)) + ".result.json")
            ).read_text()
        )
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("answer", result)
        self.assertEqual(reader.calls, 1)

    def test_unbound_future_or_duplicate_ancestors_reject_before_snapshot(self):
        changes = (
            dict(policy_sources=()),
            dict(policy_sources=(replace(self.train[0], observed_at="2025-01-01"),)),
            dict(policy_sources=self.train * 2),
            dict(policy_roots={"different"}),
            dict(policy_sources=self.documents, policy_roots={"test-root"}),
        )
        for values in changes:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.frozen(**values)
            self.assertFalse(self.root.exists())

    def test_references_are_exact_and_unrelated_withdrawal_does_not_deny(self):
        entries = source_references(
            self.train, through="2024-01-02", policy_roots={"train-root"}
        )
        self.assertEqual(
            validate_support(
                entries, through="2024-01-02", policy_roots={"train-root"}
            ),
            {"train-root"},
        )
        session, _ = self.frozen()
        result = session.answer(
            self.q, select, Reader(), withdrawals=lambda: {"unrelated"}
        )
        self.assertEqual(result["record"]["status"], "succeeded")
        for key, value in (("bytes", True), ("content_sha256", "wrong"), ("scope", "")):
            bad = [entries[0] | {key: value}]
            with self.assertRaises(ValueError):
                validate_support(bad, through="2024-01-02", policy_roots={"train-root"})


if __name__ == "__main__":
    unittest.main()
