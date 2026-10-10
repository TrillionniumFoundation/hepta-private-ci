"""Actual local journal/reopen/lock tests with an explicit fixture reader."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from evidence_bundle import EvidenceBundle, build_windows
from frozen_memory_session import FrozenMemorySession, exclusive, freeze
from native import Document, Question, digest


class Reader:
    identity = "f" * 64

    def __init__(self):
        self.calls = 0
        self.after = lambda: None
        self.drifted = False

    def verify_frozen(self):
        if self.drifted:
            raise ValueError("reader changed")

    def answer(self, query, bundle, originals, **kwargs):
        self.calls += 1
        self.after()
        return "fixture answer", dict(reader_identity=self.identity, bundle_digest=bundle.seal(),
            delivered_evidence=bundle.delivered(), input_tokens=12, generated_tokens=3)


def select(query, documents, frontier, policy, revoked):
    spans, _ = build_windows(documents)
    return EvidenceBundle(digest(asdict(query)), frontier, spans[:2], "ranked")


class FrozenSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "session"
        self.docs = (Document("d", "r", "scope", "episode", "2024-01-01", "source before task"),)
        self.q = Question("q", "family", "scope", "What happened?", "2024-02-01")
        self.sha = freeze(self.root, self.docs, through="2024-01-02", policy_bytes=b'{"ranked":true}',
                          policy_roots={"r"}, reader_identity=Reader.identity, source_commit="a"*40)
        self.session = FrozenMemorySession(self.root, expected_snapshot=self.sha)
        self.reader = Reader()

    def answer(self, **kwargs):
        return self.session.answer(self.q, select, self.reader, withdrawals=lambda: set(), **kwargs)

    def test_state_committed_before_actual_read_and_reopen_no_second_model_call(self):
        def check_start():
            starts = list(self.root.glob("*.started.json"))
            self.assertEqual(len(starts), 1)
            record = json.loads(starts[0].read_text())
            self.assertGreaterEqual(record["exposed_at_unix_ns"], self.session.state["committed_at_unix_ns"])
        self.reader.after = check_start
        result = self.answer()
        reopened = FrozenMemorySession(self.root, expected_snapshot=self.sha)
        self.assertEqual(reopened.replay(self.q, withdrawals=lambda: set(), expected_result_sha256=result["result_sha256"]), result)
        self.assertEqual(self.reader.calls, 1)
        with self.assertRaises(ValueError):
            self.answer()
        self.assertEqual(self.reader.calls, 1)
        self.assertEqual(result["record"]["query_train_tokens"], 0)
        self.assertFalse(result["record"]["prospective_window_attested"])

    def test_query_before_cutoff_cross_scope_and_new_reader_reject_without_generation(self):
        for q in (replace(self.q, observed_at="2024-01-02"), replace(self.q, scope="private")):
            with self.assertRaises(ValueError):
                self.session.answer(q, select, self.reader, withdrawals=lambda: set())
        self.reader.identity = "a" * 64
        with self.assertRaises(ValueError):
            self.answer()
        self.assertEqual(self.reader.calls, 0)

    def test_query_time_policy_update_is_not_consolidation(self):
        self.reader.after = lambda: (self.root / "policy.bin").write_bytes(b'bad')
        with self.assertRaises(ValueError):
            self.answer()
        records = [json.loads(p.read_text()) for p in self.root.glob("*.result.json")]
        self.assertEqual(records[0]["status"], "failed")
        self.assertNotIn("answer", records[0])

    def test_revoke_during_call_blocks_release_and_old_snapshot_replay(self):
        revoked = set()
        self.reader.after = lambda: revoked.add("r")
        with self.assertRaises(ValueError):
            self.session.answer(self.q, select, self.reader, withdrawals=lambda: revoked)
        with self.assertRaises(ValueError):
            self.session.replay(self.q, withdrawals=lambda: revoked, expected_result_sha256="0"*64)
        self.assertEqual(self.reader.calls, 1)

    def test_real_file_lock_excludes_second_writer(self):
        with exclusive(self.root):
            with self.assertRaises(BlockingIOError):
                self.answer()
        self.assertEqual(self.reader.calls, 0)
        self.answer()
        self.assertEqual(self.reader.calls, 1)

    def test_interrupted_attempt_is_indeterminate_not_automatic_regeneration(self):
        path = self.root / (digest(asdict(self.q)) + ".started.json")
        path.write_text('{}')
        with self.assertRaises(ValueError):
            self.answer()
        with self.assertRaises(ValueError):
            self.session.replay(self.q, withdrawals=lambda: set(), expected_result_sha256="0"*64)
        self.assertEqual(self.reader.calls, 0)

    def test_future_experience_and_policy_ancestry_fail_before_commit(self):
        for docs, roots in (([replace(self.docs[0], observed_at="2025-01-01")], {"r"}),
                            (self.docs, {"unrelated"})):
            with self.assertRaises(ValueError):
                freeze(self.root.with_name("bad"), docs, through="2024-01-02",
                       policy_bytes=b'{}', policy_roots=roots,
                       reader_identity=Reader.identity, source_commit="a"*40)
        self.assertFalse(self.root.with_name("bad").exists())

    def test_oracle_cannot_enter_online_path(self):
        def oracle(*args):
            return replace(select(*args), mode="reviewed_minimal")
        with self.assertRaises(ValueError):
            self.session.answer(self.q, oracle, self.reader, withdrawals=lambda: set())
        self.assertEqual(self.reader.calls, 0)

    def test_final_reader_mutation_is_a_failed_attempt(self):
        self.reader.after = lambda: setattr(self.reader, "drifted", True)
        with self.assertRaises(ValueError):
            self.answer()
        self.assertEqual(self.reader.calls, 1)

    def test_replay_requires_the_previously_received_result_digest(self):
        result = self.answer()
        path = next(self.root.glob("*.result.json"))
        changed = json.loads(path.read_text())
        changed["answer"] = "fabricated replay"
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            self.session.replay(self.q, withdrawals=lambda: set(),
                                expected_result_sha256=result["result_sha256"])
        self.assertEqual(self.reader.calls, 1)

    def test_snapshot_digest_and_missing_ready_fail_closed(self):
        with self.assertRaises(ValueError):
            FrozenMemorySession(self.root, expected_snapshot="0"*64)
        (self.root / "READY.json").unlink()
        with self.assertRaises(FileNotFoundError):
            FrozenMemorySession(self.root, expected_snapshot=self.sha)


if __name__ == "__main__":
    unittest.main()
