#!/usr/bin/env python3
"""Source-bound SQLite reproduction of a compound time-floor restore assumption.

Executes actual Evidence migrations and reproduces the documented frontier
encoding. It does not run Rust, Agentd generation gates, Core deduplication or a
provider. This tests a storage/time assumption outside the replay witness scope, not a product exploit.
"""
import hashlib
from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parent / 'evidence_migrations'

def u64(value):
    return value.to_bytes(8, 'big')

def text_bytes(value):
    raw = value.encode()
    return u64(len(raw)) + raw

def frontier(connection):
    replay = connection.execute('SELECT issuer_id,key_epoch,subject_id,scope_digest,sequence,envelope_digest FROM authbus_replay_sequences ORDER BY issuer_id,key_epoch,subject_id,scope_digest').fetchall()
    retired = connection.execute('SELECT issuer_id,key_epoch,retirement_digest FROM authbus_retired_epochs ORDER BY issuer_id,key_epoch').fetchall()
    raw = b'hepta.authbus.replay-frontier.v1\0' + u64(len(replay))
    for issuer, epoch, subject, scope, sequence, envelope in replay:
        raw += text_bytes(issuer) + epoch + text_bytes(subject) + scope + sequence + envelope
    raw += u64(len(retired))
    for issuer, epoch, digest in retired:
        raw += text_bytes(issuer) + epoch + digest
    return hashlib.sha256(raw).digest()

def observe(connection, host_observation):
    before, revision = connection.execute('SELECT observed_at_ms,revision FROM authbus_time_floor WHERE singleton=1').fetchone()
    if host_observation > before:
        connection.execute('UPDATE authbus_time_floor SET observed_at_ms=?,revision=? WHERE singleton=1 AND observed_at_ms=? AND revision=?',
                           (host_observation, revision + 1, before, revision))
    return max(before, host_observation)

def fixture():
    connection = sqlite3.connect(':memory:', isolation_level=None)
    for migration in sorted(ROOT.glob('*.sql')):
        connection.executescript(migration.read_text())
    digest = b'x' * 32
    connection.execute('INSERT INTO authbus_replay_sequences VALUES(?,?,?,?,?,?)',
                       ('issuer:test', u64(1), 'subject:test', digest, u64(1), digest))
    # The row's bytes satisfy actual schema constraints. Authenticity is not
    # under test: changing neither signature nor replay identity is the point.
    connection.execute('''INSERT INTO authbus_outbox
        (delivery_id,issuer_id,key_epoch,message_id,subject_id,scope_digest,payload_digest,
         sequence,expires_at_ms,signature,payload,state,fence,attempts,available_at_ms,created_at_ms,updated_at_ms)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',0,0,1000,1000,1000)''',
        (digest,'issuer:test',u64(1),'message:test','subject:test',digest,digest,u64(1),u64(5000),b's'*64,b'unchanged payload'))
    observe(connection, 1000)
    witness = (u64(2), frontier(connection))
    connection.execute('INSERT INTO authbus_restore_checkpoint VALUES(1,?,?,1000)', witness)
    return connection, witness

class EvidenceTimeRestoreTests(unittest.TestCase):
    def test_time_only_expiry_is_not_bound_by_replay_witness(self):
        connection, witness = fixture()
        snapshot = connection.serialize()
        self.assertEqual(observe(connection, 6000), 6000)
        connection.execute("UPDATE authbus_outbox SET state='expired',fence=fence+1,updated_at_ms=6000,terminal_at_ms=6000")
        self.assertEqual(frontier(connection), witness[1])
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM authbus_restore_checkpoint_pending').fetchone(), (0,))
        self.assertEqual(observe(connection, 2000), 6000)  # ordinary clock rollback is clamped
        restored = sqlite3.connect(':memory:', isolation_level=None)
        restored.deserialize(snapshot)
        self.assertEqual(restored.execute('SELECT generation,checkpoint_digest FROM authbus_restore_checkpoint').fetchone(), witness)
        self.assertEqual(frontier(restored), witness[1])
        self.assertEqual(restored.execute('SELECT COUNT(*) FROM authbus_restore_checkpoint_pending').fetchone(), (0,))
        effective_now = observe(restored, 2000)
        self.assertEqual(effective_now, 2000)
        state, expiry = restored.execute('SELECT state,expires_at_ms FROM authbus_outbox').fetchone()
        self.assertEqual(state, 'queued')
        self.assertLess(effective_now, int.from_bytes(expiry, 'big'))
        self.assertEqual(restored.execute('PRAGMA quick_check').fetchone(), ('ok',))
        connection.close(); restored.close()

    def test_restore_with_independently_current_time_does_not_revive_expiry(self):
        connection, witness = fixture()
        snapshot = connection.serialize()
        restored = sqlite3.connect(':memory:', isolation_level=None)
        restored.deserialize(snapshot)
        effective_now = observe(restored, 6000)
        expiry = int.from_bytes(restored.execute('SELECT expires_at_ms FROM authbus_outbox').fetchone()[0], 'big')
        self.assertGreaterEqual(effective_now, expiry)
        self.assertEqual(frontier(restored), witness[1])
        connection.close(); restored.close()

if __name__ == '__main__':
    unittest.main(verbosity=2)
