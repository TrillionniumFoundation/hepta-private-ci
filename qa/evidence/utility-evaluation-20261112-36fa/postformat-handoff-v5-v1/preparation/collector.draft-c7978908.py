#!/usr/bin/env python3
"""Read-only, separately approved capture of actual V5 formatted source.

No Cargo, formatter, source mutation, verifier verdict, or extractor execution.
The original complete inventory implementation remains the source observer.
"""
import argparse
import base64
import datetime
import fcntl
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import traceback


SOURCE = Path('/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1')
EVIDENCE = Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1')
RUN = EVIDENCE / 'run-v5'
LOCK = EVIDENCE / 'SOURCE_COORDINATION.lock'
OUTPUT = EVIDENCE / 'postformat-handoff-v5-v1'
HEAD = '9c4a11f61d30e9cc352bf44d56c98909d202a55d'
HEAD_TREE = 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'
PHYSICAL_TREE = '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
JOB = '1a1d16f37be-2564-1c4a'
CAPTURE_SECONDS = 300
RETENTION_SECONDS = 60
MAX_FILE_BYTES = 40_000_000
MAX_PACKET_BYTES = 64_000_000
INVENTORY_PIN = {'bytes': 5614211, 'sha256': '3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f',
                 'git_blob': '1563de8825fc183d345d10d03e68d79b2d9211ca'}
