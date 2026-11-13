import base64, gzip, hashlib, io, json, os, pathlib, stat, sys, traceback

# FROZEN_CONSTANTS

created = False

def check(value, message):
    if not value:
        raise RuntimeError(message)

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        check(key not in result, 'duplicate JSON key')
        result[key] = value
    return result

def parse(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates)

def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

def real_parents(path):
    path = pathlib.Path(path)
    check(path.is_absolute(), 'absolute fixed directory')
    current = pathlib.Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        info = current.lstat()
        check(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), 'real directory ancestry')

def read_part(spec):
    path = pathlib.Path(spec['path'])
    check(path.parent == BASE.parent and str(path) in {item['path'] for item in PART_INPUTS},
          'one frozen part path under the existing evidence parent')
    real_parents(path.parent)
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        first = os.fstat(stream.fileno())
        check(stat.S_ISREG(first.st_mode) and first.st_uid == 1000 and first.st_nlink == 1
              and stat.S_IMODE(first.st_mode) == 0o600 and first.st_size == spec['pin']['bytes']
              and first.st_size <= 307200, 'fixed owned single-link bounded part')
        raw = stream.read(spec['pin']['bytes'] + 1)
        last = os.fstat(stream.fileno())
    check(stamp(before) == stamp(first) == stamp(last) == stamp(path.lstat()),
          'whole part remained stable during no-follow read')
    check(identity(raw) == spec['pin'], 'whole compressed part identity')
    return raw

