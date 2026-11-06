#!/usr/bin/env python3
"""Seal one actual job-owned fixed parent; only exact public fixtures reuse it.

This is a Host setup receipt, never native execution or performance authority.
The original from-zero/history modes still refuse every preexisting parent.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
import fcntl
from pathlib import Path
import re
import stat
import subprocess

import public_host_ci_observation as observation
import run_history_native as history
from replay_pinned_native import require
from verify_ci_source import verify as verify_source

ROOT = Path(__file__).resolve().parents[2]
RUN = Path('/run')
SCHEMA = 'trnm-ci-public-fixture-parent-lease-v1'
SYSTEMD_PROPERTIES = ('FragmentPath', 'DropInPaths', 'ControlGroup',
                      'CPUQuotaPerSecUSec', 'CPUQuotaPeriodUSec',
                      'MemoryMax', 'MemorySwapMax', 'TasksMax')


def paths() -> tuple[Path, Path]:
    job = history.job_identity()
    receipts = Path(os.environ.get('TRNM_CI_RECEIPT_DIR', ''))
    require(receipts.is_absolute() and receipts.resolve(strict=True) == receipts
            and receipts.is_dir() and not receipts.is_relative_to(ROOT),
            'FIXTURE_PARENT_CURRENT_RECEIPTS_REQUIRED')
    name = 'trnm-public-fixture-{GITHUB_RUN_ID}-{GITHUB_RUN_ATTEMPT}-{GITHUB_JOB}'.format(**job)
    return receipts / 'public-fixture-parent.json', RUN / name / 'parent.json'


@contextmanager
def parent_lock():
    """Reject concurrent owners; never wait and silently retry a native fixture."""
    context()  # Verify this actual hosted job/source before any privileged setup.
    path = RUN / 'trnmponpublic-ci-owner.lock'
    # The unique parent has one stable root-owned lock, independent of output
    # directories. O_EXCL never replaces/truncates another owner's lock inode.
    creator = ('import os, sys\ntry:\n'
               ' fd = os.open(sys.argv[1], os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o444)\n'
               'except FileExistsError:\n pass\nelse:\n os.close(fd)\n')
    created = subprocess.run(['sudo', '-n', '/usr/bin/python3', '-I', '-S', '-c', creator, str(path)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, timeout=30)
    require(created.returncode == 0, 'FIXTURE_PARENT_ROOT_LOCK_CREATE_FAILED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
                and info.st_uid == 0 and info.st_gid == 0 and info.st_size == 0
                and stat.S_IMODE(info.st_mode) == 0o444, 'FIXTURE_PARENT_LOCK_OWNER')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = path.lstat()
        require((current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid,
                 current.st_size) == (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                                      info.st_size), 'FIXTURE_PARENT_LOCK_CHANGED')
        yield
    finally:
        os.close(fd)


def workflow_source() -> dict:
    expected = os.environ.get('TRNM_EXPECTED_SOURCE_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', expected) is not None,
            'FIXTURE_PARENT_EXPECTED_SOURCE_REQUIRED')
    value, _ = history.load_object(Path(os.environ['TRNM_CI_RECEIPT_DIR']) / 'source.json')
    require(value.get('schema') == 'trnm-ci-source-v1'
            and value.get('tested_commit') == expected
            and value.get('tracked_worktree_verified') is True
            and value.get('tests_executed_by_identity_check') is False,
            'FIXTURE_PARENT_WORKFLOW_SOURCE_REQUIRED')
    actual = verify_source(value.get('kind'), value.get('candidate'), value.get('base'),
                           value.get('prospective_merge'), root=ROOT)
    require(actual == value, 'FIXTURE_PARENT_SOURCE_CHANGED')
    return actual


def context() -> dict:
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('CI') == 'true'
            and os.getuid() != 0 and Path.cwd().resolve() == ROOT,
            'FIXTURE_PARENT_HOSTED_CONTEXT_REQUIRED')
    mirror, _ = paths()
    return {'job': history.job_identity(), 'source': workflow_source(), 'receipts': str(mirror.parent),
            'uid': os.getuid(), 'gid': os.getgid(), 'cwd': str(ROOT)}


def root_file(path: Path, *, sealed: bool) -> dict:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_gid == 0
            and stat.S_IMODE(before.st_mode) == (0o444 if sealed else 0o644),
            'FIXTURE_PARENT_ROOT_FILE_REQUIRED')
    observed, _ = history.file_observation(path, history.JSON_LIMIT)
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_gid,
             before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_gid,
                after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'FIXTURE_PARENT_ROOT_FILE_CHANGED')
    return observed


def root_directory(path: Path) -> None:
    info = path.lstat()
    require(path.resolve(strict=True) == path and stat.S_ISDIR(info.st_mode)
            and info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o755,
            'FIXTURE_PARENT_ROOT_SEAL_DIRECTORY_REQUIRED')


def parent_identity(sample: dict, owner: dict) -> dict:
    require(not observation.validate(sample, inside=False, uid=owner['uid'], gid=owner['gid'],
                                     cwd=owner['cwd']), 'FIXTURE_PARENT_KERNEL_REQUIRED')
    return {**{name: sample[name] for name in (
        'parent', 'boot_id', 'limits', 'installed_unit_sha256')},
        'unit_file': root_file(observation.RUNTIME_UNIT, sealed=False)}


def systemd_properties(path: Path) -> dict:
    _, raw = history.file_observation(path, history.JSON_LIMIT, retain=True)
    fields = {}
    for line in raw.decode('utf-8').splitlines():
        key, separator, value = line.partition('=')
        require(separator and key in SYSTEMD_PROPERTIES and key not in fields,
                'FIXTURE_PARENT_SYSTEMD_PROPERTIES')
        fields[key] = value
    require(set(fields) == set(SYSTEMD_PROPERTIES)
            and fields['FragmentPath'] == str(observation.RUNTIME_UNIT)
            and fields['DropInPaths'] == ''
            and fields['ControlGroup'] == '/trnmponpublic.slice',
            'FIXTURE_PARENT_SYSTEMD_CONFIGURATION')
    return fields


def require_no_seal() -> None:
    mirror, seal = paths()
    require(not mirror.exists() and not mirror.is_symlink()
            and not seal.parent.exists() and not seal.parent.is_symlink(),
            'FIXTURE_PARENT_SEAL_ALREADY_EXISTS')


def seal_after_provision(sample: dict, controller: Path, command: list[str], run_setup) -> dict:
    """Called only after the original absent-parent checks and actual provision."""
    require_no_seal()
    owner = context()
    before, _ = history.load_object(controller / 'before-provision.json')
    require(before.get('parent') is None and before.get('installed_unit_sha256') is None,
            'FIXTURE_PARENT_ORIGINAL_ABSENCE_REQUIRED')
    after, after_file = history.load_object(controller / 'after-provision.json')
    require(after == sample, 'FIXTURE_PARENT_ACTUAL_PROVISION_REQUIRED')
    original, original_file = history.load_object(controller / 'unprovisioned-parent.json')
    require(original.get('ActiveState') == 'inactive' and original.get('SubState') == 'dead'
            and original.get('FragmentPath') == '' and original.get('DropInPaths') == ''
            and original.get('ControlGroup') == '' and original.get('Transient') == 'no',
            'FIXTURE_PARENT_ORIGINAL_CONFIGURATION_REQUIRED')
    properties = systemd_properties(controller / 'actual-systemd-parent.log')
    value = {'schema': SCHEMA, 'context': owner, 'parent_identity': parent_identity(sample, owner),
             'systemd_properties': properties, 'creator_service': sample['service'],
             'creator_command': command, 'creator_controller': str(controller),
             'original_absence': original_file, 'actual_provision': after_file,
             'host_readiness_only': True, 'native_tests_executed_by_lease': False,
             'consensus_or_model_authority': False}
    mirror, seal = paths()
    observation.write_new(mirror, value)
    # mkdir fails on any existing directory. No root-owned lease is overwritten,
    # adopted or reconstructed from a caller's claim that a parent already exists.
    run_setup(['sudo', '-n', 'mkdir', '--mode=0755', '--', str(seal.parent)], 'seal-parent-directory')
    run_setup(['sudo', '-n', 'install', '-o', 'root', '-g', 'root', '-m', '0444',
               str(mirror), str(seal)], 'seal-parent-receipt')
    return validate_for_reuse(sample, controller / 'actual-systemd-parent.log')


def validate_for_reuse(sample: dict, properties_path: Path) -> dict:
    """Reobserve the parent; a prior service identity never names the next one."""
    owner = context()
    mirror, seal = paths()
    root_directory(seal.parent)
    seal_file = root_file(seal, sealed=True)
    value, mirror_file = history.load_object(mirror)
    sealed, sealed_file = history.load_object(seal)
    require(sealed_file == seal_file and value == sealed
            and mirror_file['sha256'] == seal_file['sha256'], 'FIXTURE_PARENT_SEAL_CHANGED')
    require(value.get('schema') == SCHEMA and value.get('context') == owner
            and value.get('host_readiness_only') is True
            and value.get('native_tests_executed_by_lease') is False
            and value.get('consensus_or_model_authority') is False,
            'FIXTURE_PARENT_LEASE_CONTEXT_CHANGED')
    require(value.get('parent_identity') == parent_identity(sample, owner),
            'FIXTURE_PARENT_IDENTITY_CHANGED')
    require(value.get('systemd_properties') == systemd_properties(properties_path),
            'FIXTURE_PARENT_SYSTEMD_CHANGED')
    for field in ('original_absence', 'actual_provision'):
        require(type(value.get(field)) is dict, 'FIXTURE_PARENT_ORIGIN_REQUIRED')
        _, actual = history.load_object(Path(value[field]['path']))
        require(actual == value[field], 'FIXTURE_PARENT_ORIGIN_CHANGED')
    counters = sample.get('counters') or {}
    require(counters.get('pids.current') == '0'
            and re.search(r'^populated 0$', counters.get('cgroup.events') or '', re.MULTILINE),
            'FIXTURE_PARENT_PRIOR_CHILDREN_NOT_EMPTY')
    return {'schema': 'trnm-ci-public-fixture-parent-binding-v1',
            'seal_sha256': seal_file['sha256'], 'seal_file': seal_file,
            'parent_identity': value['parent_identity'],
            'creator_service': value['creator_service'], 'current_service': sample['service'],
            'host_readiness_only': True, 'consensus_or_model_authority': False}
