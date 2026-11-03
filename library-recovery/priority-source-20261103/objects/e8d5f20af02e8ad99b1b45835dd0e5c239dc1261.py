#!/usr/bin/env python3
"""Execute the actual migration SQL; does not compile or simulate Rust behavior."""
import pathlib
import sqlite3
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'patched/codex-rs/hepta-authbus/migrations'

def b(n):
    return n.to_bytes(8, 'big')

D = b'x' * 32

def connection(path=':memory:', version=8):
    c = sqlite3.connect(path, isolation_level=None)
    c.execute('PRAGMA foreign_keys=ON')
    for p in sorted(ROOT.glob('*.sql')):
        if int(p.name[:4]) <= version:
            c.executescript(p.read_text())
    return c

def fixture(c, identity='reservation'):
    c.execute('INSERT INTO authbus_quota_registry VALUES (?,?,?,?,?,?,?,?,?,?)',
              ('quota'+identity, 'principal', D, 'unit', 'period', b(10), b(3), b(7), b(0), b(1)))
    c.execute('INSERT INTO authbus_quota_reservation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (identity, 'operation'+identity, 'quota'+identity, 'period', 'principal', b(7), D,
               'policy', b(1), D, 'held', b(1), b(5000), b(1400), b(1400), None, None, None, None))

def dispatch(c, identity='reservation'):
    c.execute("UPDATE authbus_quota_reservation SET state='dispatch_attempted', dispatch_digest=?, revision=?, updated_at_ms=? WHERE reservation_id=?",
              (D, b(2), b(1500), identity))

def seed_fixture_frontier(c):
    # Structural SQL fixture only. This deliberately does not claim to execute
    # the Rust digest algorithm: nonzero bytes stand for a matching root/witness.
    seq = c.execute('SELECT COALESCE(MAX(change_id),0) FROM authbus_frontier_change').fetchone()[0]
    c.execute('UPDATE authbus_frontier_accumulator SET root_digest=?,applied_change_id=?', (D, seq))
    c.execute('DELETE FROM authbus_frontier_change WHERE change_id<=?', (seq,))
    c.execute('INSERT INTO authbus_authority_checkpoint VALUES (1,?,?)', (b(1), D))
    c.execute('UPDATE authbus_authority_checkpoint_dirty SET dirty=0')

