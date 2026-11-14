"""Real SQLite qualification only; no new production upgrade permission."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import preflight as p

HERE = Path(__file__).resolve().parent
OWNER = 'preflight-fixture-owner'

def u64(value):
    return value.to_bytes(8, 'big')


def checkpoint(connection, root, generation=1):
    last = connection.execute('SELECT COALESCE(MAX(change_id),0) FROM authbus_frontier_change').fetchone()[0]
    connection.execute('UPDATE authbus_frontier_accumulator SET root_digest=?,applied_change_id=? WHERE singleton=1', (root,last))
    connection.execute('DELETE FROM authbus_frontier_change WHERE change_id<=?', (last,))
    connection.execute('INSERT INTO authbus_authority_checkpoint(singleton,generation,checkpoint_digest) VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET generation=excluded.generation,checkpoint_digest=excluded.checkpoint_digest', (u64(generation),root))
    connection.execute('UPDATE authbus_authority_checkpoint_dirty SET dirty=0 WHERE singleton=1')
    connection.commit()


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.database = self.root/'state'/'authority.sqlite'
        self.database.parent.mkdir(mode=0o700)
        self.witness = self.root/'witness'/'checkpoint.json'
        self.witness.parent.mkdir(mode=0o700)
        self.writer = sqlite3.connect(self.database)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('PRAGMA wal_autocheckpoint=0')
        p.initialize_fixture(self.writer)
        self.full = p.full_frontier(self.writer)
        checkpoint(self.writer,self.full)
        self.write_witness(self.full)
        self.audit=[]

    def tearDown(self):
        self.writer.close()
        self.temp.cleanup()

    def write_witness(self, digest, generation=1, owner=OWNER):
        self.witness.write_text(json.dumps({'schema_version':1,'owner_id':owner,'generation':generation,'digest':digest.hex()}))
        self.witness.chmod(0o600)

    def run_preflight(self, **kwargs):
        return p.preflight(self.database,self.witness,OWNER,self.audit,**kwargs)

    def add_time(self):
        self.writer.execute('INSERT INTO authbus_trusted_time(singleton,wall_time_ms,source_revision,source_digest) VALUES(1,?,?,?)', (u64(2000),u64(1),hashlib.sha256(b'new-time').digest()))
        self.writer.commit()

    def test_native_generated_full_frontier_vectors_match(self):
        native=json.loads((HERE/'native-vector.json').read_text())
        self.assertEqual(self.full.hex(),native['empty'])
        connection=sqlite3.connect((HERE/'native-vector.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            self.assertEqual(p.full_frontier(connection).hex(),native['populated'])
            self.assertEqual(connection.execute(p.SCHEMA_SQL).fetchall(),p.expected_schema())
            self.assertEqual(connection.execute('SELECT version,checksum FROM _sqlx_migrations ORDER BY version').fetchall(),p.migration_identity())
        finally:
            connection.close()

    def test_committed_wal_is_visible_without_mutating_database(self):
        self.assertTrue(Path(str(self.database)+'-wal').exists())
        before=p.physical_bytes(self.database)
        report=self.run_preflight()
        self.assertEqual(report['full_digest'],self.full.hex())
        self.assertEqual(before,p.physical_bytes(self.database))
        self.assertEqual(self.audit[0],('witness_validated',1))
        self.assertFalse(any(event[0]=='denied' for event in self.audit))
        # Native-main-file-only read would miss schema/rows still in committed WAL.
        main_copy=self.root/'main-only.sqlite'
        shutil.copyfile(self.database,main_copy)
        standalone=sqlite3.connect(main_copy)
        try:
            self.assertNotEqual(standalone.execute(p.SCHEMA_SQL).fetchall(),p.expected_schema())
        finally:
            standalone.close()

    def test_no_sidecar_cold_state_rejects_before_sql_without_creating_files(self):
        self.writer.close()
        self.assertFalse(Path(str(self.database)+'-wal').exists())
        self.assertFalse(Path(str(self.database)+'-shm').exists())
        before=p.physical_bytes(self.database)
        with self.assertRaisesRegex(p.Rejected,'no-sidecar'):
            self.run_preflight()
        self.assertFalse(any(event[0]=='sql' for event in self.audit))
        self.assertEqual(before,p.physical_bytes(self.database))
        self.assertFalse(Path(str(self.database)+'-shm').exists())

    def test_invalid_external_owner_rejects_before_database_open(self):
        self.write_witness(self.full,owner='different-owner')
        before=p.physical_bytes(self.database)
        with self.assertRaisesRegex(p.Rejected,'witness binding'):
            self.run_preflight()
        self.assertEqual(self.audit,[])
        self.assertEqual(before,p.physical_bytes(self.database))

    def test_malformed_witness_types_and_duplicate_fields_reject_before_sql(self):
        original = json.loads(self.witness.read_text())
        variants = [dict(original, schema_version=True), dict(original, digest=' '.join([original['digest'][:32],original['digest'][32:]])), dict(original, digest=original['digest'].upper()), dict(original, unknown='field')]
        raw = [json.dumps(value) for value in variants]
        raw.append(self.witness.read_text()[:-1]+',"generation":1}')
        for document in raw:
            self.witness.write_text(document)
            self.audit.clear()
            with self.subTest(document=document), self.assertRaises(p.Rejected):
                self.run_preflight()
            self.assertEqual(self.audit, [])

    def test_external_checkpoint_mismatch_does_not_promote_local_state(self):
        self.write_witness(hashlib.sha256(b'wrong-root').digest())
        before=p.physical_bytes(self.database)
        with self.assertRaisesRegex(p.Rejected,'checkpoint mismatch'):
            self.run_preflight()
        self.assertEqual(before,p.physical_bytes(self.database))

    def test_ledger_checksum_mismatch_rejected_without_running_migrator(self):
        self.writer.execute('UPDATE _sqlx_migrations SET checksum=? WHERE version=3',(bytes(48),))
        self.writer.commit()
        with self.assertRaisesRegex(p.Rejected,'prefix/checksum'):
            self.run_preflight()

    def test_missing_compiled_trigger_rejected(self):
        self.writer.execute('DROP TRIGGER authbus_frontier_time_insert')
        self.writer.commit()
        with self.assertRaisesRegex(p.Rejected,'schema differs'):
            self.run_preflight()

    def test_dirty_pending_journal_is_neither_folded_nor_pruned(self):
        self.add_time()
        before=self.writer.execute('SELECT * FROM authbus_frontier_change').fetchall()
        with self.assertRaisesRegex(p.Rejected,'dirty state'):
            self.run_preflight()
        self.assertEqual(before,self.writer.execute('SELECT * FROM authbus_frontier_change').fetchall())

    def test_full_snapshot_seed_with_rows_is_supported(self):
        self.add_time()
        root=p.full_frontier(self.writer)
        checkpoint(self.writer,root,generation=2)
        self.write_witness(root,generation=2)
        report=self.run_preflight()
        self.assertEqual(report['full_digest'],root.hex())
        self.assertGreater(report['applied_change_id'],0)

    def test_folded_pruned_chain_does_not_prove_current_full_snapshot(self):
        self.add_time()
        root=self.full
        changes=self.writer.execute('SELECT change_id,domain,operation,record_key,canonical_record FROM authbus_frontier_change ORDER BY change_id').fetchall()
        for sequence,*fields in changes:
            root=hashlib.sha256(b'hepta.authbus.authority-frontier.change.v2\0'+root+u64(sequence)+b''.join(p.push(field.encode()) for field in fields)).digest()
        checkpoint(self.writer,root,generation=2)
        self.write_witness(root,generation=2)
        self.assertEqual(self.writer.execute('SELECT COUNT(*) FROM authbus_frontier_change').fetchone()[0],0)
        self.assertNotEqual(root,p.full_frontier(self.writer))
        with self.assertRaisesRegex(p.Rejected,'full-state binding unproven'):
            self.run_preflight()

    def test_sequence_rewind_missing_duplicate_and_noninteger_are_rejected(self):
        self.add_time()
        root=p.full_frontier(self.writer)
        checkpoint(self.writer,root,generation=2)
        self.write_witness(root,generation=2)
        applied=self.writer.execute('SELECT applied_change_id FROM authbus_frontier_accumulator').fetchone()[0]
        self.assertGreater(applied,0)
        for values in [[],[applied-1],[applied,applied],[1.5],['invalid'],[-1],[2**63*1.0]]:
            self.writer.execute("DELETE FROM sqlite_sequence WHERE name='authbus_frontier_change'")
            for value in values:
                self.writer.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('authbus_frontier_change',?)",(value,))
            self.writer.commit()
            with self.subTest(values=values),self.assertRaisesRegex(p.Rejected,'frontier sequence'):
                self.run_preflight()

    def test_sql_authorizer_rejects_writes_and_mutating_pragmas(self):
        connection=p.read_only_connection(self.database,self.audit)
        try:
            for statement in ['CREATE TABLE forbidden(x)','UPDATE authbus_authority_checkpoint_dirty SET dirty=1','PRAGMA journal_mode=DELETE','PRAGMA user_version=7']:
                with self.subTest(statement=statement),self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(statement)
        finally:
            connection.close()
        self.assertEqual(sum(event[0]=='denied' for event in self.audit),4)

    def test_one_read_transaction_keeps_coherent_old_wal_snapshot(self):
        def concurrent_commit():
            self.add_time()
            new=p.full_frontier(self.writer)
            checkpoint(self.writer,new,generation=2)
        report=self.run_preflight(snapshot_hook=concurrent_commit)
        self.assertEqual(report['full_digest'],self.full.hex())
        self.assertNotEqual(p.full_frontier(self.writer),self.full)
        # A later open sees the new database and refuses the now-old witness.
        with self.assertRaisesRegex(p.Rejected,'checkpoint mismatch'):
            self.run_preflight()

    def test_source_row_tamper_is_not_blessed_by_restored_schema(self):
        self.add_time()
        root=p.full_frontier(self.writer)
        checkpoint(self.writer,root,generation=2)
        self.write_witness(root,generation=2)
        # Compound privileged-storage corruption fixture. It is not a claim that
        # an admitted caller can disable owner triggers or bypass the OS fence.
        triggers=self.writer.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name='authbus_trusted_time'").fetchall()
        for name,_ in triggers:self.writer.execute('DROP TRIGGER '+name)
        self.writer.execute('UPDATE authbus_trusted_time SET wall_time_ms=?',(u64(2100),))
        for _,sql in triggers:self.writer.execute(sql)
        self.writer.commit()
        self.assertEqual(self.writer.execute(p.SCHEMA_SQL).fetchall(),p.expected_schema())
        with self.assertRaisesRegex(p.Rejected,'full-state binding unproven'):
            self.run_preflight()

if __name__=='__main__':unittest.main(verbosity=2)
