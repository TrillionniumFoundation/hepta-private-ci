import base64, datetime, gzip, hashlib, io, json, os, pathlib, select, stat, subprocess, time, traceback

REPO = '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
HEAD = 'cc57c7198db6293ccca562253c42fffbe2a04633'
TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
PARENT = '246d8cb614770252ee42029a5c014f2a4904176a'
INVENTORY = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/admission/SOURCE_FINAL.complete.inventory.json.gz'
INVENTORY_GZIP = {'bytes': 1261372, 'sha256': 'f305af89b78f8cc0facb73c71b778061349a20ee7ee0a39ecaecd882faecfe50'}
INVENTORY_RAW = {'bytes': 5611184, 'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'}
COMMIT = {'bytes': 916, 'sha256': '9bf2f19821b3007a29d446967ccc8a025e2ac671f1e0301c8e71b37848d72e48'}
GIT_PIN = {'bytes': 4066232, 'sha256': 'eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201'}
REF_PATH = '.git/refs/retired-artifacts/20261112-r71/3b03227b9431ee012e6b'
REF_BYTES = ('refs/retired-artifacts/20261112-r71/3b03227b9431ee012e6b ' + HEAD + '\n').encode()
METADATA = {
    '.git/HEAD': {'bytes': 41, 'sha256': 'c5cda15b2712092074c1870ef8056b4b4fa3b838684353c9f17def139b4b8f5b'},
    '.git/config': {'bytes': 102, 'sha256': 'cf0afb097e81d25b8554a3f4fce7294881cdebf1aedff43d685afbfadf44bb73', 'mode': 0o600},
    '.git/index': {'bytes': 2072293, 'sha256': 'b6ab195d789d241d958cd8971181efc91d0483ef94917a9f2e5352ee3f750aa8', 'mode': 0o600},
    REF_PATH: {'bytes': 41, 'sha256': 'c5cda15b2712092074c1870ef8056b4b4fa3b838684353c9f17def139b4b8f5b'},
}
MISSING_PATHS = [
    'qualification/cell-platform-fixtures-20261108/native-and-ci-evidence.tar.gz',
    'qualification/cell-research-stages-20261108/followthrough-20261108/verify1-independent-audit.tar.gz',
    'qualification/cell-research-stages-20261108/native-ci-routing-20261108/raw-ci-logs.tar.gz',
    'qualification/hcsn-localization-trainer-20261108/hcsn-trainer-native-evidence.zip',
    'qualification/memory-cell-mem1/raw-evidence-v1.tar.xz',
    'qualification/pin-utils-parent-backports-20261108/native-evidence.tar.gz',
    'qualification/pred1/evidence/pred1_evidence.tar.xz',
]
PREFIX = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '-C', REPO]
START = time.monotonic()
report = {'format': 'hepta-cc57-snapshot-object-availability-readonly-v1', 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'repo': REPO, 'commit': HEAD, 'tree': TREE, 'qualification': False, 'source_record_index_ref_writes': False, 'cargo_formatter_gate_or_network_commands': False, 'history_walk_or_fsck': False, 'current_physical_source_files_read': 0, 'commands': [], 'status': 'not_completed'}
index_transport = None

def check(value, reason):
    if not value:
        raise ValueError(reason)

def remaining():
    value = 45 - (time.monotonic() - START)
    if value <= 0:
        raise TimeoutError('read-only availability action deadline')
    return value

def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': oid('blob', raw)}

def stamp(s):
    return {'device': s.st_dev, 'inode': s.st_ino, 'mode': s.st_mode, 'uid': s.st_uid, 'gid': s.st_gid, 'nlink': s.st_nlink, 'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns}

def checked_read(path, expected, uid=1000):
    remaining()
    path = pathlib.Path(path)
    for parent in reversed(path.parents):
        s = parent.lstat()
        check(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode), 'real fixed path parents')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        check(stat.S_ISREG(before.st_mode) and before.st_uid == uid and before.st_nlink == 1, 'owned single-link regular input')
        check(before.st_size == expected['bytes'], 'exact bounded input size')
        if 'mode' in expected:
            check(stat.S_IMODE(before.st_mode) == expected['mode'], 'known exact input mode')
        raw = stream.read(expected['bytes'] + 1)
        after = os.fstat(stream.fileno())
    outside = path.lstat()
    check(stamp(before) == stamp(after) == stamp(outside), 'stable input bytes and identity')
    observed = identity(raw)
    check(observed['bytes'] == expected['bytes'] and observed['sha256'] == expected['sha256'], 'exact complete input identity: ' + str(path))
    remaining()
    return raw, {'path': str(path), 'identity': observed, 'stable_stat': stamp(after)}

