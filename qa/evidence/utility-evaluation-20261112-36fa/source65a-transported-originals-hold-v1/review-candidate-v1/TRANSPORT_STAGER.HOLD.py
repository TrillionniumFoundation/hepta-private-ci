import base64, gzip, hashlib, io, json, os, pathlib, stat, sys, traceback

BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1')
ORIGINALS = BASE / "originals"
MANIFEST_PIN = {'bytes': 42163,
 'git_blob': '5d2e19cadd569f9dd37f0f87997b115d7ed3ef2a',
 'sha256': '9a7076714a08a5d18094741236f4d5609946f4367d6532150a2d0e9d6c692117'}
HISTORICAL_GUARD_PIN = {'bytes': 70306,
 'git_blob': '917f5b669ce5e4b926c7131a42423a0f069e46a4',
 'sha256': '503aaa202bd40ea54526e11b2e299630b7b888e5afe14a3ce5bfb8a3c1c0f556'}
PACKET_PIN = {'bytes': 10637954,
 'git_blob': '3282998b8de39cc0bcd2c44d40dfd5f9c5b1d57f',
 'sha256': 'da51b174555e0396a524f5f7da2e08e9849039f614efd0e5c7998b11a5fc6cbb'}
GZIP_PIN = {'bytes': 4994854,
 'git_blob': '0f8ff1e10bfbe418c11ff9f3f6844b02817c98b6',
 'sha256': '0fd09793b264476ac6ffda53fa89e38c28e973af32758ce7e2e0932f63275794'}
