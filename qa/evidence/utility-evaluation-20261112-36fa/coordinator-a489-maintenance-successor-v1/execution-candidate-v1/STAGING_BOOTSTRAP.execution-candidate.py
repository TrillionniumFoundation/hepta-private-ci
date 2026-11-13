import base64, gzip, hashlib, io, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1')
PINS = {'driver-maintenance.py': {'bytes': 68520, 'sha256': '2e8501f584a6905a07124f04bb623c2674c1ec77299b89fbc76ef06610c589ed', 'git_blob': '59461030d4160f7ad6a978df5a7b6aaeb33fb2a6'}, 'APPROVED_MAINTENANCE_CONFIG.json': {'bytes': 13693, 'sha256': '3ab98f7c35ce030439773f2035b7d6e4b8f9c4b11b3f6e8f93b431ea369286d7', 'git_blob': '7bddb6c423afbe739bc36a7df2516730911a9337'}, 'inventory-driver.original.py': {'bytes': 22946, 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2', 'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}, 'MAINTENANCE_STARTED.original.json': {'bytes': 1154, 'sha256': 'f9372b818186526929ae25be698d108a4fee17d6612a18f36b8e950172c02ce1', 'git_blob': '69a3d38ff1cf800813f1fbf1f30bca224157f223'}, 'MATERIALIZATION_SUPERVISOR.original.json': {'bytes': 952, 'sha256': 'fd1140f7bdc02bcc7ea475a15542bd64cfb0d2f23d78dd0708525b49ad214d30', 'git_blob': '2a11b4b9e2baa380c247b6a728f90edfbcdcd644'}, 'V8_RESTORATION_SUPERVISOR.original.json': {'bytes': 950, 'sha256': '3fc77b2332259fea7142abbc4542ea6a77144cb7f75541b12b3483300e6c4f5d', 'git_blob': 'b5a9b8d0c8e5f9372eac59e3720ba90c42997579'}}

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
    check(set(packet) == {'format', 'files'} and packet['format'] == 'hepta-original-maintenance-control-staging-v1', 'exact bootstrap schema')
    check(isinstance(packet['files'], dict) and set(packet['files']) == set(PINS), 'exact six input files')
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
    retain('STAGING_READBACK.json', (json.dumps({'format': 'hepta-original-maintenance-control-staging-readback-v1',
           'files': rows, 'source_writes_during_staging': False, 'qualification': False}, sort_keys=True, indent=2) + '\n').encode())
    directory_fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({'event': 'fixed_maintenance_controls_staged_only', 'control': str(BASE),
                      'source_writes_during_staging': False, 'qualification': False}), flush=True)
    # Staging ends here. The separately reviewed original EX launcher is the only maintenance entry.
except BaseException as error:
    if created:
        try:
            retain('BOOTSTRAP_FAILURE.json', (json.dumps({'status': 'bootstrap_failed', 'error': repr(error),
                   'traceback': traceback.format_exc(), 'source_writes_during_staging': False,
                   'partial_records_preserved': True}, sort_keys=True, indent=2) + '\n').encode())
        except BaseException:
            pass
    raise
