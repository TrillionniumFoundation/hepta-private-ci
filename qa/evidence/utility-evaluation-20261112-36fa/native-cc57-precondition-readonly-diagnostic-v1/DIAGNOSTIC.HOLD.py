import base64, datetime, gzip, hashlib, io, json, os, pathlib, stat, subprocess, time, traceback

REPO = '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2'
EXPECTED_SOURCE = {'head': 'cc57c7198db6293ccca562253c42fffbe2a04633', 'tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e', 'status': ''}
EXPECTED_NATIVE = {'bytes': 3530181, 'sha256': '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9', 'git_blob': '2def77faf50ba6d74d923732182dcb3cad916e53'}
ORIGIN_RAW = {'bytes': 5611184, 'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9', 'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537'}
ITEMS = [
    {'label': 'native_summary', 'path': BASE + '/native-records/source-after.json', 'mode': 0o400, 'bytes': 237, 'sha256': '991660a9239b56f429784c9cb0271fd9d760be0da730462a1a417419c180467e'},
    {'label': 'native_gzip', 'path': BASE + '/native-records/source-after.files.json.gz', 'mode': 0o400, 'bytes': 1169526, 'sha256': '780933b23d9d2d3c792b7eb753544056c8ac4e72e07003b2c58932d0ba671282'},
    {'label': 'origin_gzip', 'path': BASE + '/source-handoff/admission/SOURCE_FINAL.complete.inventory.json.gz', 'mode': 0o600, 'bytes': 1261372, 'sha256': 'f305af89b78f8cc0facb73c71b778061349a20ee7ee0a39ecaecd882faecfe50'},
]
ARGV = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '-C', REPO, 'for-each-ref', '--format=%(refname) %(objectname)']
START = time.monotonic()
report = {'format': 'hepta-native-precondition-snapshot-readonly-diagnostic-v1', 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'source_job_id': '1a1d23c92f3-2564-1cb4', 'native_job_id': '1a1d26326ac-2564-1cd4', 'repo': REPO, 'qualification': False, 'source_or_record_writes': False, 'cargo_formatter_or_gate_commands': False, 'observations': [], 'status': 'not_completed'}

def check(value, message):
    if not value:
        raise ValueError(message)

def remaining():
    value = 45 - (time.monotonic() - START)
    if value <= 0:
        raise TimeoutError('read-only diagnostic action deadline exhausted')
    return value

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def stamp(s):
    return {'device': s.st_dev, 'inode': s.st_ino, 'mode': s.st_mode, 'uid': s.st_uid, 'gid': s.st_gid, 'nlink': s.st_nlink, 'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns}

def read_original(item):
    remaining()
    path = pathlib.Path(item['path'])
    for parent in reversed(path.parents):
        meta = parent.lstat()
        check(stat.S_ISDIR(meta.st_mode) and not stat.S_ISLNK(meta.st_mode), 'real fixed record parent')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        check(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1, 'owned single-link regular original')
        check(before.st_size == item['bytes'] and stat.S_IMODE(before.st_mode) == item['mode'], 'original size and mode')
        raw = stream.read(item['bytes'] + 1)
        after = os.fstat(stream.fileno())
    outside = path.lstat()
    check(stamp(before) == stamp(after) == stamp(outside), 'stable original read')
    actual = identity(raw)
    check(actual['bytes'] == item['bytes'] and actual['sha256'] == item['sha256'], 'complete fixed original identity: ' + item['label'])
    report['observations'].append({'label': item['label'], 'path': item['path'], 'identity': actual, 'stable_stat': stamp(after), 'full_bounded_read': True})
    remaining()
    return raw

def inflate(raw, maximum=8 * 1024 * 1024):
    remaining()
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as stream:
        result = stream.read(maximum + 1)
        check(len(result) <= maximum, 'decoded artifact size ceiling')
        check(stream.read(1) == b'', 'decoded artifact EOF')
    remaining()
    return result

def pairs(values):
    out = {}
    for key, value in values:
        check(key not in out, 'duplicate JSON key')
        out[key] = value
    return out

def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs)

def original_native_bytes(rows):
    return json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()

def refs_observation():
    row = {'argv': ARGV, 'cwd': REPO, 'actual_terminal': 'unknown_not_observed'}
    report['refs_command'] = row
    budget = min(10, remaining())
    row['timeout_seconds'] = budget
    try:
        proc = subprocess.run(ARGV, cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=budget, check=False)
        row.update({'actual_terminal': 'observed', 'returncode': proc.returncode, 'timed_out': False, 'stdout': identity(proc.stdout), 'stderr': identity(proc.stderr), 'stdout_base64': base64.b64encode(proc.stdout).decode(), 'stderr_base64': base64.b64encode(proc.stderr).decode()})
        check(len(proc.stdout) <= 1048576 and len(proc.stderr) <= 65536, 'read-only Git output ceiling')
        check(proc.returncode == 0, 'read-only Git command returned nonzero')
    except subprocess.TimeoutExpired as exc:
        row.update({'actual_terminal': 'observed_timeout', 'timed_out': True, 'partial_stdout_base64': base64.b64encode(exc.stdout or b'').decode(), 'partial_stderr_base64': base64.b64encode(exc.stderr or b'').decode()})
        raise
    remaining()

