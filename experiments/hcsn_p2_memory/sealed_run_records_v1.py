"""Fail-closed, create-only P2 experiment recorder for *future* runs.

This is a local-file evidence primitive, NOT trusted attestation, authentic
signing, production host recovery, or proof of scientific effectiveness.
Prevents accidental path reuse/partial visible JSON and catches postwrite
mutation via an independently retained receipt digest.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

SCHEMA = 'hcsn-p2-create-only-run-evidence-v1'
_RUN_ID = re.compile(r'[a-z0-9][a-z0-9_-]{7,95}\Z')
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
MAX_RECORD_BYTES = 2_000_000

class EvidenceUnresolved(RuntimeError):
    pass


def _valid_id(run_id: str) -> bool:
    return type(run_id) is str and _RUN_ID.fullmatch(run_id) is not None


def _read_verified(path: Path, run_id: str, expected_sha: str) -> dict:
    if not _valid_id(run_id) or type(expected_sha) is not str or _SHA256.fullmatch(expected_sha) is None:
        raise EvidenceUnresolved('invalid run-id or receipt digest')
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags)
        try:
            s = os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or not 0 < s.st_size < MAX_RECORD_BYTES:
                raise EvidenceUnresolved('invalid sealed record inode/size')
            with os.fdopen(os.dup(fd), 'rb') as f:
                raw = f.read(MAX_RECORD_BYTES + 1)
        finally:
            os.close(fd)
    except (OSError, ValueError) as e:
        raise EvidenceUnresolved('sealed evidence read failed') from e
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise EvidenceUnresolved('on-disk evidence differs from immutable receipt')
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as e:
        raise EvidenceUnresolved('invalid record bytes') from e
    if (type(doc) is not dict or doc.get('schema') != SCHEMA or
            doc.get('run_id') != run_id or doc.get('production_activation') is not False or
            doc.get('all_scientific_blockers_closed') is not False or
            doc.get('provenance_authenticated') is not False):
        raise EvidenceUnresolved('run identity, schema or fail-closed gate mismatch')
    return doc


def publish_create_only(directory: Path, run_id: str, result: dict) -> dict:
    """Publish a single fsynced JSON file under a unique logical run id.

    Hard-link installs it atomically only if final pathname does not exist.
    The digest receipt MUST be independently retained (e.g. in CI logs).
    """
    if not _valid_id(run_id) or type(result) is not dict:
        raise EvidenceUnresolved('unregistered run id or result shape')
    if (result.get('production_activation') is not False or
            result.get('all_scientific_blockers_closed') is not False):
        raise EvidenceUnresolved('no production/scientific admission permitted')
    if result.get('run_id', run_id) != run_id:
        raise EvidenceUnresolved('run-id in result mismatches target')
    doc = {'schema': SCHEMA, 'run_id': run_id, 'result': result,
           'production_activation': False, 'all_scientific_blockers_closed': False,
           'provenance_authenticated': False}
    try:
        raw = (json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as e:
        raise EvidenceUnresolved('unserializable/nonfinite result') from e
    if not 0 < len(raw) < MAX_RECORD_BYTES:
        raise EvidenceUnresolved('evidence output exceeds bound')
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise EvidenceUnresolved('output directory must exist and be non-symlink')
    final = directory / (run_id + '.json')
    fd = -1
    temp: str | None = None
    try:
        fd, temp = tempfile.mkstemp(prefix='.staging-', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'wb') as f:
            fd = -1
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        # Hard-link is atomic and fails on collision; unlike os.replace it
        # cannot silently clobber prior evidence or concurrent writers.
        os.link(temp, final, follow_symlinks=False)
        dirfd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except FileExistsError as e:
        raise EvidenceUnresolved('run ID already sealed: no overwrites or silent retries') from e
    except OSError as e:
        raise EvidenceUnresolved('create-only write or fsync failed: no receipt') from e
    finally:
        if fd >= 0:
            os.close(fd)
        if temp is not None:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
    sha = hashlib.sha256(raw).hexdigest()
    _read_verified(final, run_id, sha)
    return {'schema': SCHEMA, 'run_id': run_id, 'path': str(final),
            'sha256': sha, 'bytes': len(raw), 'create_only': True,
            'readback_verified': True, 'provenance_authenticated': False,
            'production_activation': False, 'all_scientific_blockers_closed': False}


def verify_receipt(directory: Path, receipt: dict) -> dict:
    if (type(receipt) is not dict or receipt.get('schema') != SCHEMA or
            receipt.get('create_only') is not True or receipt.get('readback_verified') is not True or
            receipt.get('provenance_authenticated') is not False or
            receipt.get('production_activation') is not False or
            receipt.get('all_scientific_blockers_closed') is not False):
        raise EvidenceUnresolved('noncanonical receipt or prohibited admission')
    run_id = receipt.get('run_id')
    if not _valid_id(run_id):
        raise EvidenceUnresolved('invalid receipt run id')
    return _read_verified(Path(directory) / (run_id + '.json'), run_id, receipt.get('sha256'))
