#!/usr/bin/env python3
"""HOLD: apply reviewed non-Rust bytes, then the one original 900-second fmt.

This thin control imports the unchanged, pinned V5 recorder and maintenance
functions. It never calls that module's main/initial_preflight/fix. Approval and
the ordinary agent's final packet are intentionally absent in the draft config.
"""
import argparse
import base64
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import traceback
import types

EVIDENCE = Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1')
CONTROL = EVIDENCE / 'final-nonrust-fmt-control-v1'
CONFIG = CONTROL / 'APPROVED_CONFIG.json'
OUT = EVIDENCE / 'final-nonrust-fmt-v1'
LOCK = EVIDENCE / 'SOURCE_COORDINATION.lock'
LOCK_ID = {'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1}
V5 = EVIDENCE / 'driver-v5.py'
V5_PIN = {'bytes': 63007, 'sha256': 'ff2078884d48dcb92ec3b681d7479c33e9b074d1677108ce60e913c90f002431', 'git_blob': '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'}
V5_CONFIG = EVIDENCE / 'APPROVED_CONFIG_V5.json'
V5_CONFIG_PIN = {'bytes': 9668, 'sha256': '47acb8e9130d497035fad7b90ec0a9c4d0b3277e71c6b9392b75a7107d4599e1', 'git_blob': 'a66ab71a3504f29240da6048ca2c45ca3735e89b'}
CAPTURE = EVIDENCE / 'postformat-handoff-v5-v1'
CAPTURE_RESULT_PIN = {'bytes': 22007, 'sha256': '9ef6b7201eadf1a77ca3a5fda9943f75e7202dedd5b725ad64d22ffdd23a6283', 'git_blob': 'aef06c019dd96f2a8e493fa524e09183a4b215bf'}
CAPTURE_NORMAL_PIN = {'bytes': 909, 'sha256': '1ad13e624fa88b3509d5519c26335c92449d803ff775f8f14068d65dbbfb106e', 'git_blob': '8146d2ad99259a1965038f01dd3f8f186cd3e5a0'}
CAPTURE_JOB = '1a1d1880477-2564-1c56'
V5_JOB = '1a1d16f37be-2564-1c4a'
BASELINE = {'bytes': 5614211, 'sha256': '3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f', 'git_blob': '1563de8825fc183d345d10d03e68d79b2d9211ca'}
BASELINE_TREE = '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
V5_RESULT_PIN = {'bytes': 15927, 'sha256': '50d43cf8e2b3070733405e646f96eb8e17c7e0734cf8f1a7f4b065e68b463e6c', 'git_blob': '28fd9e0970a977881971a3e5c2ddaf73f69a58a0'}
V5_NORMAL_PIN = {'bytes': 956, 'sha256': 'c313aece99eb8d3d7eb95c9d4997b81808c8404062371ab3dc52abb9badcd675', 'git_blob': '2bb8699bae213bd97926beb6589df08e7813c79a'}
V5_GIT_PIN = {'bytes': 489, 'sha256': 'e8ec74c83f7f671727d417e722da27a1337e70b0ef14b3a0481bd5d0ef609e14', 'git_blob': 'be108e81e8becd1b6dd3f4cac302b5f855d51b41'}
PREFLIGHT_SECONDS = 600
RECORD_SECONDS = 300
FMT_SECONDS = 900


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def first_read(path, pin):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(pin['bytes'] + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
            stamp(before) != stamp(after) or stamp(after) != stamp(Path(path).lstat()) or identity(raw) != pin):
        raise ValueError('fixed stable original bytes: ' + str(path))
    return raw


def module_from_original():
    raw = first_read(V5, V5_PIN)
    module = types.ModuleType('hepta_final_format_original_v5')
    module.__file__ = str(V5)
    exec(compile(raw, str(V5), 'exec'), module.__dict__)
    module.OUT = OUT
    module.record_remaining = RECORD_SECONDS
    module.result = {'format': 'hepta-reviewed-nonrust-final-format-result-v1', 'status': 'HOLD',
                     'source_repo': str(module.REPO), 'source_commit': module.HEAD,
                     'source_tree': module.TREE, 'parents': module.PARENTS,
                     'baseline_physical_tree': BASELINE_TREE, 'baseline_inventory': BASELINE,
                     'test_commands_dispatched': 0, 'qualification': False,
                     'source_ref_updates': False, 'automatic_retry': False,
                     'fix_dispatched': False, 'source_write_attempted': False,
                     'applied_paths': [], 'stages': [], 'cargo_target': str(module.TARGET),
                     'budget_scope': 'One original fmt 900 seconds. Existing preflight/apply 600 and total evidence 300 seconds; no fix or test command.'}
    return module, raw


def lock_identity(fd):
    s = os.fstat(fd)
    outside = LOCK.lstat()
    fields = lambda value: {'device': value.st_dev, 'inode': value.st_ino, 'uid': value.st_uid,
                            'mode': stat.S_IMODE(value.st_mode), 'nlink': value.st_nlink}
    if not stat.S_ISREG(s.st_mode) or not stat.S_ISREG(outside.st_mode) or fields(s) != fields(outside) or fields(s) != LOCK_ID:
        raise ValueError('actual same source-coordination inode required')
    return fields(s)


def prove_actual_capture(m):
    raw = m.read_input(CAPTURE / 'RESULT.json', CAPTURE_RESULT_PIN)
    observed = m.parse(raw)
    terminal_raw = m.read_input(CONTROL / 'CAPTURE_NORMAL.original.json', CAPTURE_NORMAL_PIN)
    terminal = m.parse_supervisor(terminal_raw)
    m.check(terminal['job_id'] == CAPTURE_JOB, 'actual capture supervisor job')
    m.check(observed['status'] == 'CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED'
            and observed['source_changed'] is False and observed['qualification'] is False
            and observed['source_write_authorized'] is False and observed['tests_dispatched'] == 0
            and observed['captured_paths'] == 73 and observed['complete_inventory'] == BASELINE
            and observed['actual_physical_tree'] == BASELINE_TREE and observed['maintenance_job'] == V5_JOB,
            'actual complete postformat capture')
    m.check({x['check']: x['status'] for x in observed['final_audits']} ==
            {'full_source_git_and_lock': 'verified', 'all_original_inputs': 'verified'}, 'complete capture final audits')
    m.write('CAPTURE_RESULT.original.json', raw); m.write('CAPTURE_NORMAL.original.json', terminal_raw)
    packet_pin = {key: observed['capture_packet'][key] for key in ('bytes', 'sha256', 'git_blob')}
    compressed = m.read_input(CAPTURE / 'ACTUAL_73_FILES.json.gz', packet_pin)
    packet_raw = gzip.decompress(compressed)
    m.pin_bytes(packet_raw, observed['capture_packet']['raw'], 'complete actual capture packet')
    packet = m.parse(packet_raw)
    m.check(packet['source_identity'] == observed['source_identity'] and len(packet['files']) == 73,
            'actual capture source identity')
    return observed, packet


def prepare(m, control, original):
    m.check(os.getuid() == 1000, 'fixed desktop account')
    current = m.regular_read(__file__, 1000000)
    m.check(control['format'] == 'hepta-final-nonrust-format-approval-v1'
            and control['status'] == 'ROOT_APPROVED_TO_EXECUTE' and control['root_execution_approved'] is True,
            'HOLD: formal source application and final-format approval absent')
    m.check(control['driver'] == identity(current) and control['original_v5_driver'] == V5_PIN,
            'exact thin and unchanged original driver pins')
    m.check(control['source_repo'] == str(m.REPO) and control['head'] == m.HEAD and control['head_tree'] == m.TREE
            and control['baseline_inventory'] == BASELINE and control['baseline_physical_tree'] == BASELINE_TREE,
            'HEAD identity and actual dirty baseline remain separate')
    m.check(control['fmt_argv'] == m.FMT and control['fmt_seconds'] == FMT_SECONDS
            and control['preflight_seconds'] == PREFLIGHT_SECONDS and control['record_seconds'] == RECORD_SECONDS,
            'original formatter argv and unchanged budgets')
    m.check(control['fix_authorized'] is False and control['test_commands_authorized'] is False
            and control['ref_updates_authorized'] is False, 'no fix/test/ref scope')
    m.input_pins[str(Path(__file__))] = identity(current)
    m.input_pins[str(CONFIG)] = identity(m.regular_read(CONFIG))
    m.input_pins[str(V5)] = V5_PIN
    m.write('ACTUAL_DRIVER.py', current); m.write('MAINTENANCE_V5.original.py', original)
    m.write('APPROVED_CONFIG.original.json', m.regular_read(CONFIG))
    old_cfg_raw = m.read_input(V5_CONFIG, V5_CONFIG_PIN)
    m.cfg = m.parse(old_cfg_raw)  # Only original environment admission consumes this historic config.
    m.write('V5_APPROVED_CONFIG.original.json', old_cfg_raw)
    captured, capture_packet = prove_actual_capture(m)
    v5_raw = m.read_input(EVIDENCE / 'run-v5' / 'RESULT.json', V5_RESULT_PIN)
    v5 = m.parse(v5_raw)
    normal_raw = m.read_input(EVIDENCE / 'postformat-capture-control-v1' / 'V5_NORMAL_SUPERVISOR.original.json', V5_NORMAL_PIN)
    normal = m.parse_supervisor(normal_raw)
    m.check(normal['job_id'] == V5_JOB and v5['status'] == 'MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED'
            and [row['name'] for row in v5['stages']] == ['fix', 'fmt']
            and all(row['status'] == 'completed_review_required' and row['execution']['returncode'] == 0
                    and not row['execution']['timed_out'] and not row['execution']['output_limit_exceeded'] for row in v5['stages']),
            'actual V5 completed original commands, not a new execution')
    m.write('V5_RESULT.original.json', v5_raw); m.write('V5_NORMAL.original.json', normal_raw)
    m.inventory_module = m.load_module(m.INVENTORY_FILE, m.INVENTORY_PIN, 'hepta_final_format_original_inventory')
    m.write('INVENTORY_DRIVER.original.py', m.regular_read(m.INVENTORY_FILE))
    for pin in m.SOURCE_PINS:
        raw = m.regular_read(m.REPO / pin['path'])
        m.pin_bytes(raw, pin, 'original launch entry ' + pin['path'])
        name = 'SOURCE_ENTRY.' + pin['path'].replace('/', '__')
        saved = m.write(name, raw)
        m.input_pins[str(OUT / name)] = identity(raw)
        m.source_entry_snapshots[pin['path']] = {'path': str(OUT / name), **saved}
    helper_pin = next(x for x in m.SOURCE_PINS if x['path'] == 'scripts/hepta_ci_exec.py')
    m.execute_module = m.load_module(Path(m.source_entry_snapshots[helper_pin['path']]['path']), helper_pin,
                                     'hepta_final_format_original_execute_logged')
    m.initial_git_state = m.git_state()
    old_git = m.parse(m.read_input(EVIDENCE / 'run-v5' / 'final.git-state.json', V5_GIT_PIN))
    m.check(m.initial_git_state == old_git, 'exact original Git state unchanged after V5')
    m.jwrite('SOURCE_GIT_STATE.before.json', m.initial_git_state)
    m.initial_inventory = m.inventory_module.inventory(m.REPO)
    m.pin_bytes(m.initial_inventory, BASELINE, 'actual complete dirty baseline')
    m.gzrecord('SOURCE.before.inventory.json.gz', m.initial_inventory)
    snapshot = m.parse(m.initial_inventory)
    m.check(snapshot['source'] == captured['source_identity'] and snapshot['tracked_entries'] == 15188
            and snapshot['filesystem_entries'] == 15188, 'actual full baseline source identity and counts')
    leaves = m.actual_leaf_map(m.initial_inventory)
    m.check(len(leaves) == 15188 and m.merkle(leaves) == BASELINE_TREE, 'actual complete physical baseline tree')
    m.latest_inventory = m.initial_inventory
    m.initial_git_metadata = m.metadata_inventory(m.REPO / '.git')
    m.gzrecord('SOURCE_GIT_METADATA.before.json.gz', m.initial_git_metadata)
    # Dirty working blobs do not have to be stored as Git objects. Retain actual
    # bytes before any application so the unchanged original recorder can capture
    # every later formatter change without inventing an unavailable preimage.
    dirty = []
    for row in snapshot['files']:
        if row.get('matches_index') is not True:
            m.check(row['kind'] == 'file' and row['stable'] is True, 'supported baseline dirty file')
            raw = m.read_actual_leaf(row['path'], row)
            m.raw_cache[row['working_blob']] = raw
            dirty.append({'row': row, 'raw_base64': base64.b64encode(raw).decode()})
    m.gzrecord('INITIAL_DIRTY_PREIMAGES.json.gz', m.jbytes({'files': dirty, 'source_inventory': BASELINE}))
    m.result['actual_capture_job'] = CAPTURE_JOB
    m.result['actual_maintenance_job'] = V5_JOB
    m.result['fmt_base'] = m.check_fmt_base()
    m.initial_environment = m.environment_preflight()
    packet_raw = m.read_input(CONTROL / 'NONRUST_PACKET.json', control['nonrust_packet'])
    m.write('NONRUST_PACKET.original.json', packet_raw)
    packet = m.parse(packet_raw)
    m.check(packet['format'] == 'hepta-reviewed-nonrust-source-apply-v1'
            and packet['source_identity'] == captured['source_identity'] and packet['base_inventory'] == BASELINE
            and packet['base_physical_tree'] == BASELINE_TREE, 'ordinary reviewed packet exact baseline')
    changes = packet['changes']
    paths = [row['path'] for row in changes]
    safe = {row['path'] for row in capture_packet['files'] if
            row['path'] in ('CALLERS.toml', '.github/blob-size-allowlist.txt') or
            (row['path'].startswith('qa/b4-no-bypass/') and row['path'].endswith('.py'))}
    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] and paths
            and set(paths) <= safe, 'exact approved existing non-Rust paths only')
    rows = {row['path']: row for row in snapshot['files']}
    expected = dict(leaves)
    for item in changes:
        path = item['path']; row = rows[path]
        m.check(item['mode'] == leaves[path]['mode'] == '100644' and row['kind'] == 'file'
                and row['permissions'] == 0o644, 'no deletion/new path/mode or Rust change')
        before = m.read_actual_leaf(path, row)
        m.pin_bytes(before, item['before'], 'reviewed actual non-Rust preimage ' + path)
        after = base64.b64decode(item['after_base64'], validate=True)
        m.pin_bytes(after, item['after'], 'reviewed non-Rust postimage ' + path)
        m.check(after != before, 'no claimed no-op source update')
        m.raw_cache[row['working_blob']] = before
        expected[path] = {'mode': item['mode'], 'sha': item['after']['git_blob'],
                          'bytes': item['after']['bytes'], 'sha256': item['after']['sha256']}
    m.check(packet['expected_after_leaf_count'] == control['expected_after_leaf_count'] == len(expected) == 15188
            and packet['expected_after_physical_tree'] == control['expected_after_physical_tree'] == m.merkle(expected),
            'independently reconstruct exact approved after-apply tree')
    m.verify_original_inputs()
    return packet, expected


