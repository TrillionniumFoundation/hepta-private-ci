import base64, fcntl, hashlib, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/postformat-fence-proposals-v5-v1')
CONTROLS = BASE / 'controls'
RECORDS = BASE / 'records'
SOURCE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1')
LOCK = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock')
LOCK_IDENTITY = {'device': 2050, 'inode': 50139448, 'mode': 384, 'uid': 1000, 'nlink': 1}
PINS = {
    'extractor.py': {'bytes': 23468, 'sha256': 'faa04485bd3adfb4fe8b765e56da28d398803dd03f625c72a617c5235fe58edb', 'git_blob': 'f8686d5986f0f21404621d7e2d6a78634dc3f578'},
    'FENCE_MATRIX.original.json': {'bytes': 124054, 'sha256': '9e83fffb854297f7e70f1b72e9f594c2159c4b81955b64ac2eaeeab669b2eb2d', 'git_blob': 'ffaabdbd254bea8e3d45572c1e8e961625ee5119'},
    'CONTRACT_ROOT_REVIEWED.json': {'bytes': 34904, 'sha256': '3a38750c67485b73cea29e7e2bfd81fc975616c6e75e86c96fcba533315f5fcd', 'git_blob': 'a8797749da150f68d15f17028d6d0d7d43677047'},
    'STRUCTURAL_CALLERS.original.toml': {'bytes': 1294564, 'sha256': '8610f25a4d8ace133d07894f35c6bf5c5bdba0a4fb77bd7056ec24b5d2a302da', 'git_blob': '50eee584787ed0706ef2f900a09f1ca9d9cd8819'},
    'inventory-driver-v2.py': {'bytes': 22946, 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2', 'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'},
}
COPIED_INPUTS = {
    'STRUCTURAL_CALLERS.original.toml': SOURCE / 'CALLERS.toml',
    'inventory-driver-v2.py': pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/inventory-driver-v2.py'),
}
created = False
controls_created = False
lease_fd = None


def check(value, message):
    if not value:
        raise ValueError(message)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def real_parents():
    current = pathlib.Path(BASE.anchor)
    for part in BASE.parent.parts[1:]:
        current = current / part
        s = current.lstat()
        check(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode), 'real fixed parent required')
    check(BASE.parent.stat().st_uid == os.getuid(), 'owned evidence parent required')


def retain(name, raw):
    check(pathlib.Path(name).name == name, 'one-level fixed record')
    path = CONTROLS / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        first = os.fstat(f.fileno()); actual = f.read(len(raw) + 1); last = os.fstat(f.fileno())
    outside = path.lstat()
    def stamp(s):
        return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_nlink,
                s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    check(stamp(first) == stamp(last) == stamp(outside), 'record changed while reading')
    check(stat.S_ISREG(last.st_mode) and last.st_uid == os.getuid() and last.st_nlink == 1
          and stat.S_IMODE(last.st_mode) == 0o600 and actual == raw, 'exact regular record readback')
    return {'path': str(path), **identity(actual)}


def copied_input(path, pin):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        first = os.fstat(f.fileno()); raw = f.read(pin['bytes'] + 1); last = os.fstat(f.fileno())
    outside = path.lstat()
    def stamp(s):
        return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_nlink,
                s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    check(stamp(first) == stamp(last) == stamp(outside), 'copied input changed during read')
    check(stat.S_ISREG(last.st_mode) and last.st_uid == os.getuid() and last.st_nlink == 1,
          'real owned single-link copied input')
    check(identity(raw) == pin, 'fixed copied input: ' + str(path))
    return raw


