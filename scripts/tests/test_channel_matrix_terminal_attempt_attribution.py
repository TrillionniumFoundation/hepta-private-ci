#!/usr/bin/env python3
"""Migration regression for stable-transaction terminal attempt attribution."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "codex-rs/hepta-matrix-store/migrations"
AGENT_ID = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"


def digest(character: str) -> str:
    return character * 64


def migrated_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def seed_entered_attempt_then_unentered_retry(connection: sqlite3.Connection) -> None:
    connection.execute("INSERT INTO matrix_meta VALUES (1, 1, ?)", (AGENT_ID,))
    connection.execute(
        "INSERT INTO room_bindings VALUES ('!room:test', ?, '@agent:test', 1, 1, 1)",
        (AGENT_ID,),
    )
    connection.execute(
        """INSERT INTO outbox_messages (
               stable_txn_id, room_id, kind, payload, payload_sha256,
               logical_txn_count, binding_revision, generation, state,
               attempts, next_attempt_at_ms, lease_until_ms, created_at_ms,
               updated_at_ms, sent_event_id, logical_outbox_id
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "txn", "!room:test", "final", b"payload", digest("1"), 1, 1, 1,
            "in_flight", 1, 0, 100, 1, 1, None, "logical",
        ),
    )
    connection.execute(
        """INSERT INTO matrix_dispatch_ledger (
               stable_txn_id, operation_id, logical_outbox_id, room_id,
               binding_revision, generation, payload_sha256, state, attempts,
               prepared_at_ms, updated_at_ms
           ) VALUES ('txn', 'operation', 'logical', '!room:test',
                     1, 1, ?, 'dispatched', 1, 1, 1)""",
        (digest("1"),),
    )

    # Attempt one crossed the final-use boundary.
    connection.execute(
        "INSERT INTO matrix_dispatch_attempt_claims VALUES (?, ?, ?, ?, ?, ?)",
        ("txn", 1, 1, digest("a"), 1, 100),
    )
    connection.execute(
        "INSERT INTO matrix_dispatch_active_claims VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("txn", 1, 1, digest("a"), "dispatching", 1, 100),
    )
    connection.execute(
        """INSERT INTO matrix_dispatch_authority_claims VALUES (
               ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "txn", 1, "operation", AGENT_ID, "destination", "https://hs.test",
            "@agent:test", "DEVICE", 1, 1, 1, "grant-1", digest("2"),
            digest("3"), digest("1"), 90, 2,
        ),
    )
    connection.execute(
        "INSERT INTO matrix_dispatch_authority_witnesses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("txn", 1, 1, digest("a"), 1, 1, "grant-1", digest("4"), digest("5"), 3),
    )
    connection.execute(
        "INSERT INTO matrix_dispatch_content_bindings VALUES (?, ?, ?, ?, ?, ?)",
        ("txn", 1, digest("6"), digest("3"), digest("1"), 2),
    )
    connection.execute(
        "INSERT INTO matrix_dispatch_use_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "txn", 1, 1, digest("a"), "operation", AGENT_ID, "destination",
            digest("2"), digest("3"), digest("6"), digest("4"), 4,
        ),
    )

    # Attempt two only reclaimed the stable transaction; it never received
    # authority and never crossed the physical-send boundary.
    connection.execute("DELETE FROM matrix_dispatch_active_claims WHERE stable_txn_id = 'txn'")
    connection.execute(
        "UPDATE outbox_messages SET attempts = 2, lease_until_ms = 200, updated_at_ms = 101 WHERE stable_txn_id = 'txn'"
    )
    connection.execute(
        "UPDATE matrix_dispatch_ledger SET attempts = 2, updated_at_ms = 101 WHERE stable_txn_id = 'txn'"
    )
    connection.execute(
        "INSERT INTO matrix_dispatch_attempt_claims VALUES (?, ?, ?, ?, ?, ?)",
        ("txn", 2, 2, digest("b"), 101, 200),
    )
    connection.execute(
        "INSERT INTO matrix_dispatch_active_claims VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("txn", 2, 2, digest("b"), "claimed", 101, 200),
    )


class TerminalAttemptAttributionTest(unittest.TestCase):
    def assert_terminal_attribution(self, state: str, event_kind: str) -> None:
        connection = migrated_database()
        self.addCleanup(connection.close)
        seed_entered_attempt_then_unentered_retry(connection)
        if state == "succeeded":
            connection.execute(
                """UPDATE matrix_dispatch_ledger
                   SET state = 'succeeded', terminal_event_id = '$event',
                       send_observation_sha256 = ?, terminal_observed_at_ms = 150,
                       updated_at_ms = 150
                   WHERE stable_txn_id = 'txn'""",
                (digest("7"),),
            )
        else:
            connection.execute(
                """UPDATE matrix_dispatch_ledger
                   SET state = 'redacted', terminal_event_id = '$event',
                       redaction_observation_sha256 = ?, terminal_observed_at_ms = 150,
                       updated_at_ms = 150
                   WHERE stable_txn_id = 'txn'""",
                (digest("8"),),
            )

        terminal_events = connection.execute(
            """SELECT attempt, event_kind, event_id
               FROM matrix_dispatch_attempt_events
               WHERE event_kind = ?""",
            (event_kind,),
        ).fetchall()
        self.assertEqual(terminal_events, [(1, event_kind, "$event")])
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM matrix_dispatch_active_claims WHERE stable_txn_id = 'txn'"
            ).fetchone()[0],
            0,
        )

    def test_confirmed_event_uses_entered_attempt_not_later_claim(self) -> None:
        self.assert_terminal_attribution("succeeded", "confirmed")

    def test_redaction_event_uses_entered_attempt_not_later_claim(self) -> None:
        self.assert_terminal_attribution("redacted", "redacted")


if __name__ == "__main__":
    unittest.main()
