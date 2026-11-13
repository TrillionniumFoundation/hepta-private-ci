import base64, hashlib, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/final-native-cc57-isolated-v1")
PINS = {"qualification-admission.py":{"bytes":26963,"sha256":"d44eeb0fd87e82d80c16407f75d65820c63d0d00c928f367fb02dce934dda52d","git_blob":"23d412ed67927a6cbfa5f521884e891afc93eb6f"},"native-wrapper.py":{"bytes":13360,"sha256":"fc5b2c43fdf01288396b03369647a5c886108ec3e8eec3da2e2fe5afadb21d5f","git_blob":"de3e9dc5e7eb30f47929f9e1ba9f460035a94fae"},"native-driver.original.py":{"bytes":14986,"sha256":"3c318e8d028afd0039325a531215c4add411dc5a1a0ec5016fd3448dfbf2d231","git_blob":"b92ddded4fce78aeb076d022471c62bf81ce2e4f"},"PLAN.original.json":{"bytes":32246,"sha256":"2a2df598aa5b2673b55465c3978cb6c51a22326fde9878d97f39bf984e905619","git_blob":"3aefbc71d69d8014eed9e5a18269bbcc866a7583"},"APPROVED_QUALIFICATION_INPUT.json":{"bytes":11785,"sha256":"ffb59de9f19c3ec9c45ec4f750ee33220dcb74df4d35a07a0ef7b1a2be446b6f","git_blob":"1666e5df58b33f1786287ba94d1d74b79442f8d6"},"ISOLATED_MATERIALIZATION_NORMAL.original.json":{"bytes":951,"sha256":"a50934e8bbc5aa4587f478e954fee193de9339d63d0294e08ed7dc8f95e090aa","git_blob":"c507335b611474857eff53b738071a7a3f27dc99"}}
SOURCE_SUCCESS = {
    'job_id': '1a1d23c92f3-2564-1cb4',
    'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/RESULT.json',
    'result': {'bytes': 692, 'sha256': '6a18c716d85035f6dfbed2a73df36244694bceced63450bad4a19bce3ac3615c', 'git_blob': 'd52e6d9a85fed924ea3b29fad1d22347d5732a34'},
    'original_run_result_path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/ORIGINAL_RUN_RESULT.json',
    'original_run_result': {'bytes': 5082, 'sha256': '43fed7f7ed12a8dde409891132be0b876d7594f85072f441a4c5dfc8011f9083', 'git_blob': '0f5f9a8332255d4c7341b58207725254e4c34c76'},
    'supervisor': {'bytes': 954, 'sha256': 'a119569c3460e6e5fcd434c4e1144864bbf0bed38811cb77e3a8563307d88109', 'git_blob': '851a18c3063d40c1208b198d02bc875b052a83d7'},
}

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

def read_fixed(path, pin):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        check(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1,
              'owned regular pinned input required')
        raw = stream.read(pin['bytes'] + 1)
        after = os.fstat(stream.fileno())
    outside = pathlib.Path(path).lstat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_nlink,
                       s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    check(stamp(before) == stamp(after) == stamp(outside) and identity(raw) == pin,
          'actual stable exact input: ' + str(path))
    return raw

