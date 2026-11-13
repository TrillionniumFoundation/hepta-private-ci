#!/usr/bin/env python3
"""One create-only restoration of the original missing V8 archive; never run gates.

The original runtime downloader and its HTTPS, size, hash, redirect and timeout
checks are retained byte-for-byte. Its DEPOT is a new evidence spool. Only a
fully verified payload may then populate the still-absent original archive.
"""
from __future__ import annotations

import base64
import datetime
import fcntl
import gzip
import hashlib
import json
import os
import pathlib
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import traceback
import types
import urllib.error
import urllib.parse
import urllib.request

CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/v8-single-archive-restore-v2')
OUT = CONTROL / 'run'
DEPOT = OUT / 'verified-download-spool'
REPO = Path('/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1')
OLD_DEPOT = Path('/data/hepta-utility-36fa-runtime-materials-86dd-v1')
V8_DIR = OLD_DEPOT / 'v8-150.4.0-gnu-sandbox'
ARCHIVE_NAME = 'librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz'
DESTINATION = V8_DIR / ARCHIVE_NAME
BINDINGS = V8_DIR / 'src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs'
ASSET = {
    'role': 'v8-sandbox-archive', 'filename': ARCHIVE_NAME,
    'url': 'https://github.com/openai/codex/releases/download/rusty-v8-v150.4.0/' + ARCHIVE_NAME,
    'bytes': 29366352,
    'sha256': 'a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583',
}
ARCHIVE_GIT = 'c6941f7873bdfb8ac18577c9844f234e76dc5ed6'
BINDING_PIN = {'bytes': 39884,
    'sha256': '7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506',
    'git_blob': '818270d5815fe0cce4bbf7f8f0b783291f93127e'}
SOURCE_PIN = {'bytes': 5611184,
    'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9',
    'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537'}
