"""Execute migration-13 and production scheduling SQL against real SQLite."""
import json
import re
import sqlite3
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from channel_matrix_diagnostics import inspect, prometheus


class RecoverySqlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve() / 'owner.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('CREATE TABLE _sqlx_migrations(version INTEGER, success INTEGER)')
        for p in sorted((ROOT / 'codex-rs/hepta-matrix-store/migrations').glob('*.sql')):
            self.db.executescript(p.read_text())
            self.db.execute('INSERT INTO _sqlx_migrations VALUES (?,1)', (int(p.name[:4]),))
        self.db.execute("INSERT INTO room_bindings VALUES ('!r:t',?,'@bot:t',1,1,1)", ('0'*36,))
        for event in ('$old', '$new'):
            self.db.execute('''INSERT INTO inbox_events(event_id,room_id,sender_user_id,event_type,
              payload,payload_sha256,binding_revision,generation,origin_server_ts_ms,received_at_ms,state)
              VALUES (?,'!r:t','@sender:t','m.room.message',?, ?,1,1,1,1,'pending')''',
                            (event, b'PRIVATE_BODY', 'a'*64))
        self.db.commit()
        rust = (ROOT / 'codex-rs/hepta-matrix-store/src/recovery.rs').read_text()
        self.due = re.search(r'"(SELECT i.event_id FROM matrix_visible_inbox_events_v2 i.*?LIMIT \?)"', rust, re.S).group(1)
        self.finish = re.search(r'"(UPDATE matrix_inbox_recovery SET outcome=.*?last_started_at_ms <= \?)"', rust, re.S).group(1)

    def reserve(self, event='$old', at=10):
        self.db.execute("INSERT INTO matrix_inbox_recovery VALUES (?,1,?,?,'running',NULL)", (event, at, at+30000))
        self.db.commit()

    def test_unattempted_work_advances_and_interrupted_identity_stays_delayed(self):
        self.reserve()
        self.assertEqual(self.db.execute(self.due, (20, 2)).fetchall(), [('$new',)])
        self.assertEqual(self.db.execute(self.due, (40000, 2)).fetchall(), [('$new',), ('$old',)])
        self.assertEqual(self.db.execute("SELECT state FROM inbox_events WHERE event_id='$old'").fetchone(), ('pending',))

    def test_quarantine_survives_reopen_and_forbids_reactivation(self):
        self.reserve()
        self.db.execute(self.finish, ('quarantined','identity_conflict',20,'$old',1,20))
        self.db.commit()
        with sqlite3.connect(self.path) as reopened:
            self.assertEqual(reopened.execute(self.due, (40000, 2)).fetchall(), [('$new',)])
            with self.assertRaises(sqlite3.IntegrityError):
                reopened.execute("UPDATE matrix_inbox_recovery SET outcome='ready',failure_class=NULL WHERE event_id='$old'")

    def test_stale_completion_cannot_modify_new_attempt(self):
        self.reserve()
        self.db.execute("UPDATE matrix_inbox_recovery SET attempts=2,last_started_at_ms=20 WHERE event_id='$old'")
        self.assertEqual(self.db.execute(self.finish, ('retry','dependency_unavailable',30,'$old',1,30)).rowcount, 0)
        self.assertEqual(self.db.execute(self.finish, ('retry','dependency_unavailable',30,'$old',2,30)).rowcount, 1)

    def test_identity_attempt_and_clock_cannot_roll_back(self):
        self.reserve()
        for clause in ("event_id='$new'", 'attempts=0', 'last_started_at_ms=9', 'next_attempt_at_ms=0'):
            with self.subTest(clause=clause), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute('UPDATE matrix_inbox_recovery SET '+clause+" WHERE event_id='$old'")

    def test_quarantine_requires_typed_safe_reason_and_history_cannot_be_deleted(self):
        self.reserve()
        for sql in ("UPDATE matrix_inbox_recovery SET outcome='quarantined'", "UPDATE matrix_inbox_recovery SET outcome='retry',failure_class='PRIVATE_ERROR'", 'DELETE FROM matrix_inbox_recovery'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)

    def test_selected_event_is_parameterized_and_labels_exclude_identifiers(self):
        self.reserve()
        self.db.execute(self.finish, ('quarantined','binding_unrecoverable',20,'$old',1,20))
        self.db.commit()
        row = inspect(self.path, 100, event='$old')
        self.assertEqual(row['oldest_pending_inbox_age_ms'], 99)
        self.assertEqual(row['selected_event']['attempts'], 1)
        self.assertEqual(row['selected_event']['failure_class'], 'binding_unrecoverable')
        self.assertEqual(row['recovery']['quarantined'], 1)
        for value in ('PRIVATE_BODY', '$old', '@sender:t', '!r:t'):
            self.assertNotIn(value, json.dumps(row)+prometheus(row))
        self.assertEqual(inspect(self.path, 100, event="$old' OR 1=1 --")['selected_event'], {'reason':'not_visible_or_absent'})

    def test_fair_query_preserves_processed_filter(self):
        self.db.execute("UPDATE inbox_events SET state='processed',processed_at_ms=2 WHERE event_id='$old'")
        self.assertEqual(self.db.execute(self.due, (100, 2)).fetchall(), [('$new',)])