def readonly(arguments, payload=b'', ceiling=4 * 1024 * 1024):
    row = {'argv': PREFIX + arguments, 'stdin': identity(payload), 'actual_terminal': 'unknown_not_observed'}
    report['commands'].append(row)
    budget = min(15, remaining())
    row['timeout_seconds'] = budget
    try:
        result = subprocess.run(row['argv'], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=REPO, timeout=budget, check=False)
        row.update(actual_terminal='observed', returncode=result.returncode, timed_out=False, stdout=identity(result.stdout), stderr=identity(result.stderr), stderr_base64=base64.b64encode(result.stderr).decode())
        check(len(result.stdout) <= ceiling and len(result.stderr) <= 65536, 'bounded read-only Git output')
        check(result.returncode == 0, 'read-only Git normal exit required')
        remaining()
        return result.stdout
    except subprocess.TimeoutExpired as exc:
        row.update(actual_terminal='observed_timeout', timed_out=True, partial_stdout=identity(exc.stdout or b''), partial_stderr_base64=base64.b64encode(exc.stderr or b'').decode())
        raise

def metadata_snapshot():
    rows = []
    index = None
    for relative, expected in METADATA.items():
        raw, row = checked_read(pathlib.Path(REPO) / relative, expected)
        rows.append(row)
        if relative == '.git/index':
            index = raw
    absences = ['.git/packed-refs', '.git/objects/info/alternates', '.git/shallow', '.git/info/grafts']
    for name in absences:
        check(not os.path.lexists(pathlib.Path(REPO) / name), 'fixed absent Git lookup path: ' + name)
    refs = readonly(['for-each-ref', '--format=%(refname) %(objectname)'], ceiling=65536)
    check(refs == REF_BYTES, 'retain exact already-observed old ref, do not clear or ignore it')
    return {'files': rows, 'refs': identity(refs), 'refs_base64': base64.b64encode(refs).decode(), 'absent_lookup_paths': absences}, index

