import base64, hashlib, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/postformat-capture-control-v1')
PINS = {
    'collector.py': {'bytes': 20431, 'sha256': 'e00c715a41bbf3a75c283ed45664e8e9436437edc49238bb5010109577baa694', 'git_blob': 'ab75b51bf5a297b01504f34cd207fd5845ac5979'},
    'POSTFORMAT_HANDOFF_REQUEST.json': {'bytes': 20972, 'sha256': 'ffa7132a6bfc6db19e0cd8d067caa4d5cdca516b4d146d5e1a07aac2ac98da39', 'git_blob': '3480e1788552c5613ddb996459b0df070247327e'},
    'CAPTURE_PATHS.txt': {'bytes': 4496, 'sha256': 'e54fd7d8c47e9fac104598c4e5ed194982d4f44f75bf7dbadb26f12f9123ff2f', 'git_blob': '66a19f69967e4eb2a48488f27110ac69a2f1c8b4'},
    'V5_NORMAL_SUPERVISOR.original.json': {'bytes': 956, 'sha256': 'c313aece99eb8d3d7eb95c9d4997b81808c8404062371ab3dc52abb9badcd675', 'git_blob': '2bb8699bae213bd97926beb6589df08e7813c79a'},
    'APPROVED_CONFIG.json': {'bytes': 4304, 'sha256': '56dcf54467f4706c58e0c46bca97cfeda98b7bceffd0d05600ea50a9278e8c68', 'git_blob': 'f774519bd146ca59e2533c72e54c7a899d19c525'},
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
    check(all(isinstance(pin, dict) for pin in PINS.values()), 'HOLD: final approved config pin absent')
    raw_input = sys.stdin.buffer.read(1048577)
    check(len(raw_input) <= 1048576, 'bounded exact input')
    packet = json.loads(raw_input)
    check(set(packet) == {'format', 'files'} and packet['format'] == 'hepta-postformat-readonly-bootstrap-v1', 'exact bootstrap schema')
    check(isinstance(packet['files'], dict) and set(packet['files']) == set(PINS), 'exact five input files')
    files = {}
    for name, pin in PINS.items():
        encoded = packet['files'][name]
        check(isinstance(encoded, str), 'base64 input required')
        raw = base64.b64decode(encoded, validate=True)
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
    retain('STAGING_READBACK.json', (json.dumps({'format': 'hepta-postformat-readonly-bootstrap-readback-v1',
           'files': rows, 'source_writes': False, 'qualification': False}, sort_keys=True, indent=2) + '\n').encode())
    directory_fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({'event': 'fixed_postformat_readonly_bootstrap_verified', 'control': str(BASE),
                      'source_writes': False, 'qualification': False}), flush=True)
    os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(BASE / 'collector.py'),
             '--config', str(BASE / 'APPROVED_CONFIG.json'), '--config-sha256', PINS['APPROVED_CONFIG.json']['sha256']])
except BaseException as error:
    if created:
        try:
            retain('BOOTSTRAP_FAILURE.json', (json.dumps({'status': 'bootstrap_failed', 'error': repr(error),
                   'traceback': traceback.format_exc(), 'source_writes': False,
                   'partial_records_preserved': True}, sort_keys=True, indent=2) + '\n').encode())
        except BaseException:
            pass
    raise