staging_started = False
try:
    check(os.getuid() == 1000, 'fixed desktop account')
    check(all(isinstance(SOURCE_SUCCESS[k], dict) for k in ('result', 'original_run_result', 'supervisor')),
          'HOLD: complete actual source gates and Root exact launch review are still required')
    real_parents()
    raw_payload = sys.stdin.buffer.read(1048577)
    check(len(raw_payload) <= 1048576, 'bounded exact native proof and input payload')
    payload = json.loads(raw_payload)
    check(set(payload) == {'format', 'files', 'source_supervisor_base64'}
          and payload['format'] == 'hepta-isolated-native-staging-and-source-prerequisite-v1',
          'exact isolated native proof schema')
    check(isinstance(payload['files'], list) and len(payload['files']) == len(PINS),
          'exact reviewed isolated input count')
    files = {}
    for item in payload['files']:
        check(isinstance(item, dict) and set(item) == {'name', 'base64'}
              and item['name'] in PINS and item['name'] not in files,
              'exact unique reviewed isolated input name')
        raw = base64.b64decode(item['base64'], validate=True)
        check(identity(raw) == PINS[item['name']], 'exact isolated input bytes before any write')
        files[item['name']] = raw
    check(set(files) == set(PINS), 'complete six isolated input files')
    normal = base64.b64decode(payload['source_supervisor_base64'], validate=True)
    check(identity(normal) == SOURCE_SUCCESS['supervisor'], 'actual original source supervisor before any write')
    BASE.mkdir(mode=0o700)
    staging_started = True
    s = BASE.lstat()
    check(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode)
          and s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700,
          'new private reviewed isolated qualification control')
    input_rows = [retain(name, files[name]) for name in PINS]
    files = {name: read_fixed(BASE / name, expected) for name, expected in PINS.items()}
    retain('ISOLATED_NATIVE_INPUTS_READBACK.json', (json.dumps({
        'files': input_rows, 'native_wrapper_started': False,
        'scope': 'Create-only control staging; historical source proofs keep their original absolute paths.'
    }, indent=2, sort_keys=True) + '\n').encode())
    check(identity(normal) == SOURCE_SUCCESS['supervisor'], 'actual original source supervisor pin')
    envelope = json.loads(normal)
    check(envelope.get('isError') is False and len(envelope.get('content', [])) == 1
          and envelope['content'][0].get('type') == 'text', 'actual normal source SDK')
    terminal = json.loads(envelope['content'][0]['text'])
    check(terminal.get('job_id') == SOURCE_SUCCESS['job_id'] and terminal.get('state') == 'succeeded'
          and terminal.get('exit_code') == 0 and terminal.get('timed_out') is False
          and terminal.get('cancelled') is False and terminal.get('automatic_retry') is False
          and terminal.get('output_complete') is True and terminal.get('output_durable') is True
          and terminal.get('terminal_publication_confirmed') is True
          and not any(terminal.get('log_truncated', {}).values()), 'complete normal original source terminal')
    source_result_raw = read_fixed(SOURCE_SUCCESS['result_path'], SOURCE_SUCCESS['result'])
    original_raw = read_fixed(SOURCE_SUCCESS['original_run_result_path'], SOURCE_SUCCESS['original_run_result'])
    source_result = json.loads(source_result_raw)
    original = json.loads(original_raw)
    qualification_input = json.loads(files['APPROVED_QUALIFICATION_INPUT.json'])
    check(source_result.get('format') == 'hepta-final-source-gates-handoff-v1'
          and source_result.get('status') == 'passed'
          and source_result.get('source') == qualification_input['source']
          and source_result.get('tree') == qualification_input['tree']
          and source_result.get('driver_main_entered') is True
          and source_result.get('driver_returncode') == 0
          and source_result.get('original_run_status') == 'passed'
          and original.get('status') == 'passed', 'actual source pass; failed or unknown source is never rewritten')
    staging_started = True
    argv = sys.orig_argv
    actual_code = argv[argv.index('-c') + 1].encode('utf-8')
    rows = [retain('ACTUAL_NATIVE_BOOTSTRAP.py', actual_code),
            retain('ACTUAL_NATIVE_BOOTSTRAP_ARGV.json', (json.dumps(argv, indent=2, sort_keys=True) + '\n').encode()),
            retain('ACTUAL_NATIVE_BOOTSTRAP_PAYLOAD.json', raw_payload),
            retain('SOURCE_GATES_NORMAL.original.json', normal),
            retain('NATIVE_SOURCE_HANDOFF_RESULT.original.json', source_result_raw),
            retain('NATIVE_SOURCE_ORIGINAL_RUN_RESULT.original.json', original_raw)]
    retain('NATIVE_SOURCE_PREREQUISITE_READBACK.json', (json.dumps({
        'source_job_id': SOURCE_SUCCESS['job_id'], 'exact_prerequisite_pins': SOURCE_SUCCESS,
        'files': rows, 'qualification': False, 'native_wrapper_started': False,
        'scope': 'Root must review complete original per-gate and frozen-clone evidence before approving this exact launcher. This code adds no source rerun, alternate failure handling, or suite/budget change.'
    }, indent=2, sort_keys=True) + '\n').encode())
    directory_fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({'event': 'actual_source_prerequisite_verified_before_native_wrapper',
                      'source_job_id': SOURCE_SUCCESS['job_id'], 'qualification': False}), flush=True)
except BaseException as error:
    if staging_started:
        try:
            retain('NATIVE_BOOTSTRAP_FAILURE.json', (json.dumps({
                'status': 'native_bootstrap_failed', 'error': repr(error), 'traceback': traceback.format_exc(),
                'native_wrapper_started': False, 'old_source_result_unchanged': True,
                'partial_records_preserved': True
            }, indent=2, sort_keys=True) + '\n').encode())
        except BaseException:
            pass
    raise

# The original native wrapper owns all gate results and its own failure records.
# It is outside the bootstrap exception handler and is not rewritten or retried.
native_wrapper_path = BASE / 'native-wrapper.py'
namespace = {'__name__': '__main__', '__file__': str(native_wrapper_path), 'INPUT': qualification_input}
exec(compile(files['native-wrapper.py'], str(native_wrapper_path), 'exec'), namespace)