def expected_objects(full):
    root, trees, blobs = {}, {}, {}
    for row in full['files']:
        path = pathlib.PurePosixPath(row['path'])
        check(not path.is_absolute() and all(x not in ('', '.', '..', '.git') for x in path.parts), 'safe canonical path')
        check(row['stable'] is True and row['matches_index'] is True and row['kind'] in ('file', 'symlink'), 'exact stable canonical source row')
        mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        check(mode == row['index_mode'] and row['index_blob'] == row['working_blob'], 'physical and index canonical membership')
        value = {'type': 'blob', 'bytes': row['bytes'], 'sha256': row['sha256']}
        key = row['working_blob']
        check(key not in blobs or blobs[key] == value, 'same blob identity across repeated leaves')
        blobs[key] = value
        node = root
        for part in path.parts[:-1]:
            node = node.setdefault(part, {})
            check(isinstance(node, dict), 'canonical tree directory')
        check(path.name not in node, 'unique canonical path')
        node[path.name] = (mode, key)
    def build(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, key = '40000', build(value)
            else:
                mode, key = value
            name = name.encode('utf-8')
            entries.append((name + (b'/' if mode == '40000' else b''), mode.encode() + b' ' + name + b'\0' + bytes.fromhex(key)))
        raw = b''.join(row[1] for row in sorted(entries))
        key = oid('tree', raw)
        check(key not in trees or trees[key] == raw, 'exact repeated tree')
        trees[key] = raw
        return key
    check(build(root) == TREE, 'independent complete canonical Merkle root')
    check(len(blobs) == 14610 and len(trees) == 1828, 'exact current snapshot object counts')
    objects = dict(blobs)
    objects.update({key: {'type': 'tree', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for key, raw in trees.items()})
    objects[HEAD] = {'type': 'commit', **COMMIT}
    return objects, trees

def verify_bodies(selected, objects, trees):
    listing = b''.join((key + '\n').encode() for key in selected)
    row = {'argv': PREFIX + ['cat-file', '--batch'], 'stdin': identity(listing), 'objects_requested': len(selected), 'actual_terminal': 'unknown_not_observed'}
    report['commands'].append(row)
    request_fd = error_fd = None
    process = None
    observed = []
    def read_exact(count):
        chunks = []
        left = count
        while left:
            check(select.select([process.stdout], [], [], remaining())[0], 'object stream deadline')
            piece = os.read(process.stdout.fileno(), min(left, 1048576))
            check(bool(piece), 'complete object stream')
            chunks.append(piece)
            left -= len(piece)
        return b''.join(chunks)
    try:
        request_fd = os.memfd_create('hepta-readonly-object-requests', os.MFD_CLOEXEC)
        error_fd = os.memfd_create('hepta-readonly-object-stderr', os.MFD_CLOEXEC)
        position = 0
        while position < len(listing):
            remaining()
            position += os.write(request_fd, listing[position:])
        os.lseek(request_fd, 0, os.SEEK_SET)
        remaining()
        process = subprocess.Popen(row['argv'], cwd=REPO, stdin=request_fd, stdout=subprocess.PIPE, stderr=error_fd, bufsize=0)
        for key in selected:
            header = b''
            while not header.endswith(b'\n'):
                check(len(header) < 160, 'bounded Git object header')
                header += read_exact(1)
            fields = header.rstrip(b'\n').split(b' ')
            expected = objects[key]
            check(fields == [key.encode(), expected['type'].encode(), str(expected['bytes']).encode()], 'exact selected object header')
            body = read_exact(expected['bytes'])
            check(read_exact(1) == b'\n' and oid(expected['type'], body) == key, 'full original object Git SHA')
            check(hashlib.sha256(body).hexdigest() == expected['sha256'], 'full original object SHA256')
            if key in trees:
                check(body == trees[key], 'full exact canonical tree body')
            if key == HEAD:
                lines = body.split(b'\n\n', 1)[0].splitlines()
                check([x for x in lines if x.startswith(b'tree ')] == [('tree ' + TREE).encode()] and [x for x in lines if x.startswith(b'parent ')] == [('parent ' + PARENT).encode()], 'original commit tree and ordered parents')
            observed.append({'sha': key, **expected})
        check(select.select([process.stdout], [], [], remaining())[0], 'object stream final EOF deadline')
        check(os.read(process.stdout.fileno(), 1) == b'', 'object stream has no trailing data')
        row['returncode'] = process.wait(timeout=remaining())
        row['actual_terminal'] = 'observed'
        check(row['returncode'] == 0, 'original object stream normal exit')
        return observed
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            try:
                row['cleanup_child_exit_code'] = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                row['cleanup_child_terminal'] = 'unknown_not_observed'
        if process is not None and process.stdout is not None:
            process.stdout.close()
        if error_fd is not None:
            size = os.fstat(error_fd).st_size
            os.lseek(error_fd, 0, os.SEEK_SET)
            errors = os.read(error_fd, min(size + 1, 65537))
            row.update(stderr_bytes_observed=size, stderr_captured=identity(errors), stderr_base64=base64.b64encode(errors).decode(), stderr_complete=len(errors) == size)
            os.close(error_fd)
        if request_fd is not None:
            os.close(request_fd)
        row['objects_fully_verified'] = len(observed)

try:
    check(os.getuid() == 1000, 'fixed original UID')
    for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_SHALLOW_FILE', 'GIT_REPLACE_REF_BASE', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS'):
        check(not os.environ.get(name), 'no inherited Git override: ' + name)
    _, report['git_tool_before'] = checked_read('/usr/bin/git', {**GIT_PIN, 'mode': 0o755}, uid=0)
    report['old_git_before'], index_raw = metadata_snapshot()
    packed_index = gzip.compress(index_raw, compresslevel=9, mtime=0)
    check(gzip.decompress(packed_index) == index_raw, 'lossless original old-index preservation')
    index_transport = {'format': 'hepta-readonly-old-index-transport-v1', 'raw': identity(index_raw), 'gzip': identity(packed_index), 'gzip_base64': base64.b64encode(packed_index).decode()}
    report['old_index_transport'] = {'raw': identity(index_raw), 'gzip': identity(packed_index), 'transport_record_follows_summary': True}
    packed, report['original_inventory_read'] = checked_read(INVENTORY, {**INVENTORY_GZIP, 'mode': 0o600})
    with gzip.GzipFile(fileobj=io.BytesIO(packed), mode='rb') as stream:
        raw = stream.read(INVENTORY_RAW['bytes'] + 1)
        check(len(raw) == INVENTORY_RAW['bytes'] and stream.read(1) == b'', 'bounded complete original inventory')
    check(hashlib.sha256(raw).hexdigest() == INVENTORY_RAW['sha256'], 'original complete inventory raw identity')
    full = json.loads(raw)
    check(full['source'] == {'head': HEAD, 'tree': TREE, 'status': ''} and full['tracked_entries'] == full['filesystem_entries'] == len(full['files']) == 15188, 'full current canonical membership')
    objects, trees = expected_objects(full)
    missing_leaves = {row['path']: row for row in full['files'] if row['path'] in MISSING_PATHS}
    check(set(missing_leaves) == set(MISSING_PATHS) and sum(x['bytes'] for x in missing_leaves.values()) == 18176884, 'seven exact original missing-archive identities')
    order = sorted(objects)
    listing = b''.join((key + '\n').encode() for key in order)
    metadata = readonly(['cat-file', '--batch-check'], listing)
    lines = metadata.splitlines()
    check(len(lines) == len(order) == 16439, 'one complete metadata result for every current snapshot object')
    absent, mismatched, available = [], [], set()
    for key, line in zip(order, lines):
        expected = objects[key]
        if line == (key + ' missing').encode():
            absent.append({'sha': key, **expected})
        elif line == (key + ' ' + expected['type'] + ' ' + str(expected['bytes'])).encode():
            available.add(key)
        else:
            mismatched.append({'expected_sha': key, 'expected': expected, 'actual_header_base64': base64.b64encode(line).decode()})
    report['availability'] = {'expected_objects': len(order), 'available_metadata': len(available), 'missing_objects': absent, 'mismatched_objects': mismatched, 'complete_metadata_stdout': identity(metadata)}
    selected = sorted((set(trees) | {HEAD} | {row['working_blob'] for row in missing_leaves.values()}) & available)
    observed = verify_bodies(selected, objects, trees)
    verified = {row['sha'] for row in observed}
    required_selected = set(trees) | {HEAD} | {row['working_blob'] for row in missing_leaves.values()}
    report['body_verification'] = {'requested_selected_objects': len(required_selected), 'actual_verified_objects': len(verified), 'all_expected_tree_bodies_verified': set(trees) <= verified, 'canonical_commit_body_verified': HEAD in verified, 'all_seven_archive_blobs_verified': all(row['working_blob'] in verified for row in missing_leaves.values()), 'verified_object_table': identity(json.dumps(observed, sort_keys=True, separators=(',', ':')).encode()), 'seven_blobs': [{'path': path, 'sha': row['working_blob'], 'bytes': row['bytes'], 'sha256': row['sha256'], 'full_body_verified': row['working_blob'] in verified} for path, row in sorted(missing_leaves.items())]}
    report['old_git_after'], after_index = metadata_snapshot()
    check(report['old_git_before'] == report['old_git_after'] and after_index == index_raw, 'old fixed Git metadata and refs unchanged by observation')
    _, report['git_tool_after'] = checked_read('/usr/bin/git', {**GIT_PIN, 'mode': 0o755}, uid=0)
    check(report['git_tool_before'] == report['git_tool_after'], 'same actual Git executable before and after')
    report.update(status='completed_readonly_availability_check', all_snapshot_objects_available=not absent and not mismatched, local_seven_blob_recovery_material_available=report['body_verification']['all_seven_archive_blobs_verified'], old_fixed_git_state_unchanged=True, limitation='The other 15181 current physical source files were not read. Their exact bytes must be revalidated during a separately approved fresh materialization. This checks one current snapshot, not complete commit history or qualification.')
    remaining()
except Exception as exc:
    report.update(status='failed_readonly_availability_check', error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
finally:
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['wall_seconds'] = time.monotonic() - START
    print(json.dumps(report, sort_keys=True, separators=(',', ':')), flush=True)
    if index_transport is not None:
        print(json.dumps(index_transport, sort_keys=True, separators=(',', ':')), flush=True)
raise SystemExit(0 if report['status'] == 'completed_readonly_availability_check' else 1)
