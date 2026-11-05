#!/usr/bin/env python3
"""Read-only CI observations of the original public Host parent, never authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path


PARENT = Path('/sys/fs/cgroup/trnmponpublic.slice')
UNIT = 'trnmponpublic.slice'
RUNTIME_UNIT = Path('/run/systemd/system') / UNIT
UNIT_SHA256 = '74eb36a63559bf8603c15ddd3753a1db143684a2cefd84cce5aff10a76bbd622'
LIMITS = {
    'cpu.max': '25000 100000',
    'cpu.max.burst': '0',
    'memory.max': '2147483648',
    'memory.swap.max': '0',
    'pids.max': '256',
}


def write_new(path: Path, value: dict) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def capture(phase: str, service: str) -> dict:
    """Failures remain null/error observations; never substitute a valid fixture."""
    errors = {}

    def read(path: Path, limit=2048):
        try:
            with path.open('rb') as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('READ_LIMIT')
            return raw.decode('utf-8').strip()
        except (OSError, UnicodeError, ValueError) as error:
            errors[str(path)] = str(error)
            return None

    parent = None
    try:
        metadata = PARENT.lstat()
        parent = {
            'canonical_path': str(PARENT.resolve(strict=True)),
            'device': metadata.st_dev, 'inode': metadata.st_ino,
            'uid': metadata.st_uid, 'gid': metadata.st_gid,
            'mode': stat.S_IMODE(metadata.st_mode),
            'directory': stat.S_ISDIR(metadata.st_mode),
            'symlink': stat.S_ISLNK(metadata.st_mode),
        }
    except OSError as error:
        errors[str(PARENT)] = str(error)
    unit_sha = None
    try:
        unit_sha = hashlib.sha256(RUNTIME_UNIT.read_bytes()).hexdigest()
    except OSError as error:
        errors[str(RUNTIME_UNIT)] = str(error)
    status = read(Path('/proc/thread-self/status'), 16384)
    privileges = {}
    if status is not None:
        for line in status.splitlines():
            key, separator, value = line.partition(':')
            if separator and key in ('NoNewPrivs', 'CapBnd'):
                privileges[key] = value.strip()
    return {
        'schema': 'trnm-ci-original-public-host-observation-v1',
        'phase': phase, 'observed_utc': datetime.now(timezone.utc).isoformat(),
        'service': service, 'pid': os.getpid(), 'uid': os.getuid(), 'gid': os.getgid(),
        'cwd': str(Path.cwd()), 'parent_path': str(PARENT), 'parent': parent,
        'boot_id': read(Path('/proc/sys/kernel/random/boot_id'), 128),
        'thread_cgroup': read(Path('/proc/thread-self/cgroup')),
        'thread_privileges': privileges,
        'cgroup_controllers': read(Path('/sys/fs/cgroup/cgroup.controllers')),
        'limits': {name: read(PARENT / name, 128) for name in LIMITS},
        'counters': {name: read(PARENT / name) for name in (
            'cpu.stat', 'memory.current', 'memory.events', 'pids.current', 'cgroup.events')},
        'installed_unit_sha256': unit_sha, 'read_errors': errors,
        'host_readiness_only': True, 'consensus_or_model_authority': False,
    }


def validate(sample: dict, *, inside: bool, uid: int, gid: int, cwd: str,
             reference: dict | None = None) -> list[str]:
    errors = []
    parent = sample.get('parent') or {}
    if (sample.get('parent_path') != str(PARENT)
            or parent.get('canonical_path') != str(PARENT)
            or parent.get('directory') is not True or parent.get('symlink') is not False
            or parent.get('uid') != 0 or type(parent.get('mode')) is not int
            or parent.get('mode', 0) & 0o022):
        errors.append('FIXED_PARENT_IDENTITY')
    if sample.get('limits') != LIMITS:
        errors.append('ORIGINAL_FINITE_LIMITS')
    if sample.get('installed_unit_sha256') != UNIT_SHA256:
        errors.append('REVIEWED_UNIT_BYTES')
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',
                        sample.get('boot_id') or ''):
        errors.append('BOOT_ID_REQUIRED')
    if sample.get('read_errors'):
        errors.append('KERNEL_OBSERVATION_UNAVAILABLE')
    if (sample.get('uid'), sample.get('gid'), sample.get('cwd')) != (uid, gid, cwd):
        errors.append('ORIGINAL_CALLER_CONTEXT')
    if inside:
        if sample.get('thread_privileges') != {'NoNewPrivs': '1', 'CapBnd': '0000000000000000'}:
            errors.append('UNPRIVILEGED_SERVICE_REQUIRED')
        expected = '0::/trnmponpublic.slice/' + sample['service']
        actual = sample.get('thread_cgroup') or ''
        if actual != expected and not actual.startswith(expected + '/'):
            errors.append('ACTUAL_SERVICE_MEMBERSHIP')
        if '\n' in actual or any(piece in ('.', '..', '')
                                 for piece in actual.removeprefix('0::/').split('/')):
            errors.append('ACTUAL_SERVICE_MEMBERSHIP')
    if reference is not None:
        if sample.get('service') != reference.get('service'):
            errors.append('OWNED_SERVICE_CHANGED')
        for key in ('parent', 'boot_id', 'limits', 'installed_unit_sha256'):
            if sample.get(key) != reference.get(key):
                errors.append('HOST_CONTEXT_CHANGED:' + key)
    return sorted(set(errors))
