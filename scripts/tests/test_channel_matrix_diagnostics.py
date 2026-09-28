"""Real SQLite migrations plus read-only diagnostic/alert contracts."""
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('matrix_diagnostics', ROOT / 'scripts/channel_matrix_diagnostics.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'matrix.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('CREATE TABLE _sqlx_migrations(version INTEGER, success INTEGER)')
        for path in sorted((ROOT / 'codex-rs/hepta-matrix-store/migrations').glob('*.sql')):
            self.db.executescript(path.read_text())
            self.db.execute('INSERT INTO _sqlx_migrations VALUES (?,1)', (int(path.name[:4]),))
        self.db.execute("INSERT INTO room_bindings VALUES ('!r:t', ?, '@a:t',1,1,1)", ('0'*36,))
        self.db.commit()

    def seed(self, *, parked=False):
        self.db.execute('''INSERT INTO outbox_messages(stable_txn_id,room_id,kind,payload,
            payload_sha256,logical_txn_count,binding_revision,generation,state,attempts,
            next_attempt_at_ms,created_at_ms,updated_at_ms,logical_outbox_id)
            VALUES ('txn','!r:t','final',?, ?,1,1,1,'retry_scheduled',1,?,1,1,'logical')''',
            (b'SECRET_BODY_DO_NOT_EXPORT', 'a'*64, diag.MAX_I64 if parked else 100))
        self.db.execute('''INSERT INTO matrix_dispatch_ledger(stable_txn_id,operation_id,
            logical_outbox_id,room_id,binding_revision,generation,payload_sha256,state,
            attempts,prepared_at_ms,updated_at_ms)
            VALUES ('txn','op','logical','!r:t',1,1,?,'indeterminate',1,1,1)''', ('a'*64,))
        self.db.commit()

    def test_empty_database_reports_missing_measurement_not_zero(self):
        row = diag.inspect(self.path, 100)
        self.assertIsNone(row['sync_checkpoint_age_ms'])
        self.assertEqual(row['alerts'], [])
        self.assertFalse(row['authority_granted'])
        text = diag.prometheus(row)
        self.assertIn('hepta_matrix_sync_checkpoint_age_ms_available 0', text)
        self.assertNotIn('hepta_matrix_sync_checkpoint_age_ms 0', text)

    def test_pending_without_sync_and_full_capacity_are_critical(self):
        self.seed()
        row = diag.inspect(self.path, 400_000, capacity=1)
        self.assertEqual(row['admission'], 'blocked_at_unresolved_capacity')
        self.assertEqual([x['code'] for x in row['alerts']],
                         ['unresolved_capacity', 'sync_checkpoint_stale', 'queue_age'])

    def test_read_does_not_change_database_or_expose_payload(self):
        self.seed()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        row = diag.inspect(self.path, 100, transaction='txn')
        self.assertEqual(row['selected']['reason'], 'remote_result_not_yet_reconciled')
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertNotIn('SECRET_BODY', str(row))
        self.assertNotIn('!r:t', diag.prometheus(row))
        self.assertNotIn('txn', str(row))

    def test_parked_effect_never_suggests_a_new_transaction(self):
        self.seed(parked=True)
        row = diag.inspect(self.path, 100, transaction='txn')
        self.assertEqual(row['selected']['retry'], 'forbidden')
        self.assertEqual(row['parked_queue'], 1)

    def test_transaction_parameter_cannot_inject_sql(self):
        self.seed()
        row = diag.inspect(self.path, 100, transaction="txn' OR 1=1 --")
        self.assertEqual(row['selected'], {'reason': 'not_found'})
        self.assertEqual(row['unresolved'], 1)

    def test_failed_migration_is_not_a_healthy_snapshot(self):
        self.db.execute('UPDATE _sqlx_migrations SET success=0 WHERE version=12')
        self.db.commit()
        with self.assertRaises(ValueError):
            diag.inspect(self.path, 100)

    def test_future_checkpoint_is_not_zero_lag(self):
        self.db.execute('INSERT INTO matrix_sync_checkpoint VALUES (1,?,1,1,?,200)', ('0'*36,'SECRET_CURSOR'))
        self.db.commit()
        with self.assertRaises(ValueError):
            diag.inspect(self.path, 100)

    def test_missing_and_symlink_paths_are_rejected(self):
        link = self.path.parent / 'alias'; link.symlink_to(self.path)
        for path in (link, self.path.parent/'missing'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                diag.inspect(path, 100)
