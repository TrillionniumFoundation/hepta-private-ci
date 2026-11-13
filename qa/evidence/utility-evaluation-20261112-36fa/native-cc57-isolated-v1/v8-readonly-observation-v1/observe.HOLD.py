"""One bounded read-only observation of the two fixed original V8 material paths."""
import datetime, errno, hashlib, json, os, pathlib, signal, stat, sys, traceback
EXPECTED_INPUTS = [{"role":"approved_runtime_configuration","path":"/home/qian-qi/hepta-utility-36fa-evidence/final-native-cc57-isolated-v1/APPROVED_QUALIFICATION_INPUT.json","pin":{"bytes":11785,"sha256":"ffb59de9f19c3ec9c45ec4f750ee33220dcb74df4d35a07a0ef7b1a2be446b6f","git_blob":"1666e5df58b33f1786287ba94d1d74b79442f8d6"}},{"role":"original_failed_result","path":"/home/qian-qi/hepta-utility-36fa-evidence/final-native-cc57-isolated-v1/native-records/RESULT.json","pin":{"bytes":1003,"sha256":"3ff0675a3fb0dca9c6107b4982c1cb26f34007f5a3d4f62c46cd1a660428a50d","git_blob":"b6a785c0194c2f65054a26e5815042010a22dad8"}},{"role":"original_environment_before_override","path":"/home/qian-qi/hepta-utility-36fa-evidence/final-native-cc57-isolated-v1/native-records/admission/historical-runtime/FORMATTER_ENVIRONMENT.before-override.json","pin":{"bytes":1382,"sha256":"eb8fe090db31cc6c8a3422e8159bce58e1259072fcd5c5822d975b53005976b7","git_blob":"1dfdf2450ebcde903eb5cf8f6cbe50ad98f4193d"}}]
EXPECTED_V8 = {"RUSTY_V8_ARCHIVE":{"bytes":29366352,"mode":384,"path":"/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz","resolved":"/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz","sha256":"a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583"},"RUSTY_V8_SRC_BINDING_PATH":{"bytes":39884,"mode":384,"path":"/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs","resolved":"/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs","sha256":"7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"}}
PARENTS = ['/data', '/data/hepta-utility-36fa-runtime-materials-86dd-v1', '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox']

result = {
    'format': 'hepta-isolated-native-v8-readonly-observation-v1',
    'qualification': False, 'source_writes': False, 'dependency_writes': False,
    'environment_changes': False, 'commands_or_child_processes': [],
    'original_native_job_id': '1a1d2e908ac-392-5a',
    'prior_failure_reclassified': False, 'original_behavioral_tests_started': False,
    'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scope': 'Only three pinned completed-job inputs and five fixed external paths. No process environ, directory enumeration, Git, Cargo, installation, network, or source read/write.'
}
def check(value, why):
    if not value:
        raise ValueError(why)
def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
def stamp(s):
    return {k: getattr(s, k) for k in ('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')}
def checked_original(row):
    path = pathlib.Path(row['path'])
    first = path.lstat()
    check(stat.S_ISREG(first.st_mode) and first.st_uid == os.getuid() and first.st_nlink == 1,
          'pinned completed-job input must be owned regular single-link')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        inside = os.fstat(f.fileno())
        raw = f.read(row['pin']['bytes'] + 1)
        last = os.fstat(f.fileno())
    outside = path.lstat()
    check(stamp(first) == stamp(inside) == stamp(last) == stamp(outside),
          'completed-job original changed while reading')
    check(identity(raw) == row['pin'], 'completed-job exact original bytes')
    return json.loads(raw), {'role': row['role'], 'path': str(path),
                            'identity': identity(raw), 'stable_stat': stamp(outside)}
def observe(path):
    row = {'path': path}
    try:
        s = os.lstat(path)
        row['lstat'] = stamp(s)
        row['kind'] = ('regular' if stat.S_ISREG(s.st_mode) else
                       'directory' if stat.S_ISDIR(s.st_mode) else
                       'symlink' if stat.S_ISLNK(s.st_mode) else 'other')
        row['exists_as_lstat'] = True
        if stat.S_ISLNK(s.st_mode):
            target = os.readlink(path)
            check(len(os.fsencode(target)) <= 4096, 'bounded symlink observation')
            row['link_text'] = target
        # This is metadata only; no content is followed through an unknown link.
        try:
            followed = os.stat(path)
            row['stat'] = stamp(followed)
            row['current_original_is_file_predicate'] = stat.S_ISREG(followed.st_mode)
        except OSError as error:
            row['stat_error'] = {'errno': error.errno, 'type': type(error).__name__,
                                 'message': str(error)}
            row['current_original_is_file_predicate'] = None
    except OSError as error:
        row['exists_as_lstat'] = False if error.errno == errno.ENOENT else None
        row['lstat_error'] = {'errno': error.errno, 'type': type(error).__name__,
                              'message': str(error)}
    return row
def expire(signum, frame):
    raise TimeoutError('original 45-second read-only observation window ended')
