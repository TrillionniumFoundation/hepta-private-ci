#!/usr/bin/env python3
"""Restore pinned runtime materials in a new external depot; never run maintenance.

Every download, environment installation and original frozen/offline check is
preparation evidence only. A failed/unknown operation is never a qualification.
The initial offline-sync/find-links idea remains an unexecuted proposal: this
control creates an external venv, installs the sole exact locked requirement
from its verified wheelhouse, then requires the original frozen offline check.
"""
from __future__ import annotations

import base64
import contextlib
import datetime
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import traceback
import types
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO = Path('/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1')
CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/runtime-materials-restore-86dd-v1')
OUT = CONTROL / 'run-v2'
CONFIG = CONTROL / 'APPROVED_CONFIG_V2.json'
DEPOT = Path('/data/hepta-utility-36fa-runtime-materials-86dd-v1')
TARGET = Path('/data/hepta-utility-36fa-final-native-target-v1')
HEAD = '86dd56a930277e0d1aef3e475e35c2b5d60b43b7'
TREE = '383ab85c39ef9d848252ef5c25922d13d9fae6c6'
PARENTS = ['c0f78493f815780f68b9bf5e390a21314d79311f',
           'a96d1b821d10ed3d9e99dd06c5141f9f242ae318']
SOURCE_PIN = {'bytes': 5611182,
              'sha256': 'bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711',
              'git_blob': 'e7efbbc915cf80db9f873a2b5f9bf162daf4308c'}
INVENTORY_PIN = {'bytes': 22946,
                 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2',
                 'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}
EXECUTE_PIN = {'bytes': 12863,
               'sha256': '9b2bfaa563fff018df4e4f10944f6fbc63d307fa4c4a7e167c392288edb5a5c1',
               'git_blob': 'c9434b3a4afb31f80e323d543936386a2fa738de'}
INPUTS = {
    'DEPENDENCY_PLAN.original.json': {
        'bytes': 17795,
        'sha256': '22b85535cbb1d079c8dd698d8827122b439c964672fce7d182726783a0fb2ec6',
        'git_blob': '8936bfb0e0dbab9e471a158f1161567273798360'},
    'MATERIALIZATION_RESULT.original.json': {
        'bytes': 69974,
        'sha256': 'b2ef9a18547838b5978d8f4b7b8cc11b28d089cc386c207894017c2cfe5e1c58',
        'git_blob': '456f749e7558e18df99172d9c9273cda890b8feb'},
    'MATERIALIZATION_SUPERVISOR.original.json': {
        'bytes': 913,
        'sha256': '83a16687e3b108f49c598cb6be9aead68a2a95991c92df49a836889422bab2b2',
        'git_blob': '3e60d21bec849a19efb5d818b43152bfc72486fe'},
    'MAINTENANCE_STARTED.original.json': {
        'bytes': 1154,
        'sha256': 'f9372b818186526929ae25be698d108a4fee17d6612a18f36b8e950172c02ce1',
        'git_blob': '69a3d38ff1cf800813f1fbf1f30bca224157f223'},
    'inventory-driver.original.py': INVENTORY_PIN,
}
OPERATION_SECONDS = 600
FINAL_SECONDS = 180
LOG_LIMIT = 8 * 1024 * 1024
GIT = '/usr/bin/git'
PYTHON = '/usr/bin/python3'
BOOTSTRAP = 'external_venv_locked_requirement_then_frozen_check'
RUN_KEY = 'hepta-utility-36fa-runtime-materials-restore-86dd-v2'
FOREIGN_BUILD = {
    'uid': 1000,
    'job': '1a1d0e549d0-2564-1bdc',
    'cgroup': '0::/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a1d0e549d0-2564-1bdc.service\n',
    'cwd_root': '/home/qian-qi/hepta-learn-positive-ce434-8bf3881afa8c-isolated-v1/codex-rs',
    'executables': {
        'cargo': '/home/qian-qi/.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu/bin/cargo',
        'rustc': '/home/qian-qi/.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu/bin/rustc',
    },
    'original_probe_blob': '1920bec71be7ce926a7ed85e864a914e1f4ab0ea',
    'original_failed_result_blob': '88be32de12e28d39b685a7812bff9e217d4a192a',
    'scope': 'Only this exact foreign build may coexist with external material preparation; maintenance/test concurrency policy is unchanged.',
}
SAFE_SOURCE_ENV = ('CODEX_REPO_ROOT', 'PYTHONPATH')
UV_KEYS = ('UV_PROJECT_ENVIRONMENT', 'UV_CACHE_DIR', 'UV_OFFLINE',
           'RUFF_CACHE_DIR', 'UV_PYTHON_DOWNLOADS')
NETWORK_ENV_KEYS = ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
                    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE',
                    'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS')
ALLOWED_DOWNLOAD_HOSTS = frozenset(('github.com', 'release-assets.githubusercontent.com',
                                   'objects.githubusercontent.com', 'files.pythonhosted.org'))
ASSET_ROLES = ('uv-archive-checksum-text', 'uv-executable-archive', 'ruff-locked-wheel',
               'v8-pair-checksum-text', 'v8-sandbox-archive', 'v8-sandbox-bindings')
artifacts = []
commands = []
downloads = []
input_pins = {}
inventory_module = execute_module = None
before_inventory = before_git = None
network_before = None
deadline = None
cfg = plan = None
effective_environment = None
restored = {}
result = {'format': 'hepta-runtime-materials-restoration-result-v2',
          'status': 'HOLD', 'source_repo': str(REPO), 'source_commit': HEAD,
          'source_tree': TREE, 'parents': PARENTS, 'depot': str(DEPOT),
          'cargo_target': str(TARGET), 'source_unchanged': None,
          'source_comparison': 'unknown_not_observed', 'depot_created': False,
          'downloads_started': False, 'bootstrap_started': False,
          'maintenance_started': False, 'cargo_build_started': False,
          'test_commands_dispatched': 0, 'qualification': False,
          'source_ref_updates': False, 'automatic_retry': False,
          'original_offline_sync_find_links_proposal_executed': False,
          'bootstrap_strategy': BOOTSTRAP, 'run_key': RUN_KEY,
          'prior_failed_run_preserved': str(CONTROL / 'run'),
          'preparation_only_foreign_build_policy': FOREIGN_BUILD}


