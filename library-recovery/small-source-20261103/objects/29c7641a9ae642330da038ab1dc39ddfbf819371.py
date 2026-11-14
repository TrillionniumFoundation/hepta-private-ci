"""Read-only qualification probe for one pinned old AuthBus format.

Not production admission, a migration engine, or an authenticated-storage service.
An externally retained checkpoint is a fixture trust input; its independent
retention and sole-owner fence remain deployment/production prerequisites.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import stat

ROOT = Path('/workspace/shared/operations-authbus-integration/codex-rs/hepta-authbus')
MIGRATIONS = sorted((ROOT / 'migrations').glob('*.sql'))
EXPECTED_VERSIONS = list(range(1, 8))
SCHEMA_SQL = "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' AND sql IS NOT NULL ORDER BY type,name"
LEDGER_SQL = '''CREATE TABLE IF NOT EXISTS _sqlx_migrations (
    version BIGINT PRIMARY KEY,
    description TEXT NOT NULL,
    installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN NOT NULL,
    checksum BLOB NOT NULL,
    execution_time BIGINT NOT NULL
)'''

class Rejected(Exception):
    pass


def migration_identity():
    versions = [int(p.name.split('_', 1)[0]) for p in MIGRATIONS]
    if versions != EXPECTED_VERSIONS:
        raise Rejected('unsupported compiled migration prefix')
    return [(version, hashlib.sha384(path.read_bytes()).digest())
            for version, path in zip(versions, MIGRATIONS)]


def initialize_fixture(connection):
    connection.execute(LEDGER_SQL)
    for path, (version, checksum) in zip(MIGRATIONS, migration_identity()):
        connection.executescript(path.read_text())
        connection.execute('INSERT INTO _sqlx_migrations(version,description,success,checksum,execution_time) VALUES(?,?,1,?,0)',
                           (version, path.stem.split('_', 1)[1].replace('_', ' '), checksum))
    connection.commit()


def expected_schema():
    oracle = sqlite3.connect(':memory:')
    try:
        initialize_fixture(oracle)
        return oracle.execute(SCHEMA_SQL).fetchall()
    finally:
        oracle.close()


def frontier_queries():
    # Bounded extraction of the eight literal queries from this exact source.
    # This is not a Rust parser; refuse a different source shape.
    source = (ROOT / 'src/recovery.rs').read_text()
    body = source.split('async fn full_authority_frontier_digest_tx(', 1)[1].split('const RESERVATION_FRONTIER_SQL:', 1)[0]
    constants = dict(re.findall(r'const (\w+): &str\s*=\s*"([^"]*)";', source, re.S))
    calls = re.findall(r'append_rows\(\s*tx,\s*&mut bytes,\s*"([^"]+)",\s*("[^"]*"|\w+)\s*,?\s*\)', body, re.S)
    expected = ['trusted_time','policy','policy_history','policy_archive','quota','reservation','reservation_archive','issuer']
    if [tag for tag, _ in calls] != expected:
        raise Rejected('unsupported full frontier source shape')
    return [(tag, expression[1:-1] if expression.startswith('"') else constants[expression])
            for tag, expression in calls]


def push(value):
    return len(value).to_bytes(8, 'big') + value


def full_frontier(connection):
    data = bytearray(b'hepta.authbus.authority-frontier.v1\0')
    for tag, query in frontier_queries():
        rows = connection.execute(query).fetchall()
        data += push(tag.encode()) + len(rows).to_bytes(8, 'big')
        for (value,) in rows:
            if not isinstance(value, str):
                raise Rejected('invalid canonical row')
            data += push(value.encode())
    return hashlib.sha256(data).digest()


def read_fixture_witness(path, database, owner):
    # Match current witness shape and private-file policy conservatively. This
    # cannot prove independent retention and does not replace the native owner.
    if not owner or len(owner.encode()) > 256:
        raise Rejected('invalid witness owner')
    path = Path(path)
    if path.resolve() != path or path.parent == Path(database).parent:
        raise Rejected('unsafe witness path')
    parent = path.parent.stat()
    if stat.S_IMODE(parent.st_mode) != 0o700:
        raise Rejected('unsafe witness parent')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > 4096:
            raise Rejected('unsafe witness file')
        raw = os.read(descriptor, 4097)
        after = os.fstat(descriptor)
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise Rejected('witness changed while reading')
        final_path = path.lstat()
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (final_path.st_dev,final_path.st_ino,final_path.st_size,final_path.st_mtime_ns,final_path.st_ctime_ns):
            raise Rejected('witness pathname changed while reading')
        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise Rejected('duplicate witness field')
                result[key] = value
            return result
        document = json.loads(raw, object_pairs_hook=unique_fields)
    finally:
        os.close(descriptor)
    try:
        if not isinstance(document, dict) or set(document) != {'schema_version', 'owner_id', 'generation', 'digest'}:
            raise Rejected('invalid witness fields')
        encoded = document['digest']
        if not isinstance(encoded, str) or re.fullmatch(r'[0-9a-f]{64}', encoded) is None:
            raise Rejected('invalid witness digest')
        digest = bytes.fromhex(encoded)
        generation = document['generation']
        if type(document['schema_version']) is not int or document['schema_version'] != 1 or document['owner_id'] != owner or type(generation) is not int or not 0 < generation < 2**64 or len(digest) != 32 or digest == bytes(32):
            raise Rejected('invalid witness binding')
    except (KeyError, ValueError, TypeError) as error:
        raise Rejected('invalid witness encoding') from error
    return generation, digest


def physical_bytes(database):
    return {suffix: hashlib.sha256(Path(str(database)+suffix).read_bytes()).hexdigest()
            for suffix in ('', '-wal') if Path(str(database)+suffix).exists()}


def read_only_connection(database, audit):
    connection = sqlite3.connect(Path(database).as_uri() + '?mode=ro', uri=True, isolation_level=None)
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}
    def authorize(action, first, second, database_name, trigger):
        if action in allowed:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA and first in {'quick_check', 'foreign_key_check'} and second is None:
            return sqlite3.SQLITE_OK
        audit.append(('denied', action, first, second))
        return sqlite3.SQLITE_DENY
    connection.set_authorizer(authorize)
    connection.set_trace_callback(lambda statement: audit.append(('sql', statement)))
    return connection


def preflight(database, witness, owner, audit, snapshot_hook=None):
    # No database connection is opened before independent witness validation.
    external = read_fixture_witness(witness, database, owner)
    audit.append(('witness_validated', external[0]))
    # SQLite mode=ro can create WAL/SHM when absent. This bounded probe supports
    # only retained WAL bundles; do not discover unsupported state by mutating it.
    if not all(Path(str(database)+suffix).is_file() for suffix in ('-wal', '-shm')):
        raise Rejected('retained WAL/SHM required; no-sidecar opening is unsupported')
    before = physical_bytes(database)
    connection = read_only_connection(database, audit)
    try:
        connection.execute('BEGIN')
        schema = connection.execute(SCHEMA_SQL).fetchall()  # pins WAL snapshot
        if snapshot_hook:
            snapshot_hook()
        if schema != expected_schema():
            raise Rejected('live schema differs from pinned old schema')
        ledger = connection.execute('SELECT version,checksum,success FROM _sqlx_migrations ORDER BY version').fetchall()
        if ledger != [(version, digest, 1) for version, digest in migration_identity()]:
            raise Rejected('migration prefix/checksum mismatch')
        if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)] or connection.execute('PRAGMA foreign_key_check').fetchall():
            raise Rejected('SQLite integrity failure')
        local = connection.execute('SELECT generation,checkpoint_digest FROM authbus_authority_checkpoint WHERE singleton=1').fetchone()
        if local is None or len(local[0]) != 8 or (int.from_bytes(local[0], 'big'), local[1]) != external:
            raise Rejected('independent checkpoint mismatch')
        if connection.execute('SELECT dirty FROM authbus_authority_checkpoint_dirty WHERE singleton=1').fetchone() != (0,):
            raise Rejected('dirty state requires old-format recovery')
        accumulator = connection.execute('SELECT schema_version,root_digest,applied_change_id FROM authbus_frontier_accumulator WHERE singleton=1').fetchone()
        if accumulator is None or accumulator[0] != 1 or type(accumulator[2]) is not int or not 0 <= accumulator[2] < 2**63:
            raise Rejected('invalid accumulator')
        if connection.execute('SELECT COUNT(*) FROM authbus_frontier_change').fetchone()[0] != 0:
            raise Rejected('journal requires old-format recovery')
        sequences = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='authbus_frontier_change'").fetchall()
        applied = accumulator[2]
        if not sequences:
            if applied != 0:
                raise Rejected('missing frontier sequence')
        elif len(sequences) != 1 or type(sequences[0][0]) is not int or not applied <= sequences[0][0] < 2**63:
            raise Rejected('invalid frontier sequence')
        root = accumulator[1]
        if root is not None and root != external[1]:
            raise Rejected('accumulator/checkpoint mismatch')
        if root is None and accumulator[2] != 0:
            raise Rejected('invalid unseeded accumulator')
        full = full_frontier(connection)
        if full != external[1]:
            raise Rejected('full-state binding unproven: historical folded chain is not a current snapshot commitment')
        return {'format': 'supported full-snapshot binding', 'generation': external[0], 'full_digest': full.hex(), 'applied_change_id': accumulator[2]}
    finally:
        connection.rollback()
        connection.close()
        # Snapshot-concurrency tests intentionally include another writer.
        if snapshot_hook is None and physical_bytes(database) != before:
            raise AssertionError('read-only preflight changed main DB or WAL bytes')