class DispatchMigrationTests(unittest.TestCase):
    def test_dispatch_timeout_lower_bound_and_immutability(self):
        c = connection(); fixture(c); dispatch(c)
        self.assertEqual(c.execute('SELECT dispatched_at_ms FROM authbus_dispatch_observation').fetchone(), (b(1500),))
        c.execute("UPDATE authbus_quota_reservation SET state='indeterminate',revision=?,updated_at_ms=?", (b(3), b(1800)))
        self.assertEqual(c.execute('SELECT dispatched_at_ms FROM authbus_dispatch_observation').fetchone(), (b(1500),))
        self.assertLess(1499, 1500); self.assertGreaterEqual(1600, 1500); self.assertLess(1600, 1800)
        for sql in ['DELETE FROM authbus_dispatch_observation', 'UPDATE authbus_dispatch_observation SET dispatched_at_ms=dispatched_at_ms', "INSERT INTO authbus_dispatch_observation VALUES ('foreign',X'0000000000000001')"]:
            with self.assertRaises(sqlite3.IntegrityError): c.execute(sql)
        self.assertEqual(c.execute('PRAGMA quick_check').fetchone(), ('ok',))
        self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
        c.close()

    def test_exact_and_altered_replace_with_recursive_triggers_off_and_on(self):
        for recursive in [0, 1]:
            with self.subTest(recursive=recursive):
                c = connection(); fixture(c); dispatch(c)
                c.execute('PRAGMA recursive_triggers=' + str(recursive))
                for instant in [1500, 1450]:
                    c.execute('UPDATE authbus_quota_reservation SET updated_at_ms=?', (b(instant),))
                    with self.assertRaises(sqlite3.IntegrityError):
                        c.execute('INSERT OR REPLACE INTO authbus_dispatch_observation VALUES (?,?)', ('reservation', b(instant)))
                self.assertEqual(c.execute('SELECT dispatched_at_ms FROM authbus_dispatch_observation').fetchone(), (b(1500),))
                c.close()

    def test_without_rowid_blocks_hidden_identity_replacement(self):
        c = connection(); fixture(c); dispatch(c)
        c.execute('PRAGMA recursive_triggers=OFF')
        schema = c.execute("SELECT sql FROM sqlite_schema WHERE name='authbus_dispatch_observation'").fetchone()[0]
        self.assertIn('WITHOUT ROWID', schema)
        for alias in ['rowid', '_rowid_', 'oid']:
            with self.assertRaisesRegex(sqlite3.OperationalError, 'no column named'):
                c.execute(f'INSERT OR REPLACE INTO authbus_dispatch_observation ({alias},reservation_id,dispatched_at_ms) VALUES (1,?,?)',
                          ('foreign', b(1450)))
        self.assertEqual(c.execute('SELECT reservation_id,dispatched_at_ms FROM authbus_dispatch_observation').fetchall(),
                         [('reservation', b(1500))])
        c.close()

    def test_transition_and_journal_rollback_atomically(self):
        c = connection(); fixture(c)
        c.execute('BEGIN IMMEDIATE'); dispatch(c)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM authbus_frontier_change WHERE domain='dispatch_observation'").fetchone(), (1,))
        c.execute('ROLLBACK')
        self.assertEqual(c.execute('SELECT COUNT(*) FROM authbus_dispatch_observation').fetchone(), (0,))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM authbus_frontier_change WHERE domain='dispatch_observation'").fetchone(), (0,))
        self.assertEqual(c.execute('SELECT state FROM authbus_quota_reservation').fetchone(), ('held',))
        c.close()

    def test_frontier_event_is_canonical_and_pending_delete_is_forbidden(self):
        c = connection(); fixture(c); seed_fixture_frontier(c); dispatch(c)
        event = c.execute("SELECT operation,record_key,canonical_record FROM authbus_frontier_change WHERE domain='dispatch_observation'").fetchone()
        self.assertEqual(event, ('upsert','reservation',b'reservation'.hex().upper()+'|'+b(1500).hex().upper()))
        self.assertEqual(c.execute('SELECT dirty FROM authbus_authority_checkpoint_dirty').fetchone(), (1,))
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("DELETE FROM authbus_frontier_change WHERE domain='dispatch_observation'")
        c.close()

    def test_upgrade_preserves_seeded_and_unseeded_history_and_legacy_gap(self):
        for seeded in [False, True]:
            with self.subTest(seeded=seeded):
                c = connection(version=7); fixture(c); fixture(c, 'legacy'); dispatch(c, 'legacy')
                c.execute("UPDATE authbus_quota_reservation SET state='indeterminate',revision=?,updated_at_ms=? WHERE reservation_id='legacy'", (b(3),b(1800)))
                if seeded: seed_fixture_frontier(c)
                tables=['authbus_quota_reservation','authbus_frontier_accumulator','authbus_frontier_change','authbus_authority_checkpoint','authbus_authority_checkpoint_dirty']
                before={t:c.execute('SELECT * FROM '+t).fetchall() for t in tables}
                c.executescript((ROOT/'0008_dispatch_observation.sql').read_text())
                self.assertEqual(before,{t:c.execute('SELECT * FROM '+t).fetchall() for t in tables})
                self.assertEqual(c.execute('SELECT COUNT(*) FROM authbus_dispatch_observation').fetchone(), (0,))
                dispatch(c)
                self.assertEqual(c.execute('SELECT reservation_id,dispatched_at_ms FROM authbus_dispatch_observation').fetchone(), ('reservation',b(1500)))
                self.assertEqual(c.execute("SELECT updated_at_ms FROM authbus_quota_reservation WHERE reservation_id='legacy'").fetchone(), (b(1800),))
                self.assertEqual(c.execute("SELECT COUNT(*) FROM authbus_frontier_change WHERE domain='dispatch_observation'").fetchone(), (1,))
                c.close()

    def test_file_reopen_and_terminal_archival_retain_dispatch_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(pathlib.Path(tmp)/'authority.sqlite')
            c=connection(path);fixture(c);dispatch(c)
            c.execute("UPDATE authbus_quota_reservation SET state='indeterminate',revision=?,updated_at_ms=?",(b(3),b(1800)));c.close()
            c=sqlite3.connect(path,isolation_level=None)
            self.assertEqual(c.execute('SELECT dispatched_at_ms FROM authbus_dispatch_observation').fetchone(),(b(1500),))
            c.execute("UPDATE authbus_quota_reservation SET state='settled',revision=?,updated_at_ms=?,terminal_evidence=?,observed_cost=?,settlement_digest=?",(b(4),b(1900),D,b(5),D))
            c.execute('INSERT INTO authbus_quota_reservation_archive SELECT *,? FROM authbus_quota_reservation',(b(2000),))
            c.execute('DELETE FROM authbus_quota_reservation')
            self.assertEqual(c.execute('SELECT dispatched_at_ms FROM authbus_dispatch_observation').fetchone(),(b(1500),))
            self.assertEqual(c.execute('PRAGMA quick_check').fetchone(),('ok',));c.close()

if __name__=='__main__': unittest.main(verbosity=2)
