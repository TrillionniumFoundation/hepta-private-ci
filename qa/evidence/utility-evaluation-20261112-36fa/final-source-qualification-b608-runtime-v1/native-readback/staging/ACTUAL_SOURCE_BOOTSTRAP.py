import base64, hashlib, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1')
PINS = {'qualification-admission.py': {'bytes': 87654, 'sha256': '453de56b668a8361c710be67f058b5a37c8e39be106a28c5bc803783906b6ca2', 'git_blob': 'c77e3be6230d3267c08333be582f69f23c016fb9'}, 'source-gates-wrapper.py': {'bytes': 5610, 'sha256': 'f798be087f04685a30bd66ad04aefa86c2aceb4bf1644ac909b411ab7f726457', 'git_blob': '8607fa4bf00fc8cf535849de04d1eb6ff29429b3'}, 'native-wrapper.py': {'bytes': 13360, 'sha256': 'fc5b2c43fdf01288396b03369647a5c886108ec3e8eec3da2e2fe5afadb21d5f', 'git_blob': 'de3e9dc5e7eb30f47929f9e1ba9f460035a94fae'}, 'native-driver.original.py': {'bytes': 14986, 'sha256': '3c318e8d028afd0039325a531215c4add411dc5a1a0ec5016fd3448dfbf2d231', 'git_blob': 'b92ddded4fce78aeb076d022471c62bf81ce2e4f'}, 'PLAN.original.json': {'bytes': 32246, 'sha256': '2a2df598aa5b2673b55465c3978cb6c51a22326fde9878d97f39bf984e905619', 'git_blob': '3aefbc71d69d8014eed9e5a18269bbcc866a7583'}, 'APPROVED_QUALIFICATION_INPUT.json': {'bytes': 24155, 'sha256': 'ac5663c711d2d47669c334052e09151d2fbda34776ff41b0b8727804d322a840', 'git_blob': '720abbdfa96bca8c7e6aaf633a800693960d80db'}, 'SOURCE_GATES_CONFIG.json': {'bytes': 831, 'sha256': 'f08beb0e1a0c87117bd7a091ec3c7b4390285cf47a291c0d7569fd0f1d2e197c', 'git_blob': 'b97682c5a95bb7f09241e54f0b3d13bf7fa791a4'}, 'CANONICAL_SUPERVISOR.original.json': {'bytes': 950, 'sha256': 'da2b842525ca95a78f10292fc9db13c30466a2e498b717a51a7ebe3f2714c990', 'git_blob': '2deafbe4bfc7ad2c84d9e6315c12aaa6493adab2'}}

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
    check(all(isinstance(pin, dict) for pin in PINS.values()), 'HOLD: final reviewed qualification input absent')
    raw_input = sys.stdin.buffer.read(1048577)
    check(len(raw_input) <= 1048576, 'bounded exact input')
    packet = json.loads(raw_input)
    check(set(packet) == {'format', 'files'} and packet['format'] == 'hepta-final-source-qualification-bootstrap-v1', 'exact bootstrap schema')
    check(isinstance(packet['files'], dict) and set(packet['files']) == set(PINS), 'exact eight input files')
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
    rows = [retain('ACTUAL_SOURCE_BOOTSTRAP.py', code),
            retain('ACTUAL_SOURCE_BOOTSTRAP_ARGV.json', (json.dumps(argv, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()),
            retain('ACTUAL_SOURCE_BOOTSTRAP_PAYLOAD.json', raw_input)]
    rows += [retain(name, raw) for name, raw in files.items()]
    retain('STAGING_READBACK.json', (json.dumps({'format': 'hepta-final-source-qualification-bootstrap-readback-v1',
           'files': rows, 'source_writes_during_staging': False, 'qualification': False}, sort_keys=True, indent=2) + '\n').encode())
    directory_fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({'event': 'fixed_source_qualification_bootstrap_verified', 'control': str(BASE),
                      'source_writes_during_staging': False, 'qualification': False}), flush=True)
except BaseException as error:
    if created:
        try:
            retain('BOOTSTRAP_FAILURE.json', (json.dumps({'status': 'bootstrap_failed', 'error': repr(error),
                   'traceback': traceback.format_exc(), 'source_writes_during_staging': False,
                   'partial_records_preserved': True}, sort_keys=True, indent=2) + '\n').encode())
        except BaseException:
            pass
    raise

# Main failure is owned by the unchanged original wrapper, not the stager.
qualification_input = json.loads(files['APPROVED_QUALIFICATION_INPUT.json'])
source_wrapper_path = BASE / 'source-gates-wrapper.py'
source_namespace = {'__name__': '__main__', '__file__': str(source_wrapper_path),
                    'INPUT': qualification_input}
exec(compile(files['source-gates-wrapper.py'], str(source_wrapper_path), 'exec'), source_namespace)
