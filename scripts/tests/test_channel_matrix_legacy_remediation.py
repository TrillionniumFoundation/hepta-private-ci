"""Migration-only legacy-hold remediation; no native or network claim."""
from pathlib import Path
import sqlite3
import unittest

SQL = (
    Path(__file__).resolve().parents[2]
    / "codex-rs/hepta-matrix-store/migrations/0011_matrix_legacy_hold_remediation.sql"
).read_text()
MAX_I64 = 9223372036854775807


class LegacyHoldRemediationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(
            '''
            CREATE TABLE outbox_messages(
                stable_txn_id TEXT PRIMARY KEY,
                logical_outbox_id TEXT NOT NULL,
                room_id TEXT NOT NULL,
                binding_revision INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                payload_sha256 TEXT NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                next_attempt_at_ms INTEGER NOT NULL,
                lease_until_ms INTEGER,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                sent_event_id TEXT
            );
            CREATE TABLE matrix_dispatch_legacy_content_holds(
                stable_txn_id TEXT PRIMARY KEY,
                inherited_attempts INTEGER NOT NULL
            );
            CREATE TABLE matrix_dispatch_content_bindings(
                stable_txn_id TEXT PRIMARY KEY
            );
            CREATE TABLE matrix_dispatch_ledger(
                stable_txn_id TEXT PRIMARY KEY,
                operation_id TEXT UNIQUE NOT NULL,
                logical_outbox_id TEXT NOT NULL,
                room_id TEXT NOT NULL,
                binding_revision INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                payload_sha256 TEXT NOT NULL,
                authority_epoch INTEGER,
                grant_id TEXT,
                grant_payload_sha256 TEXT,
                state TEXT NOT NULL,
                accepted_event_id TEXT,
                terminal_event_id TEXT,
                transport_observation_sha256 TEXT,
                send_observation_sha256 TEXT,
                redaction_observation_sha256 TEXT,
                attempts INTEGER NOT NULL,
                prepared_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                terminal_observed_at_ms INTEGER
            );
            CREATE TABLE matrix_dispatch_attempt_claims(
                stable_txn_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                lease_epoch INTEGER NOT NULL,
                claim_token_sha256 TEXT NOT NULL,
                claimed_at_ms INTEGER NOT NULL,
                lease_until_ms INTEGER NOT NULL,
                PRIMARY KEY(stable_txn_id, attempt)
            );
            CREATE TABLE matrix_dispatch_active_claims(
                stable_txn_id TEXT PRIMARY KEY,
                attempt INTEGER NOT NULL,
                lease_epoch INTEGER NOT NULL,
                claim_token_sha256 TEXT NOT NULL,
                phase TEXT NOT NULL,
                claimed_at_ms INTEGER NOT NULL,
                lease_until_ms INTEGER NOT NULL
            );
            CREATE TABLE matrix_dispatch_attempt_events(
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                stable_txn_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                lease_epoch INTEGER NOT NULL,
                claim_token_sha256 TEXT NOT NULL,
                event_kind TEXT NOT NULL,
                failure_class TEXT,
                retry_after_ms INTEGER,
                event_id TEXT,
                detail_sha256 TEXT,
                recorded_at_ms INTEGER NOT NULL
            );
            '''
        )

    def add_message(
        self,
        txn,
        *,
        state,
        attempts,
        sent_event_id=None,
        updated_at_ms=20,
        active_phase=None,
    ):
        token = (txn[0] if txn else "a") * 64
        self.db.execute(
            "INSERT INTO outbox_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                txn,
                f"logical-{txn}",
                "!room:example.test",
                1,
                1,
                "a" * 64,
                state,
                attempts,
                5,
                100 if state == "in_flight" else None,
                1,
                updated_at_ms,
                sent_event_id,
            ),
        )
        self.db.execute(
            "INSERT INTO matrix_dispatch_legacy_content_holds VALUES (?,?)",
            (txn, attempts),
        )
        if active_phase is not None:
            self.db.execute(
                "INSERT INTO matrix_dispatch_attempt_claims VALUES (?,?,?,?,?,?)",
                (txn, attempts, attempts, token, 10, 100),
            )
            self.db.execute(
                "INSERT INTO matrix_dispatch_active_claims VALUES (?,?,?,?,?,?,?)",
                (txn, attempts, attempts, token, active_phase, 10, 100),
            )
            self.db.execute(
                '''INSERT INTO matrix_dispatch_attempt_events(
                       stable_txn_id, attempt, lease_epoch, claim_token_sha256,
                       event_kind, failure_class, retry_after_ms, event_id,
                       detail_sha256, recorded_at_ms
                   ) VALUES (?,?,?,?, 'claimed', NULL, NULL, NULL, NULL, 10)''',
                (txn, attempts, attempts, token),
            )

    def apply(self):
        self.db.executescript(SQL)

    def test_active_claims_are_closed_and_queue_rows_are_parked(self):
        self.add_message(
            "claimed",
            state="in_flight",
            attempts=2,
            active_phase="claimed",
        )
        self.add_message(
            "dispatching",
            state="in_flight",
            attempts=3,
            active_phase="dispatching",
        )
        self.db.execute(
            "INSERT INTO matrix_dispatch_ledger VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "dispatching",
                "matrix.send:dispatching",
                "logical-dispatching",
                "!room:example.test",
                1,
                1,
                "a" * 64,
                None,
                None,
                None,
                "failed",
                None,
                None,
                "b" * 64,
                None,
                None,
                3,
                1,
                20,
                20,
            ),
        )

        self.apply()

        self.assertEqual(
            self.db.execute(
                "SELECT stable_txn_id, state, next_attempt_at_ms, lease_until_ms "
                "FROM outbox_messages ORDER BY stable_txn_id"
            ).fetchall(),
            [
                ("claimed", "retry_scheduled", MAX_I64, None),
                ("dispatching", "retry_scheduled", MAX_I64, None),
            ],
        )
        self.assertEqual(
            self.db.execute(
                "SELECT stable_txn_id, state, attempts, terminal_observed_at_ms "
                "FROM matrix_dispatch_ledger ORDER BY stable_txn_id"
            ).fetchall(),
            [
                ("claimed", "indeterminate", 2, None),
                ("dispatching", "indeterminate", 3, None),
            ],
        )
        self.assertEqual(
            self.db.execute(
                "SELECT stable_txn_id, event_kind, failure_class "
                "FROM matrix_dispatch_attempt_events "
                "WHERE event_kind IN ('expired','indeterminate') "
                "ORDER BY stable_txn_id"
            ).fetchall(),
            [
                ("claimed", "expired", None),
                ("dispatching", "indeterminate", "response_lost"),
            ],
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM matrix_dispatch_active_claims"
            ).fetchone(),
            (0,),
        )

    def test_sent_legacy_row_becomes_accepted_not_confirmed(self):
        self.add_message(
            "sent",
            state="sent",
            attempts=1,
            sent_event_id="$event:example.test",
        )
        self.apply()
        self.assertEqual(
            self.db.execute(
                "SELECT state, accepted_event_id, terminal_event_id, "
                "terminal_observed_at_ms FROM matrix_dispatch_ledger"
            ).fetchone(),
            ("accepted", "$event:example.test", None, None),
        )

    def test_terminal_remote_observation_is_not_reopened(self):
        self.add_message(
            "terminal",
            state="sent",
            attempts=1,
            sent_event_id="$event:example.test",
        )
        self.db.execute(
            "INSERT INTO matrix_dispatch_ledger VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "terminal",
                "matrix.send:terminal",
                "logical-terminal",
                "!room:example.test",
                1,
                1,
                "a" * 64,
                None,
                None,
                None,
                "observed_unqualified",
                "$event:example.test",
                "$event:example.test",
                None,
                "b" * 64,
                None,
                1,
                1,
                20,
                20,
            ),
        )
        self.apply()
        self.assertEqual(
            self.db.execute(
                "SELECT state, terminal_event_id, terminal_observed_at_ms "
                "FROM matrix_dispatch_ledger"
            ).fetchone(),
            ("observed_unqualified", "$event:example.test", 20),
        )

    def test_hold_trigger_blocks_reactivation_but_allows_sync_settlement(self):
        self.add_message("held", state="pending", attempts=1)
        self.apply()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE outbox_messages SET state='in_flight', "
                "next_attempt_at_ms=0, lease_until_ms=10 "
                "WHERE stable_txn_id='held'"
            )
        self.db.execute(
            "UPDATE outbox_messages SET state='sent', "
            "sent_event_id='$event:example.test', lease_until_ms=NULL "
            "WHERE stable_txn_id='held'"
        )
        self.assertEqual(
            self.db.execute(
                "SELECT state, sent_event_id FROM outbox_messages "
                "WHERE stable_txn_id='held'"
            ).fetchone(),
            ("sent", "$event:example.test"),
        )

    def test_trigger_ddl_is_exactly_present(self):
        self.add_message("held", state="pending", attempts=1)
        self.apply()
        statement = next(
            part
            for part in SQL.split("\n\n")
            if part.startswith("CREATE TRIGGER matrix_dispatch_legacy_hold_no_reactivate")
        )
        actual = self.db.execute(
            "SELECT sql FROM sqlite_schema "
            "WHERE name='matrix_dispatch_legacy_hold_no_reactivate'"
        ).fetchone()[0]
        normalize = lambda value: " ".join(value.strip().rstrip(";").split())
        self.assertEqual(normalize(actual), normalize(statement))


if __name__ == "__main__":
    unittest.main()