def decode_packet(compressed, manifest_raw):
    """Pure, bounded exact-byte decoder; never accepts caller-chosen paths."""
    check(identity(compressed) == GZIP_PIN, 'complete compressed packet identity')
    check(identity(manifest_raw) == MANIFEST_PIN, 'fixed complete closed manifest identity')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as stream:
        raw = stream.read(PACKET_PIN['bytes'] + 1)
    check(identity(raw) == PACKET_PIN, 'bounded complete decoded packet identity')
    manifest, packet = parse(manifest_raw), parse(raw)
    check(manifest['format'] == 'hepta-closed-transported-originals-manifest-v1'
          and manifest['control'] == str(BASE) and manifest['historical_original_count'] == 55,
          'one reviewed original-input transport manifest')
    check(set(packet) == {'format', 'manifest', 'files'}
          and packet['format'] == 'hepta-closed-transported-originals-packet-v1'
          and packet['manifest'] == MANIFEST_PIN, 'exact transport packet schema')
    rows = manifest['rows']
    check(len(rows) == 55 and len({row['role'] for row in rows}) == 55
          and len({row['original_path'] for row in rows}) == 55,
          'complete unique historical role closure')
    check(isinstance(packet['files'], list) and len(packet['files']) == 55
          and [entry['role'] for entry in packet['files']] == [row['role'] for row in rows],
          'exact ordered 55-role packet')
    result = {}
    for spec, entry in zip(rows, packet['files']):
        check(set(entry) == {'role', 'data_base64'} and isinstance(entry['data_base64'], str),
              'closed original-entry shape')
        check(spec['transport_path'] == str(ORIGINALS / (spec['role'] + '.original')),
              'one fixed new location for each historical role')
        check(len(entry['data_base64']) == 4 * ((spec['pin']['bytes'] + 2) // 3),
              'bounded exact encoded original length')
        body = base64.b64decode(entry['data_base64'], validate=True)
        check(identity(body) == spec['pin'], 'complete original bytes: ' + spec['role'])
        result[spec['role']] = body
    check(sum(len(raw) for raw in result.values()) == 7976106, 'complete closed original byte count')
    return manifest, result

def retain(directory, name, raw):
    check(directory in (BASE, ORIGINALS) and pathlib.Path(name).name == name,
          'one-level record in one of two fixed new directories')
    if directory == ORIGINALS:
        check(name in ORIGINAL_NAMES, 'only the frozen 55 transported originals')
    else:
        check(name in {'TRANSPORT_MANIFEST.json', 'historical-runtime-guard.py',
              'ACTUAL_TRANSPORT_BOOTSTRAP.py', 'ACTUAL_TRANSPORT_ARGV.json',
              'ACTUAL_TRANSPORT_PAYLOAD.json', 'STAGING_READBACK.json', 'STAGING_FAILURE.json'},
              'only fixed staging evidence/control names')
    path = directory / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        first = os.fstat(stream.fileno()); actual = stream.read(len(raw) + 1); last = os.fstat(stream.fileno())
    check(stamp(before) == stamp(first) == stamp(last) == stamp(path.lstat())
          and stat.S_ISREG(first.st_mode) and first.st_uid == 1000 and first.st_nlink == 1
          and stat.S_IMODE(first.st_mode) == 0o600 and actual == raw,
          'complete new file readback and ownership/stat stability')
    return {'path': str(path), **identity(actual)}

def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

try:
    check(os.getuid() == 1000, 'fixed desktop account')
    raw_input = sys.stdin.buffer.read(1048577)
    check(len(raw_input) <= 1048576, 'original bounded typed/stdin input')
    cfg = parse(raw_input)
    check(set(cfg) == {'format', 'status', 'root_execution_approved', 'manifest_base64', 'historical_guard_base64'}
          and cfg['format'] == 'hepta-closed-history-transport-staging-input-v1', 'exact staging input schema')
    check(cfg['status'] == 'ROOT_APPROVED_TO_STAGE_ONLY' and cfg['root_execution_approved'] is True,
          'HOLD: no exact engineering approval for historical transport staging')
    manifest_raw = base64.b64decode(cfg['manifest_base64'], validate=True)
    guard_raw = base64.b64decode(cfg['historical_guard_base64'], validate=True)
    check(identity(manifest_raw) == MANIFEST_PIN and identity(guard_raw) == HISTORICAL_GUARD_PIN,
          'two exact independent control inputs')
    real_parents(BASE.parent)
    check(BASE.parent.stat().st_uid == 1000, 'owned existing evidence parent')
    check(not os.path.lexists(BASE), 'existing transport control: retain and reconcile; never overwrite')
    compressed = b''.join(read_part(spec) for spec in PART_INPUTS)
    manifest, files = decode_packet(compressed, manifest_raw)
    os.mkdir(BASE, 0o700); created = True
    os.mkdir(ORIGINALS, 0o700)
    for directory in (BASE, ORIGINALS):
        info = directory.lstat()
        check(stat.S_ISDIR(info.st_mode) and info.st_uid == 1000
              and stat.S_IMODE(info.st_mode) == 0o700, 'new private owned transport directory')
    argv = sys.orig_argv
    code = argv[argv.index('-c') + 1].encode()
    rows = [retain(BASE, 'ACTUAL_TRANSPORT_BOOTSTRAP.py', code),
            retain(BASE, 'ACTUAL_TRANSPORT_ARGV.json', json_bytes(argv)),
            retain(BASE, 'ACTUAL_TRANSPORT_PAYLOAD.json', raw_input),
            retain(BASE, 'TRANSPORT_MANIFEST.json', manifest_raw),
            retain(BASE, 'historical-runtime-guard.py', guard_raw)]
    rows += [retain(ORIGINALS, row['role'] + '.original', files[row['role']]) for row in manifest['rows']]
    # Re-read every fixed compressed input after all writes; originals are read back by retain.
    check(b''.join(read_part(spec) for spec in PART_INPUTS) == compressed,
          'all fixed compressed inputs unchanged through staging')
    receipt = {'format': 'hepta-closed-history-transport-readback-v1', 'control': str(BASE),
               'historical_original_count': 55, 'manifest': MANIFEST_PIN, 'packet': PACKET_PIN,
               'compressed_packet': GZIP_PIN, 'part_inputs': PART_INPUTS, 'files': rows,
               'source_writes': False, 'old_path_writes': False, 'main_dispatched': False,
               'qualification': False, 'automatic_retry': False}
    retain(BASE, 'STAGING_READBACK.json', json_bytes(receipt))
    for directory in (ORIGINALS, BASE):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    print(json.dumps({'event': 'closed_history_transport_staging_complete', 'control': str(BASE),
                      'historical_original_count': 55, 'source_writes': False,
                      'main_dispatched': False, 'qualification': False}), flush=True)
except BaseException as error:
    if created:
        try:
            retain(BASE, 'STAGING_FAILURE.json', json_bytes({'status': 'staging_failed',
                   'error': repr(error), 'traceback': traceback.format_exc(), 'source_writes': False,
                   'old_path_writes': False, 'main_dispatched': False, 'qualification': False,
                   'partial_files_preserved': True, 'automatic_retry': False}))
        except BaseException:
            pass
    raise