try:
    check(os.getuid() == 1000, 'fixed original UID')
    for path in (pathlib.Path(REPO), pathlib.Path(REPO) / '.git'):
        check(stat.S_ISDIR(path.lstat().st_mode) and not path.is_symlink(), 'fixed real repository directory')
    refs_observation()
    originals = {item['label']: read_original(item) for item in ITEMS}
    summary = parse(originals['native_summary'])
    check(summary == {'commit': EXPECTED_SOURCE['head'], 'tree': EXPECTED_SOURCE['tree'], 'status': '', 'files': 15188, 'inventory_sha256': '6c28a1e1291c9c96879718e6c1b81028f9fa12c9ba358123090852d5b6e72b8f'}, 'actual failed native summary identity')
    actual_raw = inflate(originals['native_gzip'])
    check(identity(actual_raw)['sha256'] == summary['inventory_sha256'], 'failed native snapshot raw identity')
    actual = parse(actual_raw)
    check(isinstance(actual, list) and len(actual) == summary['files'], 'actual native row count')
    actual_names = [row['path'] for row in actual]
    check(all(isinstance(path, str) for path in actual_names) and len(set(actual_names)) == len(actual_names), 'unique actual paths')
    check(actual_names == sorted(actual_names, key=os.fsencode), 'original native byte path order')
    check(original_native_bytes(actual) == actual_raw, 'actual original native serializer')
    for row in actual:
        check(set(row) == {'path', 'mode', 'bytes', 'sha256', 'blob'} or (set(row) == {'path', 'missing'} and row['missing'] is True), 'original native row shape')
    origin_raw = inflate(originals['origin_gzip'])
    check(identity(origin_raw) == ORIGIN_RAW, 'original successful source full inventory')
    origin = parse(origin_raw)
    check(origin['source'] == EXPECTED_SOURCE and origin['tracked_entries'] == origin['filesystem_entries'] == len(origin['files']) == 15188, 'original successful source identities')
    expected = []
    for row in sorted(origin['files'], key=lambda item: os.fsencode(item['path'])):
        check(row['stable'] is True and row['matches_index'] is True, 'original full source row stable and matches index')
        mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        check(row['kind'] in ('file', 'symlink'), 'original supported source kind')
        expected.append({'path': row['path'], 'mode': mode, 'bytes': row['bytes'], 'sha256': row['sha256'], 'blob': row['working_blob']})
    expected_raw = original_native_bytes(expected)
    check(identity(expected_raw) == EXPECTED_NATIVE, 'exact original five-field projection matches frozen expectation')
    old = {row['path']: row for row in expected}
    new = {row['path']: row for row in actual}
    check(len(old) == 15188, 'unique original source paths')
    changes = []
    counts = {'added': 0, 'removed': 0, 'changed': 0, 'unchanged': 0}
    for path in sorted(set(old) | set(new), key=os.fsencode):
        before, after = old.get(path), new.get(path)
        if before == after:
            counts['unchanged'] += 1
            continue
        kind = 'added' if before is None else ('removed' if after is None else 'changed')
        counts[kind] += 1
        changes.append({'path': path, 'kind': kind, 'before': before, 'after': after})
    diff_raw = original_native_bytes(changes)
    packed = gzip.compress(diff_raw, compresslevel=9, mtime=0)
    check(inflate(packed, 16 * 1024 * 1024) == diff_raw, 'lossless complete row-difference transport')
    report.update({'status': 'completed_readonly_diagnostic', 'expected_native_identity': identity(expected_raw), 'actual_native_identity': identity(actual_raw), 'origin_complete_identity': identity(origin_raw), 'row_counts': counts, 'source_snapshots_equal': expected_raw == actual_raw, 'diff_raw_identity': identity(diff_raw), 'diff_gzip_identity': identity(packed), 'diff_gzip_base64': base64.b64encode(packed).decode(), 'diff_rows_complete': True, 'scope': 'One original read-only Git refs command and three completed fixed evidence files. No current worktree contents or unrelated repositories are read. This does not identify the writer or repair source/index/refs.'})
    remaining()
except Exception as exc:
    report.update({'status': 'failed_readonly_diagnostic', 'error': type(exc).__name__ + ': ' + str(exc), 'traceback': traceback.format_exc()})
finally:
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['wall_seconds'] = time.monotonic() - START
    print(json.dumps(report, sort_keys=True, separators=(',', ':')), flush=True)
raise SystemExit(0 if report['status'] == 'completed_readonly_diagnostic' else 1)
