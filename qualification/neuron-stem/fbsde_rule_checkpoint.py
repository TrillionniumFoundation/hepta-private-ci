"""Bounded local durability port for RuleSlot; NOT native artifact authority.

Trusted private directory, one OS-fenced writer, SQLite atomic transactions.
A latest independent owner anchor is REQUIRED on reopen: an internally valid
old database is not evidence of currentness. No receipt grants production use.
"""
import fcntl
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import time
from threading import RLock
from four_gate_common import digest, require, strict_loads
import json

SCHEMA = 'hepta.rule-checkpoint.v1'
MAX_ROWS, MAX_ROW_BYTES, MAX_DB_BYTES = 512, 65536, 64 * 1024 * 1024


def encode(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    require(len(raw) <= MAX_ROW_BYTES, 'bounded checkpoint row')
    return raw


class CheckpointError(RuntimeError):
    """No action may be published after an uncertain persistence outcome."""


class RuleCheckpoint:
    """Own one private database; context manager deterministically releases it.

    fault(stage, event) is dependency injection for crash tests, not an env knob.
    Native persistence must replace this research port, not trust its hashes.
    """
    def __init__(self, directory, *, create=False, anchor=None, fault=None):
        self._lock = RLock(); self._db = None; self._fd = None
        self._closed = False; self._poisoned = False; self._fault = fault
        self.costs = []; self._pid = os.getpid()
        self.directory = Path(directory)
        require(self.directory.is_dir() and not self.directory.is_symlink(), 'trusted existing directory')
        path = self.directory / 'rule.sqlite3'; lock = self.directory / 'writer.lock'
        try:
            self._fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(self._fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'regular exclusive owner fence')
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if create:
                require(anchor is None, 'creation cannot import an anchor')
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            else:
                require(type(anchor) is dict and set(anchor) == {'database_id','sequence','digest'}
                    and type(anchor['database_id']) is str and len(anchor['database_id']) == 32
                    and type(anchor['sequence']) is int and 0 <= anchor['sequence'] < MAX_ROWS
                    and type(anchor['digest']) is str and len(anchor['digest']) == 64,
                    'independent current checkpoint anchor required')
                info = path.lstat()
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_DB_BYTES,
                        'regular bounded existing checkpoint')
            # mode=rw never recreates a missing journal on restart.
            self._db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True,
                isolation_level=None, check_same_thread=False, timeout=0)
            require(self._db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete', 'rollback journal')
            self._db.execute('PRAGMA synchronous=FULL')
            self._db.execute('PRAGMA trusted_schema=OFF')
            page_size = self._db.execute('PRAGMA page_size').fetchone()[0]
            require(self._db.execute(f'PRAGMA max_page_count={MAX_DB_BYTES//page_size}').fetchone()[0]
                * page_size <= MAX_DB_BYTES, 'bounded checkpoint database pages')
            if create:
                self._db.execute('BEGIN IMMEDIATE')
                self._db.execute('CREATE TABLE meta (schema TEXT NOT NULL, database_id TEXT NOT NULL)')
                self._db.execute('INSERT INTO meta VALUES (?,?)', (SCHEMA, secrets.token_hex(16)))
                self._db.execute('CREATE TABLE checkpoint (seq INTEGER PRIMARY KEY, previous TEXT, event BLOB NOT NULL, snapshot BLOB NOT NULL, digest TEXT NOT NULL)')
                self._db.execute('COMMIT')
                directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(directory_fd)
                finally: os.close(directory_fd)
            require(self._db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'checkpoint database corrupt')
            meta = self._db.execute('SELECT schema,database_id FROM meta LIMIT 2').fetchall()
            require(len(meta) == 1 and meta[0][0] == SCHEMA, 'checkpoint schema')
            self.database_id = meta[0][1]
            self._rows = self._read_verified()
            if not create:
                require(anchor['database_id'] == self.database_id and len(self._rows) > anchor['sequence']
                    and self._rows[anchor['sequence']]['digest'] == anchor['digest'], 'checkpoint rollback or foreign anchor')
        except BaseException:
            self.close()
            raise

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def close(self):
        with self._lock:
            self._closed = True
            try:
                if self._db is not None: self._db.close()
            finally:
                self._db = None
                if self._fd is not None: os.close(self._fd)
                self._fd = None

    def _read_verified(self):
        result = []; previous = None
        sizes = self._db.execute('SELECT seq,length(event),length(snapshot) FROM checkpoint ORDER BY seq LIMIT ?', (MAX_ROWS+1,)).fetchall()
        require(len(sizes) <= MAX_ROWS and all(i == s and 0 < a <= MAX_ROW_BYTES and 0 < b <= MAX_ROW_BYTES
            for i,(s,a,b) in enumerate(sizes)), 'bounded contiguous checkpoint history')
        for seq, prev, raw, state, identity in self._db.execute('SELECT * FROM checkpoint ORDER BY seq'):
            event, snapshot = strict_loads(raw), strict_loads(state)
            require(encode(event) == raw and encode(snapshot) == state and prev == previous and
                identity == digest([SCHEMA,self.database_id,seq,prev,event,snapshot]), 'checkpoint chain or canonical bytes')
            require(event['sequence'] == seq and event['previous'] == (digest(result[-1]['event']) if result else None),
                    'original lifecycle event chain')
            result.append(dict(event=event,snapshot=snapshot,digest=identity))
            previous = identity
        return result

    def rows(self):
        with self._lock:
            require(os.getpid() == self._pid and not self._closed and not self._poisoned, 'checkpoint is closed, foreign-process or uncertain')
            return json.loads(json.dumps(self._rows))

    def anchor(self):
        with self._lock:
            require(os.getpid() == self._pid and not self._closed and not self._poisoned and self._rows, 'no acknowledged checkpoint')
            return dict(database_id=self.database_id, sequence=len(self._rows)-1, digest=self._rows[-1]['digest'])

    def append(self, event, snapshot):
        with self._lock:
            require(os.getpid() == self._pid and not self._closed and not self._poisoned, 'checkpoint is closed, foreign-process or uncertain')
            cpu,wall = time.process_time_ns(),time.perf_counter_ns()
            raw, state = encode(event), encode(snapshot)
            seq = len(self._rows); previous = self._rows[-1]['digest'] if self._rows else None
            require(seq < MAX_ROWS and event['sequence'] == seq, 'checkpoint record capacity or sequence')
            identity = digest([SCHEMA,self.database_id,seq,previous,event,snapshot])
            try:
                self._db.execute('BEGIN IMMEDIATE')
                observed = self._db.execute('SELECT seq,digest FROM checkpoint ORDER BY seq DESC LIMIT 1').fetchone()
                require(observed == ((seq-1,previous) if seq else None), 'checkpoint predecessor changed')
                self._db.execute('INSERT INTO checkpoint VALUES (?,?,?,?,?)', (seq,previous,raw,state,identity))
                if self._fault: self._fault('before_commit', event['event'])
                self._db.execute('COMMIT')
                if self._fault: self._fault('after_commit', event['event'])
                self._rows.append(dict(event=strict_loads(raw),snapshot=strict_loads(state),digest=identity))
                self.costs.append(dict(event=event['event'],cpu_ns=time.process_time_ns()-cpu,
                    wall_ns=time.perf_counter_ns()-wall,bytes=len(raw)+len(state)))
            except BaseException as error:
                self._poisoned = True
                try:
                    if self._db.in_transaction: self._db.execute('ROLLBACK')
                except sqlite3.Error: pass
                raise CheckpointError('checkpoint outcome uncertain; close and reconcile') from error