status = 1
signal.signal(signal.SIGALRM, expire)
signal.setitimer(signal.ITIMER_REAL, 45)
try:
    check(os.getuid() == 1000, 'fixed actual desktop operator')
    actual_code = sys.orig_argv[sys.orig_argv.index('-c') + 1].encode()
    result['actual_script'] = identity(actual_code)
    inputs = {}
    result['original_inputs'] = []
    for row in EXPECTED_INPUTS:
        value, observation = checked_original(row)
        inputs[row['role']] = value
        result['original_inputs'].append(observation)
    cfg = inputs['approved_runtime_configuration']
    failed = inputs['original_failed_result']
    env = inputs['original_environment_before_override']
    check(failed['status'] == 'failed' and failed['behavioral_tests_started'] is False
          and failed['stages'] == []
          and failed['error'] == 'ValueError: RUSTY_V8_ARCHIVE actual existing file required',
          'bind only the observed completed native precondition failure')
    check(cfg['runtime_guard']['v8_files'] == EXPECTED_V8, 'same approved V8 pair')
    check(env['approved_explicit_environment'] == cfg['runtime_guard']['environment'],
          'actual retained intended environment equals exact approved environment')
    for name, expected in EXPECTED_V8.items():
        check(cfg['runtime_guard']['environment'][name] == expected['path']
              and pathlib.Path(expected['path']).is_absolute(), 'fixed absolute V8 material path')
    result['original_environment_evidence'] = {
        'approved_explicit_environment': env['approved_explicit_environment'],
        'inherited_source_environment': env['inherited_source_environment'],
        'formatter_environment_before_override': env['formatter_environment'],
        'scope': 'Retained evidence of the completed job. This observer does not reconstruct or sample that terminated process environment.'
    }
    before = [observe(p) for p in PARENTS]
    result['parent_observations_before'] = before
    real_parents = all(row.get('kind') == 'directory' for row in before)
    result['real_fixed_parent_directories'] = real_parents
    result['material_observations'] = []
    for name, expected in EXPECTED_V8.items():
        item = observe(expected['path'])
        item['name'] = name
        item['expected_original'] = expected
        item['full_bytes_read'] = False
        if real_parents and item.get('kind') == 'regular':
            first = item['lstat']
            if first['st_size'] <= expected['bytes']:
                fd = os.open(expected['path'], os.O_RDONLY | os.O_NOFOLLOW)
                sha256 = hashlib.sha256()
                sha1 = hashlib.sha1(b'blob ' + str(first['st_size']).encode() + b'\0')
                total = 0
                with os.fdopen(fd, 'rb') as f:
                    inside = os.fstat(f.fileno())
                    check(stamp(inside) == first, 'stable opened fixed material')
                    while True:
                        part = f.read(min(1048576, expected['bytes'] + 1 - total))
                        if not part:
                            break
                        total += len(part); sha256.update(part); sha1.update(part)
                        check(total <= expected['bytes'], 'bounded fixed material body')
                    last = os.fstat(f.fileno())
                outside = os.lstat(expected['path'])
                check(first == stamp(inside) == stamp(last) == stamp(outside),
                      'fixed material changed during full read')
                item['full_bytes_read'] = True
                item['identity'] = {'bytes': total, 'sha256': sha256.hexdigest(), 'git_blob': sha1.hexdigest()}
                item['matches_original_bytes_mode'] = (
                    total == expected['bytes'] and sha256.hexdigest() == expected['sha256']
                    and stat.S_IMODE(outside.st_mode) == expected['mode'])
            else:
                item['body_not_read_reason'] = 'actual size exceeds the exact bounded original role'
        else:
            item['body_not_read_reason'] = 'not a regular leaf under the three real fixed parent directories'
        result['material_observations'].append(item)
    after = [observe(p) for p in PARENTS]
    result['parent_observations_after'] = after
    check(before == after, 'fixed parent metadata changed in observation window')
    result['leaf_metadata_after'] = [observe(x['path']) for x in EXPECTED_V8.values()]
    for initial, final in zip(result['material_observations'], result['leaf_metadata_after']):
        for key in ('path','kind','lstat','stat','link_text','lstat_error','stat_error','exists_as_lstat'):
            check(initial.get(key) == final.get(key), 'fixed leaf metadata changed in observation window')
    result['inputs_final'] = []
    for row in EXPECTED_INPUTS:
        _, observation = checked_original(row)
        result['inputs_final'].append(observation)
    check(result['original_inputs'] == result['inputs_final'], 'completed-job inputs unchanged')
    result['status'] = 'OBSERVED_FIXED_MATERIAL_STATE_ONLY'
    result['observation_complete'] = True
    status = 0
except BaseException as error:
    result['status'] = 'READONLY_OBSERVATION_FAILED_OR_INCOMPLETE'
    result['error'] = type(error).__name__ + ': ' + str(error)
    result['traceback'] = traceback.format_exc()
    result['observation_complete'] = False
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
    result['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    raw = (json.dumps(result, sort_keys=True) + '\n').encode()
    if len(raw) > 65536:
        raise RuntimeError('bounded observation output exceeded; original exception is not rewritten as success')
    sys.stdout.buffer.write(raw); sys.stdout.buffer.flush()
raise SystemExit(status)