try:
    check(os.getuid() == 1000, 'fixed desktop account')
    check(all(isinstance(pin, dict) for pin in PINS.values()), 'HOLD: final root-reviewed contract pin absent')
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    raw_input = sys.stdin.buffer.read(1048577)
    check(len(raw_input) <= 1048576, 'bounded exact input')
    packet = json.loads(raw_input)
    check(set(packet) == {'format', 'files'} and packet['format'] == 'hepta-postformat-fence-readonly-bootstrap-v1', 'exact bootstrap schema')
    supplied = set(PINS) - set(COPIED_INPUTS)
    check(isinstance(packet['files'], dict) and set(packet['files']) == supplied, 'exact three supplied inputs; two pinned local copies')
    files = {}
    for name in supplied:
        encoded = packet['files'][name]
        check(isinstance(encoded, str), 'base64 input required')
        raw = base64.b64decode(encoded, validate=True)
        check(identity(raw) == PINS[name], 'fixed input bytes: ' + name)
        files[name] = raw
    approved = json.loads(files['CONTRACT_ROOT_REVIEWED.json'])
    check(approved.get('status') == 'root_reviewed_actual_native_formatted_source'
          and isinstance(approved.get('root_review_blob'), str)
          and len(approved['root_review_blob']) == 40,
          'actual Root approval required; a WAITING contract cannot launch')
    check(approved.get('source_lock_path') == str(LOCK), 'same actual source coordination lock')
    real_parents()
    check(not os.path.lexists(BASE), 'existing control directory: reconcile original job; never overwrite')
    os.mkdir(BASE, 0o700); created = True
    s = BASE.lstat()
    check(stat.S_ISDIR(s.st_mode) and s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, 'owned private control parent')
    os.mkdir(CONTROLS, 0o700); controls_created = True
    s = CONTROLS.lstat()
    check(stat.S_ISDIR(s.st_mode) and s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, 'owned private control directory')
    argv = sys.orig_argv
    code = argv[argv.index('-c') + 1].encode('utf-8')
    rows = [retain('ACTUAL_BOOTSTRAP.py', code),
            retain('ACTUAL_BOOTSTRAP_ARGV.json', (json.dumps(argv, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()),
            retain('ACTUAL_BOOTSTRAP_PAYLOAD.json', raw_input)]
    lease_fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    lock_stat = os.fstat(lease_fd)
    check(stat.S_ISREG(lock_stat.st_mode), 'same real source lock')
    lock_observation = {'device': lock_stat.st_dev, 'inode': lock_stat.st_ino,
                        'mode': stat.S_IMODE(lock_stat.st_mode), 'uid': lock_stat.st_uid,
                        'nlink': lock_stat.st_nlink}
    check(lock_observation == LOCK_IDENTITY, 'same actually observed source lock identity')
    fcntl.flock(lease_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    os.set_inheritable(lease_fd, True)
    check((LOCK.lstat().st_dev, LOCK.lstat().st_ino) == (lock_stat.st_dev, lock_stat.st_ino), 'source lock path changed')
    rows.append(retain('SOURCE_COORDINATION_SH.json', (json.dumps({
        **lock_observation, 'path': str(LOCK), 'pid': os.getpid(), 'fd': lease_fd,
        'lock_acquired': 'LOCK_SH|LOCK_NB', 'inherited_across_exec': True,
        'extractor_also_acquires_same_lock': True,
        'scope': 'This task cooperative writers only; full original before/after inventories remain mandatory.',
        'source_writes': False, 'qualification': False,
    }, sort_keys=True, indent=2) + '\n').encode()))
    for name, path in COPIED_INPUTS.items():
        files[name] = copied_input(path, PINS[name])
    rows += [retain(name, files[name]) for name in PINS]
    retain('STAGING_READBACK.json', (json.dumps({'format': 'hepta-postformat-fence-readonly-bootstrap-readback-v1',
           'files': rows, 'source_writes': False, 'qualification': False}, sort_keys=True, indent=2) + '\n').encode())
    for directory in (CONTROLS, BASE):
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    print(json.dumps({'event': 'fixed_postformat_fence_readonly_bootstrap_verified', 'control': str(CONTROLS),
                      'source_writes': False, 'qualification': False}), flush=True)
    os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(CONTROLS / 'extractor.py'),
             '--root', str(SOURCE), '--contract', str(CONTROLS / 'CONTRACT_ROOT_REVIEWED.json'),
             '--contract-sha256', PINS['CONTRACT_ROOT_REVIEWED.json']['sha256'],
             '--plan', str(CONTROLS / 'FENCE_MATRIX.original.json'),
             '--inventory-driver', str(CONTROLS / 'inventory-driver-v2.py'),
             '--structural-callers', str(CONTROLS / 'STRUCTURAL_CALLERS.original.toml'),
             '--records', str(RECORDS)])
except BaseException as error:
    if controls_created:
        try:
            retain('BOOTSTRAP_FAILURE.json', (json.dumps({'status': 'bootstrap_failed', 'error': repr(error),
                   'traceback': traceback.format_exc(), 'source_writes': False,
                   'extractor_terminal': 'not_observed', 'partial_records_preserved': True}, sort_keys=True, indent=2) + '\n').encode())
        except BaseException:
            pass
    if lease_fd is not None:
        os.close(lease_fd)
    raise