HEAD = 'cc57c7198db6293ccca562253c42fffbe2a04633'
TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
EXPECTED_GIT = {
    'config_bytes': 123, 'config_sha256': '5e224c2f489801ee7d2f46cf5c4e40261ea686332bac1588d05a5f463c59f84f',
    'head': HEAD, 'head_raw_sha256': 'c5cda15b2712092074c1870ef8056b4b4fa3b838684353c9f17def139b4b8f5b',
    'index_bytes': 2072488, 'index_sha256': '95547dcfed1945bb06b5400468ec228037cff5374b674ca033a7f66468b34193',
    'refs_bytes': 0, 'refs_sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'tree': TREE,
}
LOCK = Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock')
LOCK_PIN = {'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1}
RUN_KEY = 'hepta-utility-36fa-v8-single-archive-restore-v2'
OPERATION_SECONDS = 600
FINAL_SECONDS = 180
LOG_LIMIT = 8 * 1024 * 1024
GIT = '/usr/bin/git'
INVENTORY_PATH = Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/inventory-driver-v2.py')
INVENTORY_PIN = {'bytes': 22946,
    'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2',
    'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}
NATIVE_CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/final-native-cc57-isolated-v1')
HISTORY = Path('/home/qian-qi/hepta-utility-36fa-evidence/runtime-materials-restore-86dd-v1/run-v2')
INPUTS = (
    (NATIVE_CONTROL / 'APPROVED_QUALIFICATION_INPUT.json', {'bytes': 11785,
        'sha256': 'ffb59de9f19c3ec9c45ec4f750ee33220dcb74df4d35a07a0ef7b1a2be446b6f',
        'git_blob': '1666e5df58b33f1786287ba94d1d74b79442f8d6'}),
    (NATIVE_CONTROL / 'native-records/RESULT.json', {'bytes': 1003,
        'sha256': '3ff0675a3fb0dca9c6107b4982c1cb26f34007f5a3d4f62c46cd1a660428a50d',
        'git_blob': 'b6a785c0194c2f65054a26e5815042010a22dad8'}),
    (HISTORY / 'RESULT.json', {'bytes': 21366,
        'sha256': '272f2f2719d92b14939273d8807f5d1143b1307b7de78c4499fbfdad10f13a90',
        'git_blob': '7832ed48200e8361ae4a7dd5ca8b7b5f7f289b09'}),
    (HISTORY / 'ENVIRONMENT_READY.json', {'bytes': 21724,
        'sha256': 'd37a2b3eccf86e42643676d86cf0232ce1931de4693f45bb295761bb42da2172',
        'git_blob': '8b62ac16f554c1f34ee72974637752f5a3b58aec'}),
    (INVENTORY_PATH, INVENTORY_PIN),
)
ALLOWED_DOWNLOAD_HOSTS = frozenset(('github.com', 'release-assets.githubusercontent.com',
                                   'objects.githubusercontent.com', 'files.pythonhosted.org'))
artifacts = []
commands = []
downloads = []
restored = {}
input_pins = {}
deadline = None
before_inventory = before_git = binding_before = parents_before = None
inventory_module = None
environment_before = None
result = {
    'format': 'hepta-v8-single-archive-restoration-result-v1', 'status': 'HOLD',
    'qualification': False, 'source_repo': str(REPO), 'source_commit': HEAD, 'source_tree': TREE,
    'source_writes': False, 'environment_changes': False, 'native_main_started': False,
    'cargo_or_test_commands': [], 'automatic_retry': False, 'dependency_installation': False,
    'original_native_failure': 'b6a785c0194c2f65054a26e5815042010a22dad8',
    'readonly_observation': '1789babc0eeca7de054f209fc051ed8aa44582a4',
    'destination': str(DESTINATION), 'destination_created': False,
    'publication_intent_recorded': False, 'source_unchanged': None,
    'run_key': RUN_KEY,
    'budget': {'operation_seconds': 600, 'retention_seconds': 180, 'outer_seconds': 900,
               'native_qualification_budgets_changed': False},
}


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



def active_build_processes():
    active=[];unreadable=[]
    for item in pathlib.Path("/proc").iterdir():
        if not item.name.isdecimal():continue
        try:
            name=(item/"comm").read_text().strip()
            if name not in ("cargo","cargo-clippy","clippy-driver","rustc","rustfmt","just","uv","ruff"):
                continue
            status=(item/"status").read_text()
            uid_line=next(x for x in status.splitlines() if x.startswith("Uid:"))
            uid=int(uid_line.split()[1])
            if uid!=os.getuid():continue
            active.append({"pid":int(item.name),"comm":name,"uid":uid})
        except FileNotFoundError:
            continue
        except (OSError,StopIteration,ValueError) as error:
            unreadable.append({"pid":int(item.name),"error":type(error).__name__})
    return {"active_matching_processes":active,"unreadable_matching_processes":unreadable,
            "scope":"Same-UID process names only; no environment/argument values or credentials inspected; no processes killed."}




def complete_identity(raw):
    return {'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': git_blob(raw)}


def stat_identity(value):
    return {key: getattr(value, key) for key in (
        'st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
        'st_size', 'st_mtime_ns', 'st_ctime_ns')}


def arm():
    signal.setitimer(signal.ITIMER_REAL, remaining())


def stable_file(path, pin=None, mode=None):
    path = Path(path)
    before = path.lstat()
    raw = regular_read(path, 40000000, owned=True)
    after = path.lstat()
    check(stat_identity(before) == stat_identity(after), 'stable complete regular read: ' + str(path))
    check(stat.S_ISREG(after.st_mode) and after.st_nlink == 1 and after.st_uid == 1000,
          'owned single-link regular file: ' + str(path))
    if mode is not None:
        check(stat.S_IMODE(after.st_mode) == mode, 'exact existing permissions: ' + str(path))
    if pin is not None:
        pin_bytes(raw, pin, str(path))
    return raw, {'path': str(path), 'identity': complete_identity(raw), 'stat': stat_identity(after)}


def parent_observations():
    rows = []
    for path, expected_mode in ((Path('/data'), 0o755), (OLD_DEPOT, 0o700), (V8_DIR, 0o700)):
        real_directory(path, owned=True)
        value = path.lstat()
        check(stat.S_IMODE(value.st_mode) == expected_mode and value.st_gid == 1000,
              'existing fixed parent permissions/owner')
        rows.append({'path': str(path), 'stat': stat_identity(value)})
    return rows


def require_same_parent_identity(before, after, allow_archive_publication):
    check(len(before) == len(after) == 3, 'three fixed parents')
    for old, new in zip(before, after):
        check(old['path'] == new['path'], 'same fixed parent path')
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink')
        check(all(old['stat'][k] == new['stat'][k] for k in fields), 'fixed parent identity/permissions changed')
        if old['path'] != str(V8_DIR) or not allow_archive_publication:
            check(old == new, 'unrelated fixed parent metadata changed')


def require_absent_archive():
    try:
        value = DESTINATION.lstat()
    except FileNotFoundError:
        return {'path': str(DESTINATION), 'exists': False, 'observed_at': now()}
    raise IntegrityError('archive name exists; never replace, truncate, chmod or delete it: ' + repr(stat_identity(value)))


def check_build_processes(name):
    value = active_build_processes()
    jrecord(name, value)
    check(not value['active_matching_processes'] and not value['unreadable_matching_processes'],
          'original global build/formatter concurrency guard')


def git_output(arguments):
    allowed = (
        ('ls-files', '--stage', '-z'), ('rev-parse', 'HEAD'), ('rev-parse', 'HEAD^{tree}'),
        ('status', '--porcelain=v1', '--untracked-files=all'),
        ('for-each-ref', '--format=%(refname) %(objectname)'),
    )
    check(tuple(arguments) in allowed, 'closed readonly Git argv set')
    argv = [GIT, '--no-optional-locks', '-c', 'diff.autoRefreshIndex=false', '-C', str(REPO), *arguments]
    seconds = min(30.0, remaining())
    row = {'argv': argv, 'started_at': now(), 'requested_seconds': 30,
           'effective_seconds': seconds, 'mutation': False, 'original_command_terminal': 'unknown_not_observed'}
    commands.append(row)
    process = None
    output = error_output = b''
    signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        row['owned_pid'] = process.pid
        try:
            output, error_output = process.communicate(timeout=seconds)
            row.update(original_command_terminal='observed', returncode=process.returncode, timed_out=False)
        except subprocess.TimeoutExpired as error:
            output = error.output or b''
            error_output = error.stderr or b''
            row['timed_out'] = True
            raise
        check(len(output) + len(error_output) <= LOG_LIMIT, 'bounded readonly Git output')
        check(process.returncode == 0, 'readonly Git returned nonzero')
        return output
    except BaseException as error:
        row.update(error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                output, error_output = process.communicate(timeout=5)
                row.update(original_command_terminal='observed', returncode=process.returncode,
                           cleanup='owned Git process group killed and reaped')
            except BaseException as error:
                row['cleanup_error'] = type(error).__name__ + ': ' + str(error)
        elif process is not None and row['original_command_terminal'] != 'observed':
            try:
                output, error_output = process.communicate(timeout=5)
                row.update(original_command_terminal='observed', returncode=process.returncode)
            except BaseException as error:
                row['cleanup_error'] = type(error).__name__ + ': ' + str(error)
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        row.update(finished_at=now(), stdout=complete_identity(output), stderr=complete_identity(error_output))
        number = len(commands)
        gzip_record('git-%02d.stdout.gz' % number, output)
        record('git-%02d.stderr' % number, error_output)
        jrecord('git-%02d.json' % number, row)
        arm()


def inventory_check_output(argv):
    check(isinstance(argv, list) and argv[:3] == ['git', '-C', str(REPO)],
          'original inventory only this exact source')
    return git_output(argv[3:])


def source_git_state():
    real_directory(REPO / '.git', owned=True)
    for relative in ('objects/info/alternates', 'shallow', 'info/grafts', 'packed-refs'):
        check(not os.path.lexists(REPO / '.git' / relative), 'no Git lookup/ref override: ' + relative)
    raw_head, _ = stable_file(REPO / '.git/HEAD')
    raw_index, _ = stable_file(REPO / '.git/index')
    raw_config, _ = stable_file(REPO / '.git/config')
    check(raw_head == (HEAD + '\n').encode(), 'same detached actual source')
    refs = git_output(['for-each-ref', '--format=%(refname) %(objectname)'])
    tree = git_output(['rev-parse', 'HEAD^{tree}']).decode().strip()
    observed = {'head': HEAD, 'tree': tree, 'head_raw_sha256': sha256(raw_head),
        'index_bytes': len(raw_index), 'index_sha256': sha256(raw_index),
        'config_bytes': len(raw_config), 'config_sha256': sha256(raw_config),
        'refs_bytes': len(refs), 'refs_sha256': sha256(refs)}
    check(observed == EXPECTED_GIT, 'same actual native admission raw Git baseline')
    return observed


def capture_source(label):
    raw = inventory_module.inventory(REPO)
    pin_bytes(raw, SOURCE_PIN, 'actual complete 15188 source ' + label)
    inventory_module.require_inventory(raw, {'source_sha': HEAD, 'source_tree': TREE})
    value = parse(raw)
    check(value['tracked_entries'] == value['filesystem_entries'] == 15188, 'complete source count')
    artifact = gzip_record('SOURCE.' + label + '.inventory.json.gz', raw)
    state = source_git_state()
    jrecord('SOURCE.' + label + '.git-state.json', state)
    return raw, state, artifact


def preflight():
    global inventory_module, before_inventory, before_git, binding_before, parents_before, environment_before
    check(os.getuid() == os.geteuid() == 1000, 'original operator UID')
    environment_before = dict(os.environ)
    original_values = []
    for number, (path, pin) in enumerate(INPUTS):
        raw = read_input(path, pin)
        record('INPUT.%02d.original' % number, raw)
        original_values.append(parse(raw) if path.suffix == '.json' else raw)
    cfg, failed, history, ready, inventory_raw = original_values
    check(cfg['repo'] == str(REPO) and cfg['source'] == HEAD and cfg['tree'] == TREE,
          'exact failed native configuration source')
    check(failed['status'] == 'failed' and failed['behavioral_tests_started'] is False
          and failed['stages'] == [] and failed['error'] == 'ValueError: RUSTY_V8_ARCHIVE actual existing file required',
          'original zero-behavior precondition failure')
    archive = ready['tool_and_material_files']['v8-sandbox-archive']
    original_download = next(x for x in history['downloads'] if x['role'] == 'v8-sandbox-archive')
    check(original_download['requested_url'] == ASSET['url'] and original_download['complete_verified'] is True,
          'exact historically successful original source URL')
    check(archive == original_download['actual'] == original_download['retained_file'], 'same historical archive observation')
    check(archive['path'] == archive['resolved'] == str(DESTINATION)
          and archive['bytes'] == ASSET['bytes'] and archive['sha256'] == ASSET['sha256']
          and archive['git_blob'] == ARCHIVE_GIT and archive['mode'] == 0o600, 'same original archive identity')
    check(cfg['runtime_guard']['environment']['RUSTY_V8_ARCHIVE'] == str(DESTINATION)
          and cfg['runtime_guard']['environment']['RUSTY_V8_SRC_BINDING_PATH'] == str(BINDINGS),
          'no path/environment substitution')
    git_pin = ready['tool_and_material_files']['tool_git']
    git_raw = regular_read(GIT, 5000000)
    check(len(git_raw) == git_pin['bytes'] and sha256(git_raw) == git_pin['sha256']
          and git_blob(git_raw) == git_pin['git_blob'], 'actual original Git executable')
    inventory_module = types.ModuleType('original_5118_inventory_only')
    inventory_module.__file__ = str(INVENTORY_PATH)
    exec(compile(inventory_raw, str(INVENTORY_PATH), 'exec'), inventory_module.__dict__)
    inventory_module.subprocess = types.SimpleNamespace(check_output=inventory_check_output)
    # Original function bytes/serializer remain unchanged; only its fixed read-only
    # Git launcher receives the explicit deadline and no-optional-locks adapter.
    check_build_processes('BUILD_PROCESS_PREFLIGHT.json')
    parents_before = parent_observations()
    jrecord('MATERIAL_PARENTS.before.json', parents_before)
    jrecord('ARCHIVE.absent.before.json', require_absent_archive())
    _, binding_before = stable_file(BINDINGS, BINDING_PIN, 0o600)
    jrecord('BINDINGS.before.json', binding_before)
    before_inventory, before_git, _ = capture_source('before')


def restore_one():
    # The unchanged downloader can write only its new private evidence spool.
    os.mkdir(DEPOT, 0o700)
    os.mkdir(DEPOT / 'v8-150.4.0-gnu-sandbox', 0o700)
    spooled = download(ASSET)
    arm()
    payload, complete = stable_file(spooled, {'bytes': ASSET['bytes'],
        'sha256': ASSET['sha256'], 'git_blob': ARCHIVE_GIT}, 0o600)
    jrecord('VERIFIED_SPOOL.json', complete)
    check_build_processes('BUILD_PROCESS_BEFORE_PUBLICATION.json')
    require_same_parent_identity(parents_before, parent_observations(), False)
    _, observed_binding = stable_file(BINDINGS, BINDING_PIN, 0o600)
    check(observed_binding == binding_before, 'original bindings unchanged before publication')
    absence = require_absent_archive()
    jrecord('ARCHIVE_PUBLICATION_INTENT.json', {'at': now(), 'source_spool': complete,
        'destination': str(DESTINATION), 'required_absence': absence,
        'operation': 'O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW; no replace/delete/rollback', 'mode': 0o600})
    result['publication_intent_recorded'] = True
    put(DESTINATION, payload, 0o600)
    actual, observation = stable_file(DESTINATION, complete['identity'], 0o600)
    check(actual == payload, 'complete archive destination equals verified original payload')
    directory_fd = os.open(V8_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    result['destination_created'] = True
    result['archive_actual'] = observation
    jrecord('ARCHIVE_READBACK.json', observation)


def audit_source():
    if inventory_module is None or before_inventory is None or before_git is None:
        return {'status': 'unknown', 'reason': 'complete original before source unavailable'}
    raw, state, artifact = capture_source('after')
    check(raw == before_inventory and state == before_git, 'full source and raw Git unchanged')
    result['source_unchanged'] = True
    return {'status': 'verified', 'inventory': SOURCE_PIN, 'artifact': artifact,
            'raw_git': state, 'scope': 'complete physical source and HEAD/index/config/refs/declared indirection; not whole object-store metadata'}


def audit_materials():
    after_parents = parent_observations()
    jrecord('MATERIAL_PARENTS.after.json', after_parents)
    if parents_before is not None:
        require_same_parent_identity(parents_before, after_parents, result['publication_intent_recorded'])
    _, bindings = stable_file(BINDINGS, BINDING_PIN, 0o600)
    jrecord('BINDINGS.after.json', bindings)
    check(binding_before is not None and bindings == binding_before, 'original bindings full identity/stat unchanged')
    if not result['destination_created']:
        observation = {'exists': os.path.lexists(DESTINATION)}
        if observation['exists']:
            try:
                raw, observed = stable_file(DESTINATION)
                observation.update(observed)
            except BaseException as error:
                observation['error'] = type(error).__name__ + ': ' + str(error)
        jrecord('ARCHIVE.partial-or-absent.json', observation)
        return {'status': 'unknown', 'reason': 'exact archive publication did not complete', 'actual': observation}
    _, archive = stable_file(DESTINATION, {'bytes': ASSET['bytes'], 'sha256': ASSET['sha256'], 'git_blob': ARCHIVE_GIT}, 0o600)
    check(archive == result['archive_actual'], 'restored archive stable through final audit')
    return {'status': 'verified', 'archive': archive, 'bindings': bindings,
            'parent_metadata_comparison_scope': str(V8_DIR) + ' dev/inode/mode/uid/gid/nlink are equal; size/mtime/ctime may differ. No directory enumeration or exclusive cause attribution; any cause beyond this observed operation remains unknown.'}


def audit_inputs_environment():
    for path, pin in input_pins.items():
        pin_bytes(regular_read(path, max(40000000, pin['bytes']), owned=True), pin, path)
    check(environment_before is not None and dict(os.environ) == environment_before,
          'all inherited environment values preserved; values not recorded')
    return {'status': 'verified', 'input_count': len(input_pins), 'environment_unchanged': True}


def main():
    global deadline
    config_raw = sys.stdin.buffer.read(8193)
    check(len(config_raw) <= 8192, 'bounded exact configuration')
    cfg = parse(config_raw)
    expected = {'format': 'hepta-v8-single-archive-restoration-approval-v1',
        'status': 'ROOT_APPROVED_EXACT_EXECUTION', 'root_execution_approved': True,
        'run_key': RUN_KEY, 'control': str(CONTROL), 'destination': str(DESTINATION),
        'source_commit': HEAD, 'source_tree': TREE, 'operation_seconds': 600,
        'final_seconds': 180, 'outer_seconds': 900,
        'prior_native_failure_blob': 'b6a785c0194c2f65054a26e5815042010a22dad8',
        'readonly_observation_blob': '1789babc0eeca7de054f209fc051ed8aa44582a4'}
    check(cfg == expected, 'exact separate Root-approved material-only configuration')
    real_directory(CONTROL.parent, owned=True)
    check(not os.path.lexists(CONTROL), 'new operation only: reconcile existing job, never rerun')
    os.mkdir(CONTROL, 0o700)
    os.mkdir(OUT, 0o700)
    actual_script = sys.orig_argv[sys.orig_argv.index('-c') + 1].encode()
    record('ACTUAL_SCRIPT.py', actual_script)
    record('APPROVED_CONFIG.original.json', config_raw)
    input_pins[str(OUT / 'ACTUAL_SCRIPT.py')] = complete_identity(actual_script)
    input_pins[str(OUT / 'APPROVED_CONFIG.original.json')] = complete_identity(config_raw)
    signal.signal(signal.SIGALRM, alarm)
    deadline = time.monotonic() + OPERATION_SECONDS
    arm()
    lock_fd = None
    result['started_at'] = now()
    try:
        real_directory(LOCK.parent, owned=True)
        lock_fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
        lock_stat = os.fstat(lock_fd)
        actual_lock = {'device': lock_stat.st_dev, 'inode': lock_stat.st_ino, 'uid': lock_stat.st_uid,
                      'mode': stat.S_IMODE(lock_stat.st_mode), 'nlink': lock_stat.st_nlink}
        check(stat.S_ISREG(lock_stat.st_mode) and actual_lock == LOCK_PIN, 'same cooperative source coordination lock')
        fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        jrecord('SOURCE_COORDINATION_SH.json', {'at': now(), 'path': str(LOCK), **actual_lock,
            'scope': 'Cooperative source writers only; all complete before/after checks still required.'})
        preflight()
        restore_one()
        result['status'] = 'ARCHIVE_RESTORED_FOR_REVIEW_ONLY'
    except BaseException as error:
        result.update(status='FAILED_MATERIAL_PREPARATION', error=type(error).__name__ + ': ' + str(error), traceback=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        deadline = time.monotonic() + FINAL_SECONDS
        audits = []
        for name, action in (('source', audit_source), ('inputs_environment', audit_inputs_environment), ('materials', audit_materials)):
            entry = {'check': name, 'started_at': now()}
            try:
                arm()
                entry.update(action())
            except BaseException as error:
                entry.update(status='unknown', error=type(error).__name__ + ': ' + str(error), traceback=traceback.format_exc())
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            entry['finished_at'] = now()
            audits.append(entry)
        result['final_audits'] = audits
        if result['status'] == 'ARCHIVE_RESTORED_FOR_REVIEW_ONLY' and any(row['status'] != 'verified' for row in audits):
            result['status'] = 'UNKNOWN_MATERIAL_PREPARATION'
        try:
            arm()
            jrecord('COMMANDS.json', commands)
            jrecord('DOWNLOADS.json', downloads)
            jrecord('INPUT_IDENTITIES.json', input_pins)
            result['finished_at'] = now()
            result['downloads'] = downloads
            result['commands'] = commands
            jrecord('ARTIFACTS.json', {'files': artifacts, 'terminal_report': 'RESULT.json'})
            jrecord('RESULT.json', result)
            print(encoded({'status': result['status'], 'result': str(OUT / 'RESULT.json'),
                'qualification': False, 'source_unchanged': result['source_unchanged']}).decode(), end='', flush=True)
        except BaseException as error:
            result['status'] = 'UNKNOWN_MATERIAL_PREPARATION'
            print(encoded({'status': result['status'], 'retention_error': repr(error)}).decode(), end='', flush=True)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            if lock_fd is not None:
                os.close(lock_fd)
    return 0 if result['status'] == 'ARCHIVE_RESTORED_FOR_REVIEW_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
