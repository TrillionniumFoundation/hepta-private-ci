import base64, gzip, hashlib, io, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/source-repair-246d-fmt-control-v1')
PINS = {'driver.py': {'bytes': 28621, 'sha256': '0a7cc51c0ad9e1ef3b68e96f2942c36db04c3d42ee9dfcf8913099ea81a90228', 'git_blob': '9101b44fb2ab24ae41a1344425dd74b536a40de4'}, 'SOURCE_GATES_NORMAL.original.json': {'bytes': 952, 'sha256': '6499d8231230665037a977da78fe840177325f93b2b1e62f30a146251895d906', 'git_blob': 'bcc7b94d9f9f721f6592632db5a6408468014270'}, 'NONRUST_PACKET.json': None, 'APPROVED_CONFIG.json': None}

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
    check(set(packet) == {'format', 'files'} and packet['format'] == 'hepta-final-nonrust-format-bootstrap-v1', 'exact bootstrap schema')
    check(isinstance(packet['files'], dict) and set(packet['files']) == set(PINS), 'exact four input files')
    files = {}
    for name, pin in PINS.items():
        encoded = packet['files'][name]
        check(isinstance(encoded, str), 'base64 input required')
        raw = base64.b64decode(encoded, validate=True)
        if name == 'NONRUST_PACKET.json':
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
    retain('STAGING_READBACK.json', (json.dumps({'format': 'hepta-final-nonrust-format-bootstrap-readback-v1',
           'files': rows, 'source_writes_during_staging': False, 'qualification': False}, sort_keys=True, indent=2) + '\n').encode())
    directory_fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({'event': 'fixed_final_nonrust_format_bootstrap_verified', 'control': str(BASE),
                      'source_writes_during_staging': False, 'qualification': False}), flush=True)
    os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(BASE / 'driver.py'),
             '--config-sha256', PINS['APPROVED_CONFIG.json']['sha256']])
except BaseException as error:
    if created:
        try:
            retain('BOOTSTRAP_FAILURE.json', (json.dumps({'status': 'bootstrap_failed', 'error': repr(error),
                   'traceback': traceback.format_exc(), 'source_writes_during_staging': False,
                   'partial_records_preserved': True}, sort_keys=True, indent=2) + '\n').encode())
        except BaseException:
            pass
    raise