PART_INPUTS = [{'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-001',
  'pin': {'bytes': 307200,
          'git_blob': '31ab8fbbcd7cc205a6cd1de87d13aecc3b5a4e4e',
          'sha256': '6b86b0391ad498a0a33819ccf3d1f7df85086f7e8c9ee1e7adfbd274e7b0d845'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-002',
  'pin': {'bytes': 307200,
          'git_blob': 'f4b6cfcffb988b79d20e2cb2cdfae9011291e69d',
          'sha256': 'c4380979846fdd7dcbffedc2b31d77afca0ad421ad4e56e5b7482255dc4c25dc'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-003',
  'pin': {'bytes': 307200,
          'git_blob': 'bebb09eefd45b58dce8e8ee5733cfa7b72f4b867',
          'sha256': 'cb4c9818bf745863633d8facec323ad17ab9a79a5174bbc803206d66cb27e088'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-004',
  'pin': {'bytes': 307200,
          'git_blob': '9038f83a3d3749c13eb103d73709ba94627d826f',
          'sha256': 'b9c1c04f9729389996cf2ea77481823b9a0c13b55fc64a280139835fdee6fce1'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-005',
  'pin': {'bytes': 307200,
          'git_blob': '117500db05eb47a4ed5fa15348c2badaf90e8eb9',
          'sha256': '57de91373607f18e1bb495835784555a8c20fed3c35c18568d2f28f25563db6d'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-006',
  'pin': {'bytes': 307200,
          'git_blob': '2bd9985ea771c0a4820461f928019545d5f432e8',
          'sha256': '2c0b8661579fdfc073c934cb6536ac975f0979cf20bbaf6673c8968e4ed73093'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-007',
  'pin': {'bytes': 307200,
          'git_blob': '53b7395b2c06fe97d530300551407dcf93d64a9d',
          'sha256': 'd591844926bf2b70a1c4b1687646e58fed36e5e48e02feb9739fee8306f87ad1'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-008',
  'pin': {'bytes': 307200,
          'git_blob': 'da75e3a2f3f8734a6f75294a94d22da86f851d33',
          'sha256': 'd31c9f29880e7b3f4661a32a2d075252a29e9419940aee6d60690107b2e57ff1'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-009',
  'pin': {'bytes': 307200,
          'git_blob': 'cddcaabf900a5914be150d4932e04a367722ee79',
          'sha256': 'f86dc62e47e9f24bbd9a06cf17eb624a64cce23eca2d89645fd894eba4d44a44'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-010',
  'pin': {'bytes': 307200,
          'git_blob': 'e17216d2dcc28bd08d5290ef1dc3652f685cbb2b',
          'sha256': '3dfa4e0a1a42e0d517e1deed0471b63ab9580dd628d84af1b892b2366215595a'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-011',
  'pin': {'bytes': 307200,
          'git_blob': '021f4f922769f4ed583608695e1ebeaf2e42e5af',
          'sha256': '55db7199ca7b9d776ac22f5546ce9a8c791c639a9a53eeb0ac9d7dc6ee290248'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-012',
  'pin': {'bytes': 307200,
          'git_blob': 'db8238ca9f3a20f7782b4cbe471373f26a60bf1b',
          'sha256': 'ec2b2887b33fe891fdb18596724ca3e6c8899b2e30159021bea5f2afa4df1d72'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-013',
  'pin': {'bytes': 307200,
          'git_blob': 'b24d04d8212983127a63401c05e6937ecdc6cd00',
          'sha256': 'f7c316582236168bbc1ff6fb14c04d4090d0259e103bc51dbf49256bf73e1bcf'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-014',
  'pin': {'bytes': 307200,
          'git_blob': '9e365c121528367edf62cad17251117900cd81a5',
          'sha256': 'e46da201c7353d917a18314e34fcac53ecf20d509ea095fe432d9a36eaf2f1ad'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-015',
  'pin': {'bytes': 307200,
          'git_blob': '355e5c9355e63c7ea23e7ffcd36a424f4dcb810f',
          'sha256': '3059a5c2580412437680096e6068a835e381a0c94e039621e12b6afefd9c5c0f'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-016',
  'pin': {'bytes': 307200,
          'git_blob': '101e78c002ed67a46f597d5cee48c92bb05002bd',
          'sha256': '42dfe642346ff861f9cbb6c3269ae841821dfc8c795f67243444da53e3115dd8'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-017',
  'pin': {'bytes': 79654,
          'git_blob': 'aadf21d52a68d116c3c9d022c1b08f7ef827db04',
          'sha256': '2073b0f1f10f06d0b884ac2ab25aad6f0b200c904be1585bc8b38f537bac51d8'}}]
ORIGINAL_NAMES = ['canonical.supervisor.original',
 'runtime.supervisor.original',
 'canonical.config.original',
 'canonical.packet.original',
 'final_format.supervisor.original',
 'canonical.driver.original',
 'canonical.artifacts.original',
 'canonical.commands.original',
 'canonical.metadata_delta.original',
 'canonical.metadata_before_gzip.original',
 'canonical.metadata_final_gzip.original',
 'canonical.git_state_final.original',
 'canonical.index_delta_gzip.original',
 'canonical.index_audit_gzip.original',
 'canonical.index_raw_gzip.original',
 'canonical.inputs.original',
 'canonical.progress.original',
 'canonical.result.original',
 'final_format.config.original',
 'maintenance.supervisor.original',
 'final_format.driver.original',
 'final_format.artifacts.original',
 'final_format.inputs.original',
 'final_format.result.original',
 'final_format.metadata_after_gzip.original',
 'final_format.metadata_before_gzip.original',
 'final_format.git_state_final.original',
 'final_format.inventory_final_gzip.original',
 'final_format.empty_transition_gzip.original',
 'materialization.config.original',
 'materialization.packet.original',
 'materialization.driver.original',
 'materialization.artifacts.original',
 'materialization.commands.original',
 'materialization.inputs.original',
 'materialization.mutations.original',
 'materialization.result.original',
 'materialization.metadata_final_gzip.original',
 'maintenance.config.original',
 'materialization.supervisor.original',
 'archive.supervisor.original',
 'maintenance.driver.original',
 'maintenance.artifacts.original',
 'maintenance.inputs.original',
 'maintenance.result.original',
 'maintenance.metadata_after_gzip.original',
 'maintenance.metadata_before_gzip.original',
 'maintenance.git_state_before.original',
 'maintenance.git_state_final.original',
 'runtime.environment_ready.original',
 'runtime.result.original',
 'archive.readback.original',
 'archive.artifacts.original',
 'archive.result.original',
 'historical_environment.started.original']

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
