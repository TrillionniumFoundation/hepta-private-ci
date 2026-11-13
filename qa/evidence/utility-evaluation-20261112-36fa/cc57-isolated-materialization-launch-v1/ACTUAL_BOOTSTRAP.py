import base64, gzip, hashlib, io, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1')
PINS = {
    'driver.py': {'bytes': 57607, 'sha256': '5717afe87597089462b685014d0687f0d45a3416f5a1d65580f69f26c9650436', 'git_blob': '972ec74449b113a95b4ec098e562a565f23aa82f'},
    'MATERIALIZATION_PACKET.json': {'bytes': 13764, 'sha256': 'b2a62c45873fe6c37257df5561accd9d30dcf2d7ca969de6968fec7ac1e3acc3', 'git_blob': '06503652a2895120daf8b66e42b3a01cefeaf4fb'},
    'AVAILABILITY_RESULT.original.json': {'bytes': 11954, 'sha256': '7631a19a48c56b4a37b396b97d57f19793baa67cdb37e31acb7a3dd79f397a22', 'git_blob': '365a11bbfc183a05d76076da08301ce227847191'},
    'AVAILABILITY_SUPERVISOR.original.json': {'bytes': 956, 'sha256': '417a8191432b901a1b1c625518e31ae77e51150ee9494c616fe16da04a56c3de', 'git_blob': '432eeed53c480af77bd3b79fef43d3f96f1ca22c'},
    'APPROVED_CONFIG.json': {'bytes': 992, 'sha256': '414a52cdd7802f5d84de65ee70422a14eb93d799ca46912a9d618f734bffe6a0', 'git_blob': '692d2b825dcbb38eb95e91c0fb5f67afa39d0518'},
}

created = False

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
    path = BASE / name
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

try:
    check(os.getuid() == 1000, 'fixed desktop account')
    check(all(isinstance(pin, dict) for pin in PINS.values()), 'HOLD: final reviewed packet or approved config pin absent')
    raw_input = sys.stdin.buffer.read(1048577)
    check(len(raw_input) <= 1048576, 'bounded exact input')
    packet = json.loads(raw_input)
    check(set(packet) == {'format', 'files'} and packet['format'] == 'hepta-isolated-cc57-materialization-bootstrap-v1', 'exact bootstrap schema')
    check(isinstance(packet['files'], dict) and set(packet['files']) == set(PINS), 'exact five input files')
    files = {}
    for name, pin in PINS.items():
        encoded = packet['files'][name]
        check(isinstance(encoded, str), 'base64 input required')
        raw = base64.b64decode(encoded, validate=True)
        if name == 'MATERIALIZATION_PACKET.json':
            check(type(pin['bytes']) is int and 0 < pin['bytes'] <= 40000000, 'bounded reviewed packet')
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                expanded = stream.read(pin['bytes'] + 1)
                check(len(expanded) == pin['bytes'] and stream.read(1) == b'', 'complete bounded reviewed packet')
            raw = expanded
        check(identity(raw) == pin, 'fixed input bytes: ' + name)
        files[name] = raw
    real_parents()
    check(not os.path.lexists(BASE), 'existing control directory: reconcile original job; never overwrite')
    os.mkdir(BASE, 0o700); created = True
    s = BASE.lstat()
    check(stat.S_ISDIR(s.st_mode) and s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, 'owned private control directory')
    argv = sys.orig_argv
    code = argv[argv.index('-c') + 1].encode('utf-8')
    rows = [retain('ACTUAL_BOOTSTRAP.py', code),
            retain('ACTUAL_BOOTSTRAP_ARGV.json', (json.dumps(argv, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()),
            retain('ACTUAL_BOOTSTRAP_PAYLOAD.json', raw_input)]
    rows += [retain(name, raw) for name, raw in files.items()]
    retain('STAGING_READBACK.json', (json.dumps({'format': 'hepta-isolated-cc57-materialization-bootstrap-readback-v1',
           'files': rows, 'source_writes_during_staging': False, 'qualification': False}, sort_keys=True, indent=2) + '\n').encode())
    directory_fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({'event': 'fixed_isolated_cc57_materialization_bootstrap_verified', 'control': str(BASE),
                      'source_writes_during_staging': False, 'qualification': False}), flush=True)
    os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(BASE / 'driver.py')])
except BaseException as error:
    if created:
        try:
            retain('BOOTSTRAP_FAILURE.json', (json.dumps({'status': 'bootstrap_failed', 'error': repr(error),
                   'traceback': traceback.format_exc(), 'source_writes_during_staging': False,
                   'partial_records_preserved': True}, sort_keys=True, indent=2) + '\n').encode())
        except BaseException:
            pass
    raise