DRIVER_PIN = {'bytes': 22946, 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2',
              'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}
REQUEST_PIN = {'bytes': 20972, 'sha256': 'ffa7132a6bfc6db19e0cd8d067caa4d5cdca516b4d146d5e1a07aac2ac98da39',
               'git_blob': '3480e1788552c5613ddb996459b0df070247327e'}
PATHS_PIN = {'bytes': 4496, 'sha256': 'e54fd7d8c47e9fac104598c4e5ed194982d4f44f75bf7dbadb26f12f9123ff2f',
             'git_blob': '66a19f69967e4eb2a48488f27110ac69a2f1c8b4'}
LOCK_IDENTITY = {'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1}
ORIGINAL_NAMES = {
    'RESULT.json', 'fix.terminal.json', 'fmt.terminal.json', 'ARTIFACTS.json',
    'fix.execute_logged.original.json', 'fmt.execute_logged.original.json',
    'final.inventory.json.gz', 'final.postimages.json.gz',
    'final.postimages-summary.json', 'final.git-state.json',
}


def check(value, message):
    if not value:
        raise ValueError(message)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def jbytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def stamps(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_nlink,
            s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def read_regular(path, limit=MAX_FILE_BYTES):
    path = Path(path)
    check(path.is_absolute() and path.resolve() == path, 'absolute non-symlink path required: ' + str(path))
    a = path.lstat()
    check(stat.S_ISREG(a.st_mode) and a.st_size <= limit, 'bounded regular input: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as handle:
        b = os.fstat(handle.fileno())
        raw = handle.read(limit + 1)
        c = os.fstat(handle.fileno())
    d = path.lstat()
    check(len(raw) <= limit and stamps(a) == stamps(b) == stamps(c) == stamps(d),
          'file changed while reading: ' + str(path))
    return raw, d


def pinned(path, pin):
    raw, _ = read_regular(path)
    check(identity(raw) == {k: pin[k] for k in ('bytes', 'sha256', 'git_blob')}, 'input pin: ' + str(path))
    return raw


def put(name, raw):
    check(Path(name).name == name and name not in ('', '.', '..'), 'single-level output name')
    path = OUTPUT / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    check(read_regular(path, max(MAX_FILE_BYTES, len(raw)))[0] == raw, 'output exact readback')
    item = {'name': name, **identity(raw)}
    artifacts.append(item)
    return item


def compressed(name, raw):
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    meta = put(name, packed)
    meta['raw'] = identity(raw)
    meta['parts'] = []
    for offset in range(0, len(packed), 262144):
        chunk = packed[offset:offset + 262144]
        part = put(name + '.part-' + str(offset // 262144 + 1).zfill(3) + '.b64', base64.b64encode(chunk) + b'\n')
        meta['parts'].append({**part, 'decoded_offset': offset, 'decoded_bytes': len(chunk),
                              'decoded_sha256': hashlib.sha256(chunk).hexdigest()})
    return meta


def unpack(raw, pin):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as handle:
        result = handle.read(pin['bytes'] + 1)
        check(len(result) == pin['bytes'] and handle.read(1) == b'', 'bounded complete gzip')
    check(identity(result) == pin, 'decompressed exact original identity')
    return result


def decode_normal(raw):
    value = json.loads(raw)
    check(value.get('isError') is False and len(value['content']) == 1
          and value['content'][0]['type'] == 'text', 'original complete normal SDK')
    return json.loads(value['content'][0]['text'])


def git_metadata():
    root = SOURCE / '.git'
    check(root.is_dir() and root.resolve() == root, 'real source Git directory')
    rows = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs.sort(); files.sort()
        for name in dirs + files:
            path = Path(directory) / name
            before = path.lstat()
            row = {'path': path.relative_to(root).as_posix(), 'stat': list(stamps(before))}
            if stat.S_ISDIR(before.st_mode):
                row['kind'] = 'directory'
            elif stat.S_ISREG(before.st_mode):
                digest = hashlib.sha256()
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as handle:
                    opened = os.fstat(handle.fileno())
                    for chunk in iter(lambda: handle.read(1048576), b''):
                        digest.update(chunk)
                    closed = os.fstat(handle.fileno())
                check(stamps(before) == stamps(opened) == stamps(closed) == stamps(path.lstat()), 'Git file drift')
                row.update(kind='file', sha256=digest.hexdigest())
            else:
                raise ValueError('unsupported Git metadata entry')
            rows.append(row)
    return jbytes({'root': str(root), 'files': rows})


def expire(signum, frame):
    raise TimeoutError('separate read-only handoff observation budget exhausted')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    args = parser.parse_args()
    check(SOURCE.resolve() == SOURCE and SOURCE.is_dir(), 'actual fixed source root')
    check(EVIDENCE.resolve() == EVIDENCE and EVIDENCE.is_dir(), 'actual external evidence directory')
    check(not os.path.lexists(OUTPUT), 'existing capture: reconcile it, never overwrite or retry here')
    os.mkdir(OUTPUT, 0o700)
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'; sys.dont_write_bytecode = True
    signal.signal(signal.SIGALRM, expire)
    signal.alarm(CAPTURE_SECONDS)
    result = {'format': 'hepta-actual-postformat-readonly-handoff-v1', 'status': 'UNKNOWN',
              'started_at': now(), 'qualification': False, 'source_write_authorized': False,
              'extractor_executed': False, 'tests_dispatched': 0, 'source_changed': None,
              'capture_seconds': CAPTURE_SECONDS, 'retention_seconds': RETENTION_SECONDS}
    driver = before = before_git = lease_fd = None
    inputs = []
    capture_complete = False
    try:
        raw, _ = read_regular(args.config)
        check(identity(raw)['sha256'] == args.config_sha256, 'approved capture config transport hash')
        cfg = json.loads(raw)
        check(cfg['status'] == 'ROOT_APPROVED_READONLY_CAPTURE' and cfg['root_execution_approved'] is True,
              'HOLD capture is not executable')
        check(re.fullmatch('[0-9a-f]{40}', cfg['root_review_blob']) is not None, 'root review identity')
        check(cfg['driver_sha256'] == identity(read_regular(Path(__file__).resolve())[0])['sha256'], 'frozen collector')
        check(cfg['source_root'] == str(SOURCE) and cfg['record_root'] == str(RUN)
              and cfg['output_root'] == str(OUTPUT) and cfg['job_id'] == JOB, 'exact current identities')
        check(cfg['capture_seconds'] == CAPTURE_SECONDS and cfg['retention_seconds'] == RETENTION_SECONDS,
              'separate observation budgets')
        put('APPROVED_CAPTURE_CONFIG.original.json', raw)
        inputs.append((args.config, identity(raw)))
        request = json.loads(pinned(cfg['request_path'], REQUEST_PIN))
        paths_raw = pinned(cfg['paths_path'], PATHS_PIN)
        paths = paths_raw.decode().splitlines()
        group_paths = {x for g in request['actual_byte_capture']['groups'].values() for x in g['paths']}
        check(len(paths) == 73 and len(set(paths)) == 73 and set(paths) == group_paths, 'exact 73 capture paths')
        for path, pin in ((cfg['request_path'], REQUEST_PIN), (cfg['paths_path'], PATHS_PIN),
                          (cfg['inventory_driver_path'], DRIVER_PIN)):
            inputs.append((Path(path), pin))
        inventory_driver = pinned(cfg['inventory_driver_path'], DRIVER_PIN)
        put('INVENTORY_DRIVER.original.py', inventory_driver)
        put('CAPTURE_PATHS.original.txt', paths_raw)
        check(set(cfg['originals']) == ORIGINAL_NAMES, 'complete fixed original record set')
        original = {}
        for name, pin in cfg['originals'].items():
            path = RUN / name
            original[name] = pinned(path, pin)
            inputs.append((path, {k: pin[k] for k in ('bytes', 'sha256', 'git_blob')}))
            put('V5.' + name, original[name])
        normal_raw = pinned(cfg['normal_path'], cfg['normal_pin'])
        ex_raw = pinned(EVIDENCE / 'SOURCE_COORDINATION_EX_V5.json', cfg['exclusive_lease_pin'])
        inputs += [(Path(cfg['normal_path']), cfg['normal_pin']),
                   (EVIDENCE / 'SOURCE_COORDINATION_EX_V5.json', cfg['exclusive_lease_pin'])]
        put('NORMAL_SUPERVISOR.original.json', normal_raw)
        put('SOURCE_COORDINATION_EX_V5.original.json', ex_raw)
        normal = decode_normal(normal_raw); ex = json.loads(ex_raw)
        check(normal['job_id'] == JOB and normal['state'] == 'succeeded' and normal['exit_code'] == 0
              and normal['timed_out'] is False and normal['cancelled'] is False
              and normal['output_complete'] is True and normal['output_durable'] is True
              and normal['terminal_publication_confirmed'] is True, 'actual normal zero terminal')
        check(ex['path'] == str(LOCK) and ex['source_repo'] == str(SOURCE)
              and ex['lock_acquired'] == 'LOCK_EX|LOCK_NB' and ex['inheritable'] is True
              and all(ex[k] == v for k, v in LOCK_IDENTITY.items()), 'actual V5 exclusive lease')
        result_v5 = json.loads(original['RESULT.json'])
        check(result_v5['status'] == 'MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED'
              and result_v5['source_commit'] == HEAD and result_v5['source_tree'] == HEAD_TREE
              and result_v5['parents'] == ['86dd56a930277e0d1aef3e475e35c2b5d60b43b7']
              and result_v5['git_metadata_unchanged'] is True
              and result_v5['qualification'] is False and result_v5['test_commands_dispatched'] == 0,
              'actual successful maintenance-only result')
        check(result_v5['attempted_commands'] == ['fix', 'fmt'] and result_v5['not_run_commands'] == [], 'both actual phases')
        check({x['check']: x['status'] for x in result_v5['final_audits']} ==
              {'actual_complete_source_and_git': 'verified', 'original_inputs': 'verified'}, 'actual final audits')
        for index, phase in enumerate(('fix', 'fmt')):
            terminal = json.loads(original[phase + '.terminal.json'])
            execution = json.loads(original[phase + '.execute_logged.original.json'])
            check(terminal == result_v5['stages'][index], 'original stage equals result stage')
            check(execution == terminal['execution'] and execution['returncode'] == 0
                  and execution['timed_out'] is False and execution['output_limit_exceeded'] is False
                  and terminal['command_returned'] is True and terminal['retention']['complete'] is True,
                  'actual zero exit and complete phase retention')
        final = result_v5['actual_final_source']
        check(final['complete'] is True and final['inventory'] == INVENTORY_PIN
              and final['postimages']['all_actual_physical_tree'] == PHYSICAL_TREE
              and final['postimages']['all_actual_physical_leaf_count'] == 15188
              and final['postimages']['change_count'] == 43, 'actual complete physical source identity')
        retained = unpack(original['final.inventory.json.gz'], INVENTORY_PIN)
        table = json.loads(original['ARTIFACTS.json'])['files']
        for name in ('final.inventory.json.gz', 'final.postimages.json.gz'):
            rows = [x for x in table if x['name'] == name]
            check(len(rows) == 1 and identity(original[name]) == {k: rows[0][k] for k in ('bytes', 'sha256', 'git_blob')},
                  'original artifact index exact compressed bytes')
        check(json.loads(original['final.postimages-summary.json']) == final['postimages'], 'complete original postimage summary')
        lock_stat = LOCK.lstat()
        check(stat.S_ISREG(lock_stat.st_mode) and LOCK.resolve() == LOCK, 'actual regular coordination lock')
        lease_fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(lease_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        lock_stat = os.fstat(lease_fd)
        lock_id = {'device': lock_stat.st_dev, 'inode': lock_stat.st_ino, 'uid': lock_stat.st_uid,
                   'mode': stat.S_IMODE(lock_stat.st_mode), 'nlink': lock_stat.st_nlink}
        check(lock_id == LOCK_IDENTITY and stamps(lock_stat) == stamps(LOCK.lstat()), 'same actual coordination inode')
        put('SOURCE_COORDINATION_SH.json', jbytes({'path': str(LOCK), **lock_id, 'at': now(),
              'pid': os.getpid(), 'fd': lease_fd, 'lock_acquired': 'LOCK_SH|LOCK_NB', 'qualification': False,
              'scope': 'This task cooperative writers only; full inventories remain mandatory.'}))
        spec = importlib.util.spec_from_file_location('hepta_actual_postfmt_original_inventory', OUTPUT / 'INVENTORY_DRIVER.original.py')
        check(spec is not None and spec.loader is not None, 'original inventory loader')
        driver = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = driver
        spec.loader.exec_module(driver)
        before_git = git_metadata(); compressed('GIT_BEFORE.json.gz', before_git)
        before = driver.inventory(SOURCE)
        compressed('SOURCE_BEFORE.json.gz', before)
        check(before == retained, 'actual full before inventory equals original final bytes')
        snapshot = json.loads(before)
        check(snapshot['source']['head'] == HEAD and snapshot['source']['tree'] == HEAD_TREE
              and snapshot['tracked_entries'] == snapshot['filesystem_entries'] == 15188,
              'actual source identity; dirty status is retained verbatim')
        rows = {row['path']: row for row in snapshot['files']}
        check(len(rows) == len(snapshot['files']) == 15188
              and all(row['stable'] is True for row in rows.values()), 'complete stable source rows')
        captured = []
        for relative in paths:
            rel = Path(relative)
            check(not rel.is_absolute() and '..' not in rel.parts, 'no source path traversal')
            path = SOURCE / rel
            check(path.resolve().is_relative_to(SOURCE), 'source containment')
            started = now(); raw, s = read_regular(path); finished = now()
            row = rows[relative]; pin = identity(raw)
            check(row['kind'] == 'file' and row['bytes'] == pin['bytes']
                  and row['sha256'] == pin['sha256'] and row['working_blob'] == pin['git_blob']
                  and row['permissions'] == stat.S_IMODE(s.st_mode), 'actual file equals complete physical row')
            captured.append({'path': relative, 'kind': 'file', 'mode': '100755' if s.st_mode & 0o111 else '100644',
                             'permissions': stat.S_IMODE(s.st_mode), 'bytes': pin['bytes'], 'sha256': pin['sha256'],
                             'git_blob_sha': pin['git_blob'], 'content_base64': base64.b64encode(raw).decode(),
                             'read_started_at': started, 'read_finished_at': finished, 'stable': True,
                             'original_inventory_row': row})
        packet = {'format': 'hepta-actual-postformat-73-file-packet-v1', 'qualification': False,
                  'source_identity': snapshot['source'], 'complete_inventory': identity(before),
                  'actual_physical_tree': PHYSICAL_TREE, 'groups': request['actual_byte_capture']['groups'],
                  'maintenance_job': JOB, 'files': captured}
        packet_raw = jbytes(packet)
        check(len(packet_raw) <= MAX_PACKET_BYTES, 'bounded complete 73 file packet')
        result['capture_packet'] = compressed('ACTUAL_73_FILES.json.gz', packet_raw)
        result.update(source_identity=snapshot['source'], actual_physical_tree=PHYSICAL_TREE,
                      captured_paths=len(captured), complete_inventory=identity(before), maintenance_job=JOB,
                      original_final_postimages=identity(original['final.postimages.json.gz']))
        capture_complete = True
    except BaseException as error:
        result.update(status='UNKNOWN_CAPTURE', error=repr(error), traceback=traceback.format_exc())
    finally:
        signal.alarm(0)
        signal.alarm(RETENTION_SECONDS)
        audits = []
        try:
            if before is not None and driver is not None:
                after = driver.inventory(SOURCE)
                compressed('SOURCE_AFTER.json.gz', after)
                result['source_changed'] = after != before
                check(after == before, 'source changed during capture')
                after_git = git_metadata(); compressed('GIT_AFTER.json.gz', after_git)
                check(after_git == before_git, 'Git metadata changed during capture')
                check(stamps(os.fstat(lease_fd)) == stamps(LOCK.lstat()), 'coordination inode changed')
                audits.append({'check': 'full_source_git_and_lock', 'status': 'verified', 'inventory': identity(after)})
            else:
                audits.append({'check': 'full_source_git_and_lock', 'status': 'not_started'})
            for path, pin in inputs:
                pinned(path, pin)
            audits.append({'check': 'all_original_inputs', 'status': 'verified', 'count': len(inputs)})
            if capture_complete and result.get('source_changed') is False:
                result['status'] = 'CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED'
        except BaseException as error:
            result.update(status='UNKNOWN_CAPTURE_OR_FINAL_AUDIT', final_error=repr(error),
                          final_traceback=traceback.format_exc())
        finally:
            signal.alarm(0)
            result.update(final_audits=audits, finished_at=now(), artifacts=artifacts)
            try:
                put('RESULT.json', jbytes(result))
                print(json.dumps({'event': 'readonly_actual_postfmt_capture_terminal', 'status': result['status'],
                                  'output': str(OUTPUT), 'qualification': False}), flush=True)
            finally:
                if lease_fd is not None:
                    os.close(lease_fd)
    return 0 if result['status'] == 'CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED' else 1


artifacts = []
if __name__ == '__main__':
    raise SystemExit(main())
