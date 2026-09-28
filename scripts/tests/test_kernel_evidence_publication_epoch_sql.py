"""SQL/migration probes only; not a substitute for the Rust product suite."""

from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "codex-rs/hepta-evidence"
SOURCE = MODULE / "src/publication_dispatch.rs"


class PublicationEpochSqlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "evidence.sqlite"
        self.connection = sqlite3.connect(self.database, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        for migration in sorted((MODULE / "migrations").glob("*.sql")):
            self.connection.executescript(migration.read_text(encoding="utf-8"))
        self.connection.execute(
            "INSERT INTO evidence_recovery_identity VALUES (1, 'store:epoch')"
        )
        self.connection.execute(
            "INSERT INTO evidence_publication_owner VALUES (?, ?, ?, ?, ?)",
            ("store:epoch", "owner:epoch", 1, 1000, 100),
        )
        self.connection.execute(
            """INSERT INTO evidence_publication_batches (
                batch_id, store_id, prepared_owner_id, prepared_owner_generation,
                state, first_intent_seq, last_intent_seq, intent_count,
                snapshot_json, snapshot_sha256, expected_frontier_generation,
                expected_frontier_sha256, expected_backend_identity_sha256,
                proposed_frontier_generation, proposed_frontier_sha256,
                backend_identity_sha256, durable_audit_sequence, created_at_ms,
                updated_at_ms
            ) VALUES (?, ?, ?, 1, 'dispatching', 1, 1, 1, '{}', ?, 1, ?, ?, 2, ?, ?, NULL, 100, 100)""",
            (
                "batch:epoch", "store:epoch", "owner:epoch", "a" * 64,
                "b" * 64, "c" * 64, "d" * 64, "c" * 64,
            ),
        )
        self.queries = re.findall(
            r'sqlx::query\(\s*"([^"]+)"', SOURCE.read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        self.connection.close()
        self.temp.cleanup()

    def query(self, fragment: str) -> str:
        matches = [query for query in self.queries if fragment in query]
        self.assertEqual(len(matches), 1, fragment)
        return matches[0]

    def test_every_production_statement_prepares_against_actual_migrations(self) -> None:
        self.assertEqual(len(self.queries), 6)
        for query in self.queries:
            self.connection.execute("EXPLAIN " + query, (None,) * query.count("?"))

    def test_dispatch_join_returns_exact_batch_and_owner(self) -> None:
        query = self.query("SELECT b.store_id")
        row = self.connection.execute(query, ("batch:epoch",)).fetchone()
        self.assertEqual(row["store_id"], "store:epoch")
        self.assertEqual(row["owner_id"], "owner:epoch")
        self.assertEqual(row["owner_generation"], 1)
        self.assertEqual(row["proposed_frontier_generation"], 2)
        self.assertIsNone(self.connection.execute(query, ("batch:other",)).fetchone())

    def test_immediate_epoch_excludes_another_writer_until_release(self) -> None:
        other = sqlite3.connect(self.database, timeout=0, isolation_level=None)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.OperationalError):
                other.execute("BEGIN IMMEDIATE")
            self.connection.execute("ROLLBACK")
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
        finally:
            other.close()

    def test_uncommitted_acknowledgement_preserves_dispatch_identity(self) -> None:
        update = self.query("UPDATE evidence_publication_batches")
        self.connection.execute("BEGIN IMMEDIATE")
        self.assertEqual(self.connection.execute(update, (2, 200, "batch:epoch")).rowcount, 1)
        self.connection.execute("ROLLBACK")
        row = self.connection.execute(self.query("SELECT b.store_id"), ("batch:epoch",)).fetchone()
        self.assertEqual(row["state"], "dispatching")
        self.assertEqual(row["proposed_frontier_sha256"], "d" * 64)

    def test_acknowledged_batch_cannot_be_reopened_for_dispatch(self) -> None:
        self.connection.execute(self.query("UPDATE evidence_publication_batches"), (2, 200, "batch:epoch"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE evidence_publication_batches SET state = 'dispatching', durable_audit_sequence = NULL, updated_at_ms = 300 WHERE batch_id = 'batch:epoch'"
            )
        self.assertEqual(
            self.connection.execute(self.query("SELECT b.store_id"), ("batch:epoch",)).fetchone()["state"],
            "acknowledged",
        )

    def test_trust_generation_and_digest_remain_append_only(self) -> None:
        self.connection.execute(
            """INSERT INTO evidence_trust_acceptance (
                store_id, agent_id, registry_generation, registry_sha256,
                predecessor_sha256, accepted_frontier_generation,
                accepted_frontier_sha256, backend_identity_sha256, accepted_at_ms
            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)""",
            ("store:epoch", "agent:epoch", (1).to_bytes(8, "big"), "a" * 64,
             (1).to_bytes(8, "big"), "b" * 64, "c" * 64, (100).to_bytes(8, "big")),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("UPDATE evidence_trust_acceptance SET registry_sha256 = ?", ("d" * 64,))
        row = self.connection.execute(self.query("SELECT agent_id"), ("store:epoch",)).fetchone()
        self.assertEqual(row["registry_generation"], (1).to_bytes(8, "big"))
        self.assertEqual(row["registry_sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
