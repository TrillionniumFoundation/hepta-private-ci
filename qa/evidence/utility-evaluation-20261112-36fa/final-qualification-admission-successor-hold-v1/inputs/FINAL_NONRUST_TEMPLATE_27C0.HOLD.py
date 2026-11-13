#!/usr/bin/env python3
"""HOLD: apply reviewed non-Rust bytes, then the one original 900-second fmt.

This thin control imports the exact 594610 recorder and maintenance functions
used by completed job 41e. It never calls that module's main/initial_preflight/fix.
Actual 41e proof and current full bytes replace the historical SH73/V5 binding.
Approval and the final immutable non-Rust packet remain absent in the HOLD config.
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

EVIDENCE = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1')
CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1')
CONFIG = CONTROL / 'APPROVED_CONFIG.json'
OUT = CONTROL / 'run'
LOCK = Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock')
LOCK_ID = {'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1}
MAINTENANCE = EVIDENCE / 'driver-maintenance.py'
MAINTENANCE_CONFIG = EVIDENCE / 'APPROVED_MAINTENANCE_CONFIG.json'
MAINTENANCE_RUN = EVIDENCE / 'run'
MAINTENANCE_JOB = '1a1d47cebc8-392-41e'
MAINTENANCE_PIN = {'bytes': 68520, 'sha256': '2e8501f584a6905a07124f04bb623c2674c1ec77299b89fbc76ef06610c589ed', 'git_blob': '59461030d4160f7ad6a978df5a7b6aaeb33fb2a6'}
MAINTENANCE_CONFIG_PIN = {'bytes': 13693, 'sha256': '3ab98f7c35ce030439773f2035b7d6e4b8f9c4b11b3f6e8f93b431ea369286d7', 'git_blob': '7bddb6c423afbe739bc36a7df2516730911a9337'}
MAINTENANCE_RESULT_PIN = {'bytes': 12532, 'sha256': 'fc551cbf01cbc3a113b4039212e6263cf3c59034421dc795ac187248cabac484', 'git_blob': 'b87aed7647ac34e3db0e381110bf685438aee0ee'}
MAINTENANCE_NORMAL_PIN = {'bytes': 956, 'sha256': '865ecacf8f40e4f3e94a92d80adc19190f60d847869394728adfc3a643190b04', 'git_blob': '70e1866f963a2a2a8d6f3bd468ddd0c291fbf871'}
MAINTENANCE_GIT_PIN = {'bytes': 489, 'sha256': 'a63fa97612dbe0eb6a90da53563a895bcbff187898ef38083df08a18269e8147', 'git_blob': 'aef9e645b81c2a7f349b11d546c5555b1475c906'}
MAINTENANCE_ARTIFACTS_PIN = {'bytes': 53526, 'sha256': '4fe039d5630c39af2a05c9ba7a9272cda4bc2a351a81cd253eca7bf21657e706', 'git_blob': '222eb4e2913d62cdd308e2ce26edf7c320ebe47f'}
MAINTENANCE_INPUTS_PIN = {'bytes': 6256, 'sha256': '477d05eb00e62a90f5c187cc18c4ad1401be0b39c289ef5b4dfe1328be96d4bb', 'git_blob': '5c0ae8a43544a14461d272e1a0e70bb9ef3b1395'}
MAINTENANCE_LEASE_PIN = {'bytes': 841, 'sha256': '523208c3692d5ffe93a546cd06faf7500daf4f036386996082301943f19acd26', 'git_blob': 'd2f348f2e2864be124049548118b0ad2eea424e5'}
BASELINE = {'bytes': 5633323, 'sha256': '981e5971d3e8afc2694bcb1951b0261d24f0238675187005ec8e9bb386a07bf1', 'git_blob': '4a77b645fd76a980ef746997efbd09fcd8f233ba'}
BASELINE_GZIP_PIN = {'bytes': 1266734, 'sha256': '27781a7a5eded2f0b14a07bd7868f23a36d31df10a9e7282eb237bc2ce7b155b', 'git_blob': '64d1b890871434829776a4850865eac8d95d79c2'}
MAINTENANCE_METADATA_GZIP_PIN = {'bytes': 791, 'sha256': 'e2424547edb11c781c10b53e619ad7ee04b8325c3ddd4f49e96e5fe33a70c7be', 'git_blob': '4858d38c42978b8db371db5a98232bacd99a94cc'}
MAINTENANCE_METADATA_PIN = {'bytes': 2654, 'sha256': '2a980585e50ec38b223fef002990f42e122b7f8a57b49298c32de6c7c67a24b9', 'git_blob': '42e3986f6a5f06d8518067f0d9dd2ec3e6b46c6a'}
BASELINE_TREE = 'c026a8d7e93c958b39a36c666debecb3dba4be14'
LEAVES = 15243
NONRUST_PATHS = ('.github/blob-size-allowlist.txt', 'CALLERS.toml', 'qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json', 'qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py')
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
    raw = first_read(MAINTENANCE, MAINTENANCE_PIN)
    module = types.ModuleType('hepta_final_format_original_594610')
    module.__file__ = str(MAINTENANCE)
    exec(compile(raw, str(MAINTENANCE), 'exec'), module.__dict__)
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


def prove_actual_maintenance(m):
    raw = m.read_input(MAINTENANCE_RUN / 'RESULT.json', MAINTENANCE_RESULT_PIN)
    observed = m.parse(raw)
    normal_raw = m.read_input(CONTROL / 'MAINTENANCE_NORMAL.original.json', MAINTENANCE_NORMAL_PIN)
    normal = m.parse_supervisor(normal_raw)
    m.check(normal['job_id'] == MAINTENANCE_JOB, 'actual completed 41e supervisor job')
    m.check(observed['format'] == 'hepta-original-scoped-maintenance-result-v1'
            and observed['status'] == 'MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED'
            and observed['source_repo'] == str(m.REPO) and observed['source_commit'] == m.HEAD
            and observed['source_tree'] == m.TREE and observed['parents'] == m.PARENTS
            and observed['source_preflight_complete'] is True,
            'actual completed 41e source identity')
    m.check(observed['qualification'] is False and observed['test_commands_dispatched'] == 0
            and observed['source_ref_updates'] is False and observed['automatic_retry'] is False
            and observed['attempted_commands'] == ['fix', 'fmt'] and observed['not_run_commands'] == []
            and observed['cargo_target'] == str(m.TARGET), 'actual maintenance scope and consumed commands')
    stages = observed['stages']
    m.check(len(stages) == 2 and [row['name'] for row in stages] == ['fix', 'fmt'],
            'both actual original maintenance stages')
    for row, argv, seconds in zip(stages, (m.FIX, m.FMT), (m.FIX_SECONDS, FMT_SECONDS)):
        m.check(row['argv'] == argv and row['timeout_seconds'] == seconds
                and row['maximum_log_bytes'] == m.MAXIMUM_LOG_BYTES
                and row['working_directory'] == str(m.REPO) and row['test_command'] is False
                and row['command_returned'] is True and row['execution_outcome'] == 'completed'
                and row['status'] == 'completed_review_required' and row['raw_log_retained'] is True
                and row['execution']['returncode'] == 0 and row['execution']['timed_out'] is False
                and row['execution']['output_limit_exceeded'] is False and row['retention']['complete'] is True,
                'actual complete original stage and unchanged command budget')
    complete = observed['actual_final_source']
    m.check(complete['complete'] is True and complete['inventory'] == BASELINE
            and complete['postimages']['all_actual_physical_tree'] == BASELINE_TREE
            and complete['postimages']['all_actual_physical_leaf_count'] == LEAVES
            and complete['postimages']['change_count'] == len(complete['postimages']['paths']) == 17
            and stages[-1]['retention']['inventory'] == BASELINE
            and observed['git_metadata_unchanged'] is True, 'actual complete 41e dirty baseline')
    audits = observed['final_audits']
    m.check(len(audits) == 2 and {row['check']: row['status'] for row in audits} ==
            {'actual_complete_source_and_git': 'verified', 'original_inputs': 'verified'},
            'both actual complete maintenance final audits')
    source_audit = next(row for row in audits if row['check'] == 'actual_complete_source_and_git')
    inputs_audit = next(row for row in audits if row['check'] == 'original_inputs')
    m.check(source_audit['complete_final_source'] == complete and source_audit['git_metadata_unchanged'] is True
            and inputs_audit['input_count'] == 24 and inputs_audit['unchanged'] is True,
            'actual final source and original-input audit payloads')
    inventory_gzip = m.read_input(MAINTENANCE_RUN / 'final.inventory.json.gz', BASELINE_GZIP_PIN)
    inventory_raw = gzip.decompress(inventory_gzip)
    m.pin_bytes(inventory_raw, BASELINE, 'complete original final 41e inventory')
    snapshot = m.parse(inventory_raw)
    m.check(snapshot['source']['head'] == m.HEAD and snapshot['source']['tree'] == m.TREE
            and snapshot['tracked_entries'] == snapshot['filesystem_entries'] == len(snapshot['files']) == LEAVES,
            'original inventory source and complete counts')
    dirty = sorted(row['path'] for row in snapshot['files'] if row.get('matches_index') is not True)
    m.check(dirty == complete['postimages']['paths'], 'all actual dirty paths match retained final transition')
    git_raw = m.read_input(MAINTENANCE_RUN / 'final.git-state.json', MAINTENANCE_GIT_PIN)
    metadata_gzip = m.read_input(MAINTENANCE_RUN / 'SOURCE_GIT_METADATA.after.json.gz', MAINTENANCE_METADATA_GZIP_PIN)
    metadata_raw = gzip.decompress(metadata_gzip)
    m.pin_bytes(metadata_raw, MAINTENANCE_METADATA_PIN, 'complete current 2654-byte original Git metadata')
    m.check(m.parse(metadata_raw)['root'] == str(m.REPO / '.git'), 'actual metadata belongs to current source')
    artifacts_raw = m.read_input(MAINTENANCE_RUN / 'ARTIFACTS.json', MAINTENANCE_ARTIFACTS_PIN)
    artifact_rows = m.parse(artifacts_raw)['files']
    indexed = {row['name']: row for row in artifact_rows}
    m.check(len(indexed) == len(artifact_rows), 'unambiguous original artifact paths')
    for name, pin in (('final.inventory.json.gz', BASELINE_GZIP_PIN), ('final.git-state.json', MAINTENANCE_GIT_PIN),
                      ('SOURCE_GIT_METADATA.after.json.gz', MAINTENANCE_METADATA_GZIP_PIN),
                      ('INPUT_IDENTITIES.json', MAINTENANCE_INPUTS_PIN)):
        m.check({key: indexed[name][key] for key in ('bytes', 'sha256', 'git_blob')} == pin,
                'complete original artifact binding ' + name)
    for name, pin in (('final.inventory.json.gz', BASELINE),
                      ('SOURCE_GIT_METADATA.after.json.gz', MAINTENANCE_METADATA_PIN)):
        m.check({key: indexed[name]['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')} == pin,
                'complete raw companion identity ' + name)
    inputs_raw = m.read_input(MAINTENANCE_RUN / 'INPUT_IDENTITIES.json', MAINTENANCE_INPUTS_PIN)
    m.check(len(m.parse(inputs_raw)) == inputs_audit['input_count'], 'actual original input-map count')
    lease_raw = m.read_input(EVIDENCE / 'SOURCE_COORDINATION_EX.json', MAINTENANCE_LEASE_PIN)
    lease = m.parse(lease_raw)
    m.check(lease['format'] == 'hepta-source-coordination-exclusive-lease-v1'
            and lease['source_repo'] == str(m.REPO) and lease['path'] == str(LOCK)
            and {key: lease[key] for key in LOCK_ID} == LOCK_ID and lease['created'] is False
            and lease['lock_acquired'] == 'LOCK_EX|LOCK_NB' and lease['inheritable'] is True
            and lease['qualification'] is False, 'historical actual cooperative EX lease only')
    for name, body in (('MAINTENANCE_RESULT.original.json', raw), ('MAINTENANCE_NORMAL.original.json', normal_raw),
                       ('MAINTENANCE_GIT_STATE.original.json', git_raw), ('MAINTENANCE_ARTIFACTS.original.json', artifacts_raw),
                       ('MAINTENANCE_INPUTS.original.json', inputs_raw), ('MAINTENANCE_LEASE.original.json', lease_raw)):
        m.write(name, body)
    m.gzrecord('MAINTENANCE_FINAL_INVENTORY.original.json.gz', inventory_raw)
    m.gzrecord('MAINTENANCE_GIT_METADATA.original.json.gz', metadata_raw)
    return observed, snapshot, m.parse(git_raw), metadata_raw

def prepare(m, control, original):
    m.check(os.getuid() == 1000, 'fixed desktop account')
    current = m.regular_read(__file__, 1000000)
    m.check(control['format'] == 'hepta-final-nonrust-format-approval-v1'
            and control['status'] == 'ROOT_APPROVED_TO_EXECUTE' and control['root_execution_approved'] is True,
            'HOLD: formal source application and final-format approval absent')
    m.check(control['driver'] == identity(current) and control['original_maintenance_driver'] == MAINTENANCE_PIN,
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
    m.input_pins[str(MAINTENANCE)] = MAINTENANCE_PIN
    m.write('ACTUAL_DRIVER.py', current); m.write('MAINTENANCE_594610.original.py', original)
    m.write('APPROVED_CONFIG.original.json', m.regular_read(CONFIG))
    old_cfg_raw = m.read_input(MAINTENANCE_CONFIG, MAINTENANCE_CONFIG_PIN)
    m.cfg = m.parse(old_cfg_raw)  # Only the unchanged environment admission consumes this exact completed-maintenance config.
    m.write('MAINTENANCE_APPROVED_CONFIG.original.json', old_cfg_raw)
    maintenance, prior_snapshot, old_git, old_metadata = prove_actual_maintenance(m)
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
    m.check(m.initial_git_state == old_git, 'exact original Git state unchanged after 41e')
    m.jwrite('SOURCE_GIT_STATE.before.json', m.initial_git_state)
    m.initial_inventory = m.inventory_module.inventory(m.REPO)
    m.pin_bytes(m.initial_inventory, BASELINE, 'actual complete dirty baseline')
    m.gzrecord('SOURCE.before.inventory.json.gz', m.initial_inventory)
    snapshot = m.parse(m.initial_inventory)
    m.check(snapshot == prior_snapshot and snapshot['tracked_entries'] == LEAVES
            and snapshot['filesystem_entries'] == LEAVES, 'actual full baseline source identity and counts')
    leaves = m.actual_leaf_map(m.initial_inventory)
    m.check(len(leaves) == LEAVES and m.merkle(leaves) == BASELINE_TREE, 'actual complete physical baseline tree')
    m.latest_inventory = m.initial_inventory
    m.initial_git_metadata = m.metadata_inventory(m.REPO / '.git')
    m.check(m.initial_git_metadata == old_metadata, 'all original Git metadata bytes unchanged since 41e')
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
    m.result['actual_maintenance_job'] = MAINTENANCE_JOB
    m.result['actual_maintenance_result'] = MAINTENANCE_RESULT_PIN
    m.result['baseline_observation_scope'] = 'Exact 41e final inventory and complete live re-read under this new EX; no new SH73 capture is asserted.'
    m.result['fmt_base'] = m.check_fmt_base()
    m.initial_environment = m.environment_preflight()
    packet_raw = m.read_input(CONTROL / 'NONRUST_PACKET.json', control['nonrust_packet'])
    m.write('NONRUST_PACKET.original.json', packet_raw)
    packet = m.parse(packet_raw)
    m.check(packet['format'] == 'hepta-reviewed-nonrust-source-apply-v1'
            and packet['source_identity'] == prior_snapshot['source'] and packet['base_inventory'] == BASELINE
            and packet['base_physical_tree'] == BASELINE_TREE, 'ordinary reviewed packet exact baseline')
    changes = packet['changes']
    paths = [row['path'] for row in changes]
    safe = {row['path'] for row in prior_snapshot['files'] if row['path'] in NONRUST_PATHS}
    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] == list(NONRUST_PATHS)
            and set(paths) == safe, 'only the four exact approved existing non-Rust paths')
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
    m.check(packet['expected_after_leaf_count'] == control['expected_after_leaf_count'] == len(expected) == LEAVES
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