def apply_packet(m, packet, expected):
    m.check(m.inventory_module.inventory(m.REPO) == m.initial_inventory, 'full source unchanged immediately before apply')
    m.check(m.git_state() == m.initial_git_state, 'Git unchanged immediately before apply')
    active = m.active_build_processes()
    m.jwrite('APPLY.process-preflight.json', active)
    m.check(not active['active_matching_processes'] and not active['unreadable_matching_processes'],
            'unchanged original global build/formatter guard before source application')
    for number, item in enumerate(packet['changes'], 1):
        path = m.REPO / item['path']
        m.real_directory(path.parent)
        m.pin_bytes(m.regular_read(path), item['before'], 'immediate preimage ' + item['path'])
        m.check(stat.S_IMODE(path.lstat().st_mode) == 0o644 and path.lstat().st_uid == os.getuid(),
                'current owned regular preimage mode')
        after = base64.b64decode(item['after_base64'], validate=True)
        m.result['source_write_attempted'] = True
        m.jwrite('APPLY.%03d.attempt.json' % number, {'path': item['path'], 'before': item['before'],
                 'after': item['after'], 'at': m.now(), 'status': 'attempted', 'rollback': False})
        fd, temporary = tempfile.mkstemp(prefix='.hepta-36fa-final-', dir=path.parent)
        temporary = Path(temporary)
        m.jwrite('APPLY.%03d.temporary.json' % number, {'path': str(temporary), 'source': item['path']})
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(after); stream.flush(); os.fsync(stream.fileno())
        m.pin_bytes(m.regular_read(temporary), item['after'], 'complete source sibling postimage')
        m.pin_bytes(m.regular_read(path), item['before'], 'preimage before atomic replacement')
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        m.pin_bytes(m.regular_read(path), item['after'], 'actual atomic postimage')
        m.raw_cache[item['after']['git_blob']] = after
        m.result['applied_paths'].append(item['path'])
        m.jwrite('APPLY.%03d.completed.json' % number, {'path': item['path'], 'at': m.now(),
                 'status': 'observed_complete', 'after': item['after']})
    actual = m.inventory_module.inventory(m.REPO)
    m.check(m.actual_leaf_map(actual) == expected, 'all physical source leaves equal the approved non-Rust result')
    m.check(m.git_state() == m.initial_git_state, 'no index/HEAD/config/ref change by source application')
    m.result['application'] = m.capture_source('apply.after', m.initial_inventory)
    m.check(m.result['application']['postimages']['paths'] == [x['path'] for x in packet['changes']],
            'only exact reviewed application paths changed')
    m.result['nonrust_application_complete'] = True
    m.event('reviewed_nonrust_application_completed', paths=m.result['applied_paths'],
            physical_tree=m.merkle(expected), source_commit=m.HEAD, qualification=False)