class IntegrityError(RuntimeError):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def nodup(pairs):
    value = {}
    for key, item in pairs:
        check(key not in value, 'duplicate JSON key: ' + key)
        value[key] = item
    return value


def parse(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=nodup)


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':')) + '\n').encode()


def real_directory(path, owned=False):
    path = Path(path)
    check(path.is_absolute() and str(path) == os.path.normpath(str(path)), 'canonical absolute directory')
    current = Path(path.anchor)
    for piece in path.parts[1:]:
        current /= piece
        info = current.lstat()
        check(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
              'non-real directory: ' + str(current))
    info = path.lstat()
    if owned:
        check(info.st_uid == os.getuid(), 'not current-user-owned directory: ' + str(path))
    return {'path': str(path), 'device': info.st_dev, 'inode': info.st_ino,
            'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode)}


def regular_read(path, maximum=40000000, owned=False):
    path = Path(path)
    real_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        first = os.fstat(fd)
        check(stat.S_ISREG(first.st_mode) and first.st_nlink == 1,
              'not single-link regular file: ' + str(path))
        check(not owned or first.st_uid == os.getuid(), 'not owned file: ' + str(path))
        check(first.st_size <= maximum, 'read byte ceiling: ' + str(path))
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(1048576, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            check(total <= maximum, 'read byte ceiling exceeded')
        last = os.fstat(fd)
        check(tuple(getattr(first, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')) ==
              tuple(getattr(last, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')),
              'file changed during read: ' + str(path))
        raw = b''.join(chunks)
        check(len(raw) == first.st_size, 'short file read')
        return raw
    finally:
        os.close(fd)


def pin_bytes(raw, pin, label):
    check(len(raw) == pin['bytes'] and sha256(raw) == pin['sha256']
          and git_blob(raw) == pin['git_blob'], 'exact input identity: ' + label)
    return raw


def read_input(path, pin):
    raw = regular_read(path, max(pin['bytes'], 40000000), owned=True)
    pin_bytes(raw, pin, str(path))
    input_pins[str(path)] = dict(pin)
    return raw


def put(path, raw, mode=0o600):
    path = Path(path)
    real_directory(path.parent, owned=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    check(regular_read(path, max(len(raw), 40000000), owned=True) == raw,
          'create-only readback mismatch: ' + str(path))


def record(name, raw):
    check(Path(name).name == name, 'one-level record name')
    put(OUT / name, raw)
    value = {'name': name, 'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': git_blob(raw)}
    artifacts.append(value)
    return value


def jrecord(name, value):
    return record(name, encoded(value))


def gzip_record(name, raw):
    compressed = gzip.compress(raw, mtime=0)
    check(gzip.decompress(compressed) == raw, 'gzip roundtrip')
    entry = record(name, compressed)
    entry.update(raw_bytes=len(raw), raw_sha256=sha256(raw), raw_git_blob=git_blob(raw))
    entry['parts'] = []
    for index, offset in enumerate(range(0, len(compressed), 262144), 1):
        chunk = compressed[offset:offset + 262144]
        part = record(name + '.part-%03d.b64' % index, base64.b64encode(chunk) + b'\n')
        part.update(decoded_offset=offset, decoded_bytes=len(chunk), decoded_sha256=sha256(chunk))
        entry['parts'].append(part)
    return entry


def event(kind, **fields):
    raw = encoded({'event': kind, 'at': now(), **fields})
    fd = os.open(OUT / 'EVENTS.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'ab') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(raw.decode(), end='', flush=True)


def remaining():
    value = deadline - time.monotonic()
    check(value > 0, 'preparation operation deadline reached')
    return value


def alarm(signum, frame):
    raise TimeoutError('separate preparation/evidence deadline reached')


def source_git_state():
    real_directory(REPO / '.git', owned=True)
    for relative in ('objects/info/alternates', 'shallow', 'info/grafts'):
        check(not os.path.lexists(REPO / '.git' / relative), 'unexpected Git lookup/history override: ' + relative)
    values = {}
    for name in ('HEAD', 'index', 'config'):
        raw = regular_read(REPO / '.git' / name, owned=True)
        values[name] = {'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': git_blob(raw)}
        if name == 'HEAD':
            check(raw == (HEAD + '\n').encode(), 'actual detached preparation HEAD')
    refs = subprocess.run([GIT, '--no-optional-locks', '-C', str(REPO), 'for-each-ref',
                           '--format=%(refname) %(objectname)'], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=30, check=False)
    check(refs.returncode == 0 and refs.stdout == b'', 'no source refs or Git command failure')
    values['refs'] = {'bytes': len(refs.stdout), 'sha256': sha256(refs.stdout)}
    return values


def load_module(path, pin, name):
    raw = read_input(path, pin)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def active_processes():
    observed, allowed, blocking, unknown = [], [], [], []
    names = ('cargo', 'cargo-clippy', 'clippy-driver', 'rustc', 'rustfmt', 'just', 'uv', 'ruff')
    stable_fields = ('comm', 'startticks', 'uids', 'cwd', 'exe', 'cgroup')

    def snapshot(entry):
        raw = (entry / 'stat').read_text()
        end = raw.rfind(')')
        fields = raw[end + 2:].split()
        status = (entry / 'status').read_text().splitlines()
        uids = [int(x) for x in next(line for line in status if line.startswith('Uid:')).split()[1:]]
        check(uids == [FOREIGN_BUILD['uid']] * 4, 'matching PID UID changed or is not the configured operator')
        return {'comm': raw[raw.find('(') + 1:end], 'state': fields[0],
                'ppid': int(fields[1]), 'startticks': int(fields[19]), 'uids': uids,
                'cwd': os.readlink(entry / 'cwd'), 'exe': os.readlink(entry / 'exe'),
                'cgroup': (entry / 'cgroup').read_text()}

    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        row = None
        try:
            name = (entry / 'comm').read_text().strip()
            if name not in names:
                continue
            row = {'pid': int(entry.name), 'initial_comm': name, 'observed_at': now()}
            status = (entry / 'status').read_text().splitlines()
            uid = int(next(line for line in status if line.startswith('Uid:')).split()[1])
            if uid != os.getuid():
                row.update(classification='outside_current_uid_scope', current_uid=uid)
                observed.append(row)
                continue
            first, last = snapshot(entry), snapshot(entry)
            row.update(before=first, after=last)
            stable = name == first['comm'] and all(first[key] == last[key] for key in stable_fields)
            row['identity_metadata_stable'] = stable
            if not stable:
                row.update(classification='unknown', reason='PID identity or scope metadata changed during observation')
                observed.append(row)
                unknown.append(row)
                continue
            cwd = Path(first['cwd'])
            own_path = any(cwd == root or cwd.is_relative_to(root) for root in (REPO, DEPOT, TARGET))
            exact_foreign = (
                first['comm'] in FOREIGN_BUILD['executables']
                and first['exe'] == FOREIGN_BUILD['executables'].get(first['comm'])
                and first['cgroup'] == FOREIGN_BUILD['cgroup']
                and cwd.is_absolute() and not first['cwd'].endswith(' (deleted)')
                and cwd.is_relative_to(Path(FOREIGN_BUILD['cwd_root']))
                and not own_path
            )
            if exact_foreign:
                row.update(classification='allowed_exact_foreign_build',
                           reason='Exact observed job, stable UID/startticks/comm/exe/cwd/cgroup; material preparation only')
                allowed.append(row)
            else:
                row.update(classification='blocking',
                           reason='Named same-user process is not the exact admitted foreign build',
                           touches_own_cwd_scope=own_path)
                blocking.append(row)
            observed.append(row)
        except (OSError, StopIteration, ValueError, IndexError) as error:
            if row is None and isinstance(error, FileNotFoundError):
                # No matching process was identified before this /proc entry vanished.
                continue
            row = row or {'pid': int(entry.name), 'observed_at': now()}
            row.update(classification='unknown', error_type=type(error).__name__,
                       error=str(error), errno=getattr(error, 'errno', None))
            observed.append(row)
            unknown.append(row)
    return {'observed': observed, 'allowed_exact_foreign_build': allowed,
            'blocking': blocking, 'unknown': unknown, 'fixed_foreign_build_policy': FOREIGN_BUILD,
            'scope': 'Same-user named-process identities only. No args/env, signals, foreign-task waits, or maintenance/test policy changes.'}


def file_identity(path, allow_symlink=False):
    path = Path(path)
    source = path.resolve(strict=True) if allow_symlink else path
    real_directory(source.parent)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        first = os.fstat(fd)
        check(stat.S_ISREG(first.st_mode), 'regular tool/material required: ' + str(path))
        digest = hashlib.sha256()
        object_hash = hashlib.sha1(b'blob ' + str(first.st_size).encode() + b'\0')
        while True:
            chunk = os.read(fd, 1048576)
            if not chunk:
                break
            digest.update(chunk)
            object_hash.update(chunk)
        last = os.fstat(fd)
        check(tuple(getattr(first, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')) ==
              tuple(getattr(last, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')),
              'tool/material changed while hashing: ' + str(path))
        return {'path': str(path), 'resolved': str(source), 'bytes': first.st_size,
                'sha256': digest.hexdigest(), 'git_blob': object_hash.hexdigest(),
                'device': first.st_dev, 'inode': first.st_ino, 'uid': first.st_uid,
                'nlink': first.st_nlink, 'mode': stat.S_IMODE(first.st_mode),
                'mtime_ns': first.st_mtime_ns, 'ctime_ns': first.st_ctime_ns}
    finally:
        os.close(fd)


def run_command(name, argv, seconds):
    row = {'name': name, 'argv': list(argv), 'cwd': str(REPO), 'started_at': now(),
           'requested_timeout_seconds': seconds, 'purpose': 'runtime material preparation; no test gate',
           'original_command_terminal': 'unknown_not_observed'}
    commands.append(row)
    allowed = min(float(seconds), remaining())
    row['effective_timeout_seconds'] = allowed
    event('preparation_command_started', name=name, argv=argv, timeout_seconds=allowed)
    # The unchanged helper owns this command group's deadline and cleanup.
    # Do not interrupt its kill/wait/final log retention with a competing alarm.
    signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        with (OUT / (name + '.forwarded.log')).open('x', encoding='utf-8') as output:
            with contextlib.redirect_stdout(output):
                execution = execute_module.execute_logged(argv, OUT / (name + '.log'),
                                                          timeout_seconds=allowed, maximum_bytes=LOG_LIMIT)
            output.flush()
            os.fsync(output.fileno())
        row.update(execution)
        row['original_command_terminal'] = 'observed'
    except BaseException as error:
        row.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        try:
            row['finished_at'] = now()
            for suffix in ('.log', '.forwarded.log'):
                path = OUT / (name + suffix)
                if path.exists():
                    raw = regular_read(path, LOG_LIMIT * 4 + 1024, owned=True)
                    artifacts.append({'name': path.name, 'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': git_blob(raw)})
            jrecord(name + '.json', row)
        finally:
            signal.setitimer(signal.ITIMER_REAL, max(0.0, deadline - time.monotonic()))
    check(execution['returncode'] == 0 and execution['timed_out'] is False
          and execution['output_limit_exceeded'] is False, name + ' failed; original command record retained')
    remaining()
    return regular_read(OUT / (name + '.log'), LOG_LIMIT, owned=True)


def validate_materialization(raw_result, raw_supervisor):
    observed = parse(raw_result)
    outer = parse(raw_supervisor)
    check(outer.get('isError') is False and len(outer.get('content', [])) == 1
          and outer['content'][0].get('type') == 'text', 'actual supervisor response shape')
    terminal = parse(outer['content'][0]['text'].encode())
    check(terminal.get('job_id') == '1a1d0c6996e-2564-1bc8'
          and terminal.get('state') == 'succeeded' and terminal.get('exit_code') == 0
          and terminal.get('timed_out') is False and terminal.get('cancelled') is False
          and terminal.get('automatic_retry') is False
          and terminal.get('output_complete') is True and terminal.get('output_durable') is True
          and terminal.get('terminal_publication_confirmed') is True
          and not any(terminal.get('log_truncated', {}).values()), 'actual complete materialization supervisor')
    check(observed.get('status') == 'MATERIALIZED_FOR_MAINTENANCE_ONLY'
          and observed.get('target_repo') == str(REPO) and observed.get('source_commit') == HEAD
          and observed.get('source_tree') == TREE and observed.get('parents') == PARENTS,
          'actual materialization source identity')
    check(observed.get('materialized') == {'head': HEAD, 'tree': TREE, 'index_equals_tree': True,
          'physical_bytes_equal': True, 'detached': True, 'maintenance_or_tests_started': False,
          'qualification': False}, 'actual complete materialization')
    for key in ('source_repo_unmodified', 'source_object_lookup_unchanged', 'inputs_unchanged'):
        check(observed.get(key) is True, 'materialization prerequisite ' + key)
    for key in ('maintenance_started', 'cargo_or_tests_started', 'qualification', 'remote_ref_updates'):
        check(observed.get(key) is False, 'materialization scope ' + key)
    check({row['check']: row['status'] for row in observed['final_audits']} == {
          'close_owned_helpers': 'verified', 'original_source': 'verified',
          'original_source_object_lookup': 'verified', 'new_destination': 'verified',
          'original_inputs': 'verified'}, 'complete materialization final audits')
    inv = observed['destination_inventory']
    check(all(inv.get(k) == v for k, v in SOURCE_PIN.items())
          and inv.get('tracked_entries') == inv.get('filesystem_entries') == 15188,
          'actual complete materialized baseline')
    result['materialization_job'] = terminal['job_id']


def preflight():
    global cfg, plan, inventory_module, execute_module, before_inventory, before_git
    global network_before, effective_environment
    raw_cfg = regular_read(CONFIG, 1000000, owned=True)
    cfg = parse(raw_cfg)
    check(cfg.get('format') == 'hepta-runtime-materials-restoration-approval-v2'
          and cfg.get('status') == 'ROOT_APPROVED_TO_EXECUTE'
          and cfg.get('root_execution_approved') is True, 'HOLD: exact Root approval required')
    own = regular_read(__file__, 200000, owned=True)
    check(cfg.get('driver_sha256') == sha256(own) and cfg.get('driver_git_blob') == git_blob(own),
          'exact approved driver identity')
    check(cfg.get('source_repo') == str(REPO) and cfg.get('source_commit') == HEAD
          and cfg.get('source_tree') == TREE and cfg.get('source_inventory') == SOURCE_PIN,
          'exact source and complete physical baseline approval')
    check(cfg.get('depot') == str(DEPOT) and cfg.get('cargo_target') == str(TARGET)
          and cfg.get('create_new_depot') is True and cfg.get('require_target_absent') is True,
          'only approved external directories, both initially absent')
    check(cfg.get('unique_idempotency_key') == RUN_KEY
          and cfg.get('preparation_only_foreign_build_policy') == FOREIGN_BUILD,
          'exact single foreign-job preparation isolation approval')
    check(cfg.get('operation_seconds') == OPERATION_SECONDS and cfg.get('final_seconds') == FINAL_SECONDS
          and cfg.get('outer_seconds') == 900 and cfg.get('bootstrap_strategy') == BOOTSTRAP,
          'reviewed preparation scope and budgets')
    check(cfg.get('maintenance_authorized') is False and cfg.get('tests_authorized') is False
          and cfg.get('remote_ref_updates_authorized') is False, 'preparation only')
    for path, raw in ((Path(__file__), own), (CONFIG, raw_cfg)):
        input_pins[str(path)] = {'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': git_blob(raw)}
    record('ACTUAL_DRIVER.py', own)
    record('APPROVED_CONFIG.original.json', raw_cfg)
    original = {name: read_input(CONTROL / name, pin) for name, pin in INPUTS.items()}
    plan = parse(original['DEPENDENCY_PLAN.original.json'])
    check(plan['source']['commit'] == HEAD and plan['source']['tree'] == TREE,
          'exact reviewed source dependency plan')
    check(len(plan['artifacts']) == 6 and {x['role'] for x in plan['artifacts']} == set(ASSET_ROLES),
          'six reviewed material roles')
    validate_materialization(original['MATERIALIZATION_RESULT.original.json'],
                             original['MATERIALIZATION_SUPERVISOR.original.json'])
    inventory_module = load_module(CONTROL / 'inventory-driver.original.py', INVENTORY_PIN,
                                   'hepta_restoration_original_inventory')
    execute_module = load_module(REPO / 'scripts/hepta_ci_exec.py', EXECUTE_PIN,
                                 'hepta_restoration_original_execute')
    # All unlisted process environment, including proxy/CA policy, is inherited.
    network_before = {key: os.environ.get(key) for key in NETWORK_ENV_KEYS}
    jrecord('INHERITED_SAFE_ENVIRONMENT.json', {
        'source_environment': {key: os.environ.get(key) for key in SAFE_SOURCE_ENV},
        'formatter_environment': {key: os.environ.get(key) for key in UV_KEYS},
        'network_environment_presence': {key: value is not None for key, value in network_before.items()},
        'network_values_recorded': False})
    unexpected = sorted(key for key in os.environ if (key.startswith('UV_') or key.startswith('RUFF_'))
                        and key not in UV_KEYS)
    check(not unexpected, 'unreviewed formatter environment names: ' + repr(unexpected))
    check(not any(os.environ.get(key) for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR',
          'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
          'GIT_SHALLOW_FILE', 'GIT_REPLACE_REF_BASE')), 'no inherited Git identity overrides')
    seed = parse(original['MAINTENANCE_STARTED.original.json'])['environment']
    effective_environment = dict(seed)
    effective_environment.update({
        'PATH': str(DEPOT / 'bin') + ':' + seed['PATH'],
        'CARGO_TARGET_DIR': str(TARGET),
        'RUSTY_V8_ARCHIVE': str(DEPOT / 'v8-150.4.0-gnu-sandbox' /
                              'librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz'),
        'RUSTY_V8_SRC_BINDING_PATH': str(DEPOT / 'v8-150.4.0-gnu-sandbox' /
                                       'src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs'),
        'UV_PROJECT_ENVIRONMENT': str(DEPOT / 'scripts-project-environment'),
        'UV_CACHE_DIR': str(DEPOT / 'uv-cache'), 'RUFF_CACHE_DIR': str(DEPOT / 'ruff-cache'),
        'UV_OFFLINE': 'true', 'UV_PYTHON_DOWNLOADS': 'never'})
    check(cfg.get('environment') == effective_environment, 'frozen complete explicit runtime environment')
    os.environ.update(effective_environment)
    before_git = source_git_state()
    jrecord('SOURCE_GIT_STATE.before.json', before_git)
    before_inventory = inventory_module.inventory(REPO)
    gzip_record('SOURCE.before.inventory.json.gz', before_inventory)
    pin_bytes(before_inventory, SOURCE_PIN, 'current complete 15188-file source')
    inventory_module.require_inventory(before_inventory, {'source_sha': HEAD, 'source_tree': TREE})
    value = parse(before_inventory)
    check(len(value['files']) == value['tracked_entries'] == value['filesystem_entries'] == 15188,
          'exact all-source file counts')
    for pin in plan['source']['pins']:
        read_input(REPO / pin['path'], {'bytes': pin['bytes'], 'sha256': pin['sha256'],
                                       'git_blob': pin['git_blob_sha']})
    process = active_processes()
    jrecord('PROCESS_PREFLIGHT.json', process)
    check(not process['blocking'] and not process['unknown'],
          'blocking/unknown named build or formatter outside exact foreign preparation allowance')
    result['process_preparation_observation'] = process
    check(platform.system() == 'Linux' and platform.machine() == 'x86_64'
          and platform.libc_ver()[0] == 'glibc', 'exact GNU x86_64 platform')
    check(sys.version_info >= (3, 10) and Path(sys.executable).resolve() == Path(PYTHON).resolve(),
          'existing explicit system Python >=3.10; no interpreter download')
    python = file_identity(PYTHON, allow_symlink=True)
    jrecord('PYTHON_AND_PLATFORM.json', {'python': python, 'version': sys.version,
            'platform': platform.platform(), 'libc': platform.libc_ver()})
    installed_tools = {}
    for name in ('git', 'just', 'python3', 'rustup', 'cargo'):
        path = shutil.which(name)
        check(path is not None, 'required existing tool unavailable on the original PATH: ' + name)
        installed_tools[name] = file_identity(path, allow_symlink=True)
        restored['tool_' + name] = installed_tools[name]
    jrecord('EXISTING_TOOL_FILES.json', installed_tools)
    real_directory(DEPOT.parent)
    check(os.access(DEPOT.parent, os.W_OK | os.X_OK), 'writable/searchable actual depot parent')
    check(not os.path.lexists(DEPOT), 'new depot already exists; reconcile instead of overwrite/replay')
    real_directory(TARGET.parent)
    check(os.access(TARGET.parent, os.W_OK | os.X_OK), 'writable/searchable actual target parent')
    check(not os.path.lexists(TARGET), 'dedicated Cargo target must still be absent before this new preparation')
    jrecord('EXTERNAL_ABSENCE_PREFLIGHT.json', {'at': now(), 'depot': str(DEPOT),
            'target': str(TARGET), 'depot_absent': True, 'target_absent': True,
            'existing_directories_reused': False})
    disk = shutil.disk_usage(DEPOT.parent)
    check(disk.free >= 6 * 1024**3, 'at least 6 GiB actual external free space required')
    jrecord('DISK_PREFLIGHT.json', {'parent': real_directory(DEPOT.parent),
            'total': disk.total, 'used': disk.used, 'free': disk.free,
            'minimum_free_bytes': 6 * 1024**3})
    os.mkdir(DEPOT, 0o700)
    result['depot_created'] = True
    for name in ('bin', 'downloads', 'wheelhouse', 'v8-150.4.0-gnu-sandbox', 'uv-cache', 'ruff-cache'):
        os.mkdir(DEPOT / name, 0o700)
    os.mkdir(TARGET, 0o700)
    target_created = True
    target = real_directory(TARGET, owned=True)
    check(os.access(TARGET, os.R_OK | os.W_OK | os.X_OK), 'accessible dedicated target directory')
    result['cargo_target_created'] = target_created
    jrecord('EXTERNAL_DIRECTORIES_CREATED.json', {'depot': real_directory(DEPOT, owned=True),
            'target': target, 'target_created': target_created, 'removed_or_replaced': []})
    restored['python'] = python
    event('restoration_preflight_complete', source_commit=HEAD, physical_files=15188,
          depot=str(DEPOT), cargo_target_created=target_created)


def safe_url(url):
    value = urllib.parse.urlsplit(url)
    check(value.scheme == 'https' and value.hostname in ALLOWED_DOWNLOAD_HOSTS
          and value.username is None and value.password is None and value.port in (None, 443),
          'unreviewed HTTPS download/redirect destination')
    return urllib.parse.urlunsplit((value.scheme, value.hostname, value.path, '', ''))


class FixedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, row):
        super().__init__()
        self.row = row

    def redirect_request(self, request, fp, code, message, headers, new_url):
        target = urllib.parse.urljoin(request.full_url, new_url)
        self.row['redirects'].append({'status': code, 'destination_without_query': safe_url(target)})
        check(len(self.row['redirects']) <= 5, 'download redirect ceiling')
        return super().redirect_request(request, fp, code, message, headers, target)


def download(asset):
    role = asset['role']
    folder = 'wheelhouse' if role == 'ruff-locked-wheel' else (
        'v8-150.4.0-gnu-sandbox' if role.startswith('v8-') else 'downloads')
    target = DEPOT / folder / asset['filename']
    check(Path(asset['filename']).name == asset['filename'], 'reviewed material basename')
    request_url = safe_url(asset['url'])
    check(request_url == asset['url'], 'reviewed URL has no dynamic query or credentials')
    row = {'role': role, 'requested_url': request_url, 'path': str(target),
           'expected_bytes': asset['bytes'], 'expected_sha256': asset['sha256'],
           'started_at': now(), 'redirects': [], 'complete_verified': False}
    downloads.append(row)
    result['downloads_started'] = True
    event('pinned_download_started', role=role, bytes=asset['bytes'])
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    total = 0
    digest = hashlib.sha256()
    start = time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, min(120.0, remaining()))
    try:
        with os.fdopen(fd, 'wb') as output:
            opener = urllib.request.build_opener(FixedRedirects(row))
            request = urllib.request.Request(asset['url'], headers={
                'User-Agent': 'hepta-pinned-runtime-preparation/1', 'Accept': 'application/octet-stream'})
            # Default urllib TLS verification, environment proxies and CA trust remain enabled.
            with opener.open(request, timeout=min(30.0, remaining())) as response:
                row['http_status'] = response.status
                row['final_destination_without_query'] = safe_url(response.geturl())
                row['content_length_header'] = response.headers.get('Content-Length')
                check(response.status == 200, 'expected HTTP 200 for pinned material')
                if row['content_length_header'] is not None:
                    check(int(row['content_length_header']) == asset['bytes'], 'pinned HTTP byte length')
                while True:
                    check(time.monotonic() - start < 120 and remaining() > 0, 'individual download deadline')
                    chunk = response.read(min(1048576, asset['bytes'] + 1 - total))
                    if not chunk:
                        break
                    output.write(chunk)
                    total += len(chunk)
                    digest.update(chunk)
                    check(total <= asset['bytes'], 'pinned download size exceeded')
            output.flush()
            os.fsync(output.fileno())
        check(total == asset['bytes'] and digest.hexdigest() == asset['sha256'],
              'pinned downloaded payload bytes/SHA256')
        observed = file_identity(target)
        check(observed['bytes'] == asset['bytes'] and observed['sha256'] == asset['sha256']
              and observed['nlink'] == 1 and observed['uid'] == os.getuid(), 'downloaded file readback')
        row.update(complete_verified=True, actual=observed)
        restored[role] = observed
        return target
    except BaseException as error:
        row['error_type'] = type(error).__name__
        row['error'] = str(error)
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, max(0.0, deadline - time.monotonic()))
        row.update(finished_at=now(), received_bytes=total, received_sha256=digest.hexdigest())
        try:
            row['retained_file'] = file_identity(target)
        except BaseException as error:
            row['retained_file_observation_error'] = {'type': type(error).__name__, 'message': str(error)}
        jrecord('download-%02d.json' % len(downloads), row)


def checksum_lines(path, expected):
    raw = regular_read(path, 4096, owned=True)
    lines = raw.decode('ascii').splitlines()
    parsed = {}
    for line in lines:
        match = re.fullmatch(r'([0-9a-f]{64}) [ *](\S+)', line)
        check(match is not None, 'canonical checksum text line')
        name = match[2]
        check(name not in parsed and Path(name).name == name, 'unique checksum basename')
        parsed[name] = match[1]
    check(parsed == expected, 'exact checksum set; no substituted profile/architecture')
    jrecord(path.name + '.parsed.json', {'path': str(path), 'entries': parsed, 'bytes': len(raw), 'sha256': sha256(raw)})


def extract_uv(archive):
    entries = []
    uv_member = None
    with tarfile.open(archive, mode='r:gz') as stream:
        total = 0
        for member in stream:
            check(len(entries) < 256, 'UV archive member ceiling')
            name = PurePosixPath(member.name)
            check(not name.is_absolute() and all(piece not in ('', '.', '..') for piece in name.parts),
                  'safe UV archive member path')
            check(member.isdir() or member.isfile(), 'UV archive contains a link or special entry')
            total += member.size
            check(total <= 256 * 1024**2, 'UV uncompressed archive ceiling')
            entries.append({'name': member.name, 'bytes': member.size, 'kind': 'directory' if member.isdir() else 'file',
                            'mode': member.mode})
            if name.name == 'uv':
                check(uv_member is None and member.isfile() and member.size <= 128 * 1024**2,
                      'unique bounded regular UV executable')
                uv_member = member
        check(uv_member is not None, 'UV executable missing in exact official archive')
        source = stream.extractfile(uv_member)
        check(source is not None, 'UV archive readable executable')
        with source:
            raw = source.read(uv_member.size + 1)
        check(len(raw) == uv_member.size and raw.startswith(b'\x7fELF'), 'complete actual UV ELF')
    target = DEPOT / 'bin' / 'uv'
    put(target, raw, 0o700)
    identity = file_identity(target)
    jrecord('UV_ARCHIVE_INDEX.json', {'archive': str(archive), 'entries': entries,
            'extraction_scope': 'only unique regular uv executable; no links/directories extracted', 'uv': identity})
    restored['uv'] = identity
    output = run_command('uv-version', [str(target), '--version'], 30)
    check(re.fullmatch(rb'uv 0\.11\.3(?: \([^\r\n]*\))?\r?\n', output) is not None,
          'actual pinned UV version 0.11.3')
    return target


def verify_wheel(wheel):
    with zipfile.ZipFile(wheel) as stream:
        names = stream.namelist()
        check(len(names) == len(set(names)) and len(names) <= 256, 'bounded unique Ruff wheel entries')
        for name in names:
            relative = PurePosixPath(name)
            check(not relative.is_absolute() and all(x not in ('', '.', '..') for x in relative.parts),
                  'safe Ruff wheel member')
        metadata = 'ruff-0.15.13.dist-info/METADATA'
        check(metadata in names and stream.getinfo(metadata).file_size <= 1000000, 'exact Ruff wheel metadata')
        raw = stream.read(metadata)
        text = raw.decode('utf-8')
        check(re.search(r'^Name: ruff$', text, re.M) and re.search(r'^Version: 0\.15\.13$', text, re.M),
              'actual Ruff wheel name/version')
        check(not re.search(r'^Requires-Dist:', text, re.M), 'sole locked Ruff wheel has no further runtime dependencies')
    record('RUFF_WHEEL_METADATA.original.txt', raw)


def bootstrap(uv, wheelhouse):
    venv = DEPOT / 'scripts-project-environment'
    check(not os.path.lexists(venv), 'fresh external project environment only')
    result['bootstrap_started'] = True
    run_command('uv-external-venv', [str(uv), 'venv', '--python', PYTHON, str(venv)], 120)
    real_directory(venv, owned=True)
    # A named locked requirement from the single verified flat-index wheel is
    # deliberate. Do not install a direct-URL requirement that changes provenance.
    run_command('uv-locked-ruff-install', [str(uv), 'pip', 'install', '--offline', '--no-index',
                '--find-links', str(wheelhouse), '--python', str(venv / 'bin/python'),
                'ruff==0.15.13'], 120)
    run_command('uv-frozen-offline-check', [str(uv), 'sync', '--frozen', '--project', 'scripts',
                '--offline', '--check'], 120)
    output = run_command('original-uv-run-ruff-version', [str(uv), 'run', '--frozen', '--project',
                          'scripts', 'ruff', '--version'], 120)
    check(output.strip() == b'ruff 0.15.13', 'actual original UV-run Ruff version')
    # Recheck after original uv run; do not infer the environment remained ready.
    run_command('uv-frozen-offline-final-check', [str(uv), 'sync', '--frozen', '--project',
                'scripts', '--offline', '--check'], 120)
    restored['venv_python'] = file_identity(venv / 'bin/python', allow_symlink=True)
    restored['ruff'] = file_identity(venv / 'bin/ruff', allow_symlink=True)
    check(restored['venv_python']['sha256'] == restored['python']['sha256'],
          'external environment uses the verified existing Python')
    check(restored['ruff']['resolved'].startswith(str(venv) + '/'), 'actual Ruff executable belongs to external venv')
    result['actual_frozen_offline_check_completed'] = True


def restore_materials():
    by_role = {row['role']: row for row in plan['artifacts']}
    paths = {}
    for role in ASSET_ROLES:
        paths[role] = download(by_role[role])
        if role == 'uv-archive-checksum-text':
            item = by_role['uv-executable-archive']
            checksum_lines(paths[role], {item['filename']: item['sha256']})
        elif role == 'v8-pair-checksum-text':
            checksum_lines(paths[role], {by_role[key]['filename']: by_role[key]['sha256']
                           for key in ('v8-sandbox-archive', 'v8-sandbox-bindings')})
    uv = extract_uv(paths['uv-executable-archive'])
    restored['tool_uv'] = file_identity(uv)
    verify_wheel(paths['ruff-locked-wheel'])
    bootstrap(uv, DEPOT / 'wheelhouse')
    result['materials_and_environment_prepared'] = True


def verify_materials_final():
    for role, pin in restored.items():
        current = file_identity(pin['path'], allow_symlink=role in ('python', 'venv_python', 'ruff') or role.startswith('tool_'))
        check(current == pin, 'restored tool/material changed before final admission: ' + role)
    for path in (DEPOT / 'uv-cache', DEPOT / 'ruff-cache', DEPOT / 'scripts-project-environment', TARGET):
        real_directory(path, owned=True)
    check({key: os.environ.get(key) for key in NETWORK_ENV_KEYS} == network_before,
          'proxy/CA policy changed in the preparation process')
    check(all(os.environ.get(key) == value for key, value in effective_environment.items()),
          'explicit final runtime environment changed')
    final = {'format': 'hepta-runtime-materials-environment-v1', 'source_commit': HEAD,
             'source_tree': TREE, 'depot': str(DEPOT), 'explicit_environment': effective_environment,
             'inherited_source_environment': {key: os.environ.get(key) for key in SAFE_SOURCE_ENV},
             'proxy_ca_values_preserved': True, 'proxy_ca_values_recorded': False,
             'tool_and_material_files': restored, 'downloads': downloads,
             'frozen_offline_project_check_completed': result.get('actual_frozen_offline_check_completed') is True,
             'no_maintenance_or_test_qualification': True}
    result['environment_record'] = jrecord('ENVIRONMENT_READY.json', final)
    return {'status': 'verified', 'material_and_tool_count': len(restored)}


def audit_source():
    if inventory_module is None:
        return {'status': 'not_observed', 'reason': 'original inventory module not admitted', 'source_unchanged': None}
    after = inventory_module.inventory(REPO)
    gzip_record('SOURCE.after.inventory.json.gz', after)
    after_git = source_git_state()
    jrecord('SOURCE_GIT_STATE.after.json', after_git)
    if before_inventory is None or before_git is None:
        result['source_comparison'] = 'unknown_before_unavailable'
        return {'status': 'not_observed', 'source_unchanged': None,
                'actual_after_sha256': sha256(after), 'reason': 'complete before comparison unavailable'}
    result['source_unchanged'] = after == before_inventory and after_git == before_git
    result['source_comparison'] = 'same' if result['source_unchanged'] else 'different'
    if not result['source_unchanged']:
        raise IntegrityError('actual complete source or HEAD/index/config/refs changed')
    pin_bytes(after, SOURCE_PIN, 'final complete 15188-file prepared source')
    inventory_module.require_inventory(after, {'source_sha': HEAD, 'source_tree': TREE})
    return {'status': 'verified', 'source_unchanged': True, 'inventory': SOURCE_PIN,
            'git_comparison_scope': 'HEAD/index/config/refs; no complete historical fsck claim'}


def audit_inputs():
    for path, pin in input_pins.items():
        pin_bytes(regular_read(path, max(pin['bytes'], 40000000), owned=True), pin, path)
    return {'status': 'verified', 'count': len(input_pins)}


def finish():
    result['finished_at'] = now()
    event('runtime_restoration_terminal', status=result['status'], source_unchanged=result['source_unchanged'],
          qualification=False, out=str(OUT))
    jrecord('COMMANDS.json', commands)
    jrecord('DOWNLOADS.json', downloads)
    jrecord('INPUT_IDENTITIES.json', input_pins)
    if (OUT / 'EVENTS.jsonl').exists():
        raw = regular_read(OUT / 'EVENTS.jsonl', LOG_LIMIT, owned=True)
        artifacts.append({'name': 'EVENTS.jsonl', 'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': git_blob(raw)})
    result['commands'] = commands
    result['downloads'] = downloads
    result['budget_scope'] = {'operation_seconds': OPERATION_SECONDS, 'final_evidence_seconds': FINAL_SECONDS,
                              'outer_seconds': 900, 'original_maintenance_or_test_budgets_changed': False}
    jrecord('ARTIFACTS.json', {'files': artifacts, 'terminal_report': 'RESULT.json', 'terminal_self_hash_included': False})
    jrecord('RESULT.json', result)


def main():
    global deadline
    result['started_at'] = now()
    real_directory(REPO, owned=True)
    real_directory(CONTROL, owned=True)
    check(not os.path.lexists(OUT), 'existing restoration output: reconcile, never automatically retry')
    os.mkdir(OUT, 0o700)
    lock = (OUT / 'EXCLUSIVE_RESTORATION.lock').open('x')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.chdir(REPO)
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    signal.signal(signal.SIGALRM, alarm)
    deadline = time.monotonic() + OPERATION_SECONDS
    signal.alarm(OPERATION_SECONDS)
    try:
        event('runtime_restoration_preconditions_started')
        preflight()
        restore_materials()
        result['status'] = 'MATERIALS_READY_FOR_MAINTENANCE_REVIEW'
    except BaseException as error:
        result.update(status='FAILED_PREPARATION', error=repr(error), traceback=traceback.format_exc())
    finally:
        signal.alarm(0)
        final_deadline = time.monotonic() + FINAL_SECONDS
        audits = []
        actions = [('source', audit_source), ('inputs', audit_inputs)]
        if result.get('materials_and_environment_prepared'):
            actions.append(('materials_environment', verify_materials_final))
        for name, action in actions:
            entry = {'check': name, 'started_at': now()}
            try:
                available = int(final_deadline - time.monotonic())
                check(available > 0, 'final evidence budget exhausted')
                signal.alarm(available)
                entry.update(action())
            except BaseException as error:
                entry.update(status='failed_integrity' if isinstance(error, IntegrityError) else 'unknown',
                             error=repr(error), traceback=traceback.format_exc())
            finally:
                signal.alarm(0)
            entry['finished_at'] = now()
            audits.append(entry)
        result['final_audits'] = audits
        if result['status'] == 'MATERIALS_READY_FOR_MAINTENANCE_REVIEW' and (
                len(audits) != 3 or any(row['status'] != 'verified' for row in audits)):
            result['status'] = 'UNKNOWN'
        if any(row['status'] == 'failed_integrity' for row in audits):
            result['status'] = 'FAILED_INTEGRITY'
        try:
            finish()
        except BaseException as error:
            result['status'] = 'UNKNOWN'
            print(json.dumps({'event': 'runtime_restoration_retention_error', 'status': 'UNKNOWN',
                              'error': repr(error), 'out': str(OUT), 'qualification': False}), flush=True)
        lock.close()
    return 0 if result['status'] == 'MATERIALS_READY_FOR_MAINTENANCE_REVIEW' else 1


if __name__ == '__main__':
    try:
        code = main()
    except BaseException as error:
        print(json.dumps({'event': 'runtime_restoration_admission_error', 'status': 'UNKNOWN',
                          'error': repr(error), 'automatic_retry': False, 'qualification': False}), flush=True)
        code = 1
    sys.exit(code)