def retain_terminal(m):
    m.result['finished_at'] = m.now()
    m.result['attempted_commands'] = list(m.attempted)
    m.result['not_run_commands'] = [] if 'fmt' in m.attempted else ['fmt']
    m.result['record_seconds_remaining'] = m.record_remaining
    m.result['freeze_approved'] = False
    m.result['retry_policy'] = 'No automatic retry, rollback, reset, dependency install, fix/test, or ref update. Retain partial application and every actual formatter postimage.'
    m.jwrite('READONLY_COMMANDS.json', m.commands)
    m.jwrite('INPUT_IDENTITIES.json', m.input_pins)
    m.jwrite('SOURCE_ENTRY_SNAPSHOTS.json', m.source_entry_snapshots)
    if (OUT / 'EVENTS.jsonl').exists():
        raw = m.regular_read(OUT / 'EVENTS.jsonl')
        m.artifacts.append({'name': 'EVENTS.jsonl', **identity(raw)})
    m.jwrite('ARTIFACTS.json', {'files': list(m.artifacts), 'terminal_report': 'RESULT.json',
                              'terminal_report_self_hash_not_included': True})
    m.jwrite('RESULT.json', m.result)
    print(json.dumps({'event': 'reviewed_nonrust_final_format_terminal', 'status': m.result['status'],
                      'out': str(OUT), 'qualification': False, 'test_commands_dispatched': 0}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-sha256', required=True)
    args = parser.parse_args()
    m, original = module_from_original()
    config_raw = m.regular_read(CONFIG, 1000000)
    m.check(m.sha256(config_raw) == args.config_sha256, 'launcher-pinned formal config')
    control = m.parse(config_raw)
    m.real_directory(m.REPO); m.real_directory(CONTROL)
    m.check(not os.path.lexists(OUT), 'existing attempt: reconcile the original job, never overwrite')
    os.mkdir(OUT, 0o700)
    os.chdir(m.REPO)
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'; sys.dont_write_bytecode = True
    m.result['started_at'] = m.now()
    lease = None
    signal.signal(signal.SIGALRM, m.alarm_handler)
    m.set_alarm(PREFLIGHT_SECONDS)
    try:
        lease = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        m.jwrite('SOURCE_COORDINATION_EX.json', {'path': str(LOCK), **lock_identity(lease),
                 'at': m.now(), 'pid': os.getpid(), 'fd': lease, 'lock_acquired': 'LOCK_EX|LOCK_NB',
                 'scope': 'Only this task cooperative writers; full physical and Git checks remain required.'})
        packet, expected = prepare(m, control, original)
        apply_packet(m, packet, expected)
        signal.alarm(0)
        if m.stage('fmt', m.FMT, FMT_SECONDS):
            m.result['status'] = 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
            changed = m.result['stages'][-1]['retention']['postimages']['paths']
            m.result['formatter_changed_paths'] = changed
            m.result['format_source_stable'] = not changed
            m.result['requires_fence_refresh_review'] = bool(changed)
        else:
            m.result['status'] = 'FAILED_FORMAT' if m.result['stages'][-1]['status'] == 'failed' else 'UNKNOWN'
    except BaseException as error:
        m.result.update(status='UNKNOWN' if m.result['source_write_attempted'] or m.attempted else 'FAILED_PRECONDITION',
                        error=repr(error), traceback=traceback.format_exc())
    finally:
        signal.alarm(0)
        audits = []
        for name, action in (('actual_complete_source_and_git', m.finalize_source), ('original_inputs', m.finalize_inputs)):
            report = {'check': name, 'started_at': m.now()}
            try:
                report.update(m.bounded_record(action))
            except BaseException as error:
                report.update(status='unknown', error=repr(error), traceback=traceback.format_exc())
            report['finished_at'] = m.now(); audits.append(report)
        try:
            m.check(lease is not None, 'no actual coordination lease')
            lock_identity(lease)
            audits.append({'check': 'same_source_coordination_lock', 'status': 'verified'})
        except BaseException as error:
            audits.append({'check': 'same_source_coordination_lock', 'status': 'unknown', 'error': repr(error)})
        m.result['final_audits'] = audits
        if any(x['status'] != 'verified' for x in audits):
            m.result['status'] = 'UNKNOWN'
        try:
            retain_terminal(m)
        finally:
            if lease is not None:
                os.close(lease)
    return 0 if m.result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED' else 1


if __name__ == '__main__':
    try:
        code = main()
    except BaseException as error:
        print(json.dumps({'event': 'final_nonrust_format_admission_or_retention_error', 'status': 'UNKNOWN',
                          'error': repr(error), 'qualification': False}), flush=True)
        code = 1
    sys.exit(code)
