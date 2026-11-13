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
CONTROL = EVIDENCE / 'source-repair-246d-fmt-control-v1'
CONFIG = CONTROL / 'APPROVED_CONFIG.json'
OUT = EVIDENCE / 'source-repair-246d-fmt-v1'
LOCK = EVIDENCE / 'SOURCE_COORDINATION.lock'
LOCK_ID = {'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1}
V5 = EVIDENCE / 'driver-v5.py'
V5_PIN = {'bytes': 63007, 'sha256': 'ff2078884d48dcb92ec3b681d7479c33e9b074d1677108ce60e913c90f002431', 'git_blob': '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'}
V5_CONFIG = EVIDENCE / 'APPROVED_CONFIG_V5.json'
V5_CONFIG_PIN = {'bytes': 9668, 'sha256': '47acb8e9130d497035fad7b90ec0a9c4d0b3277e71c6b9392b75a7107d4599e1', 'git_blob': 'a66ab71a3504f29240da6048ca2c45ca3735e89b'}
CURRENT_HEAD = '246d8cb614770252ee42029a5c014f2a4904176a'
CURRENT_TREE = 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
CURRENT_PARENTS = ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']
CANONICAL_ALIGNMENT = {'job_id': '1a1d1ddc8e4-2564-1c83', 'result': {'bytes': 368586, 'git_blob': '2678be6c23d00696d356e988120887a61f88bfab', 'sha256': '33cd2a23b1bd4a4b7b8ec5d41b5658d3149d701e7096cea00aee6f5d9f2f82c7'}, 'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/final-canonical-alignment-v1/run/RESULT.json', 'supervisor': {'bytes': 910, 'git_blob': '879685b4776ef2f9237587ae20cc8916391504de', 'sha256': '70b7c7ab7c5b895d9fea60f88aa87d7f7ae8aed70483cf83b4ec788a17a68886'}, 'supervisor_path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-246d-v1/CANONICAL_ALIGNMENT_NORMAL.original.json'}
SOURCE_RUN = Path('/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-246d-v1')
SOURCE_JOB = '1a1d1e83bd4-2564-1c86'
SOURCE_PROOFS = {'handoff': {'path': 'source-handoff/RESULT.json', 'bytes': 692, 'sha256': 'd79599e089c55e8b688bc6098d79d02662c5d7bb736400858cdd2427677ba6d8', 'git_blob': '110ab48579e159301900daa663d289964a63bc34'}, 'original_run': {'path': 'source-handoff/ORIGINAL_RUN_RESULT.json', 'bytes': 5082, 'sha256': '4dd23d14599d591b3fa7593797bc8d5d32e2f3e0a440f835774f9419e63b24b1', 'git_blob': '96ca7c7728c7ac3944782abc0d219dd75a8b9f75'}, 'git_after': {'path': 'source-handoff/admission/GIT_STATE.after.json', 'bytes': 489, 'sha256': '21f7d6e2b6c00369df7c9b04b2cee028c851a21a69fcdafdc75ee7c21f4fd0ef', 'git_blob': 'c81a713647d2b0d39eded736f681bc3058139682'}, 'full_comparison': {'path': 'source-handoff/admission/FULL_PHYSICAL_COMPARISON.json', 'bytes': 204, 'sha256': '0e95afa2a439a0d8ecfbdbd120564dfd5acf9d21eab1e47af2a50754438d717c', 'git_blob': '54cc9f6894944027a22b0d8f7ea16a2c978a1d74'}}
SOURCE_NORMAL_PIN = {'bytes': 952, 'sha256': '6499d8231230665037a977da78fe840177325f93b2b1e62f30a146251895d906', 'git_blob': 'bcc7b94d9f9f721f6592632db5a6408468014270'}
REPAIR_PATHS = ['.github/blob-size-allowlist.txt', 'CALLERS.toml', 'qa/b4-no-bypass/test_original_circuit_observer_source_closure.py', 'qa/b4-no-bypass/test_original_selection_readback_source_closure.py', 'qa/b4-no-bypass/test_resident_root_source_closure.py']
V5_JOB = '1a1d16f37be-2564-1c4a'
BASELINE = {'bytes': 5611184, 'sha256': 'df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e', 'git_blob': '663373f936c2ff130aec96ad34654cc9811773c2'}
BASELINE_TREE = CURRENT_TREE
V5_RESULT_PIN = {'bytes': 15927, 'sha256': '50d43cf8e2b3070733405e646f96eb8e17c7e0734cf8f1a7f4b065e68b463e6c', 'git_blob': '28fd9e0970a977881971a3e5c2ddaf73f69a58a0'}
V5_NORMAL_PIN = {'bytes': 956, 'sha256': 'c313aece99eb8d3d7eb95c9d4997b81808c8404062371ab3dc52abb9badcd675', 'git_blob': '2bb8699bae213bd97926beb6589df08e7813c79a'}
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
    module.HEAD = CURRENT_HEAD; module.TREE = CURRENT_TREE; module.PARENTS = CURRENT_PARENTS
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


def prove_actual_clean_source(m):
    """Require the real clean alignment and preserve the completed FAILED gate."""
    aligned_raw = m.read_input(Path(CANONICAL_ALIGNMENT['result_path']), CANONICAL_ALIGNMENT['result'])
    aligned = m.parse(aligned_raw)
    normal_raw = m.read_input(Path(CANONICAL_ALIGNMENT['supervisor_path']), CANONICAL_ALIGNMENT['supervisor'])
    normal = m.parse_supervisor(normal_raw)
    m.check(normal['job_id'] == CANONICAL_ALIGNMENT['job_id']
            and aligned['format'] == 'hepta-final-canonical-alignment-result-v1'
            and aligned['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
            and aligned['source_repo'] == str(m.REPO)
            and aligned['qualification'] is False
            and aligned['physical_source_writes_dispatched'] == 0
            and aligned['cargo_or_formatter_started'] is False
            and aligned['test_commands_dispatched'] == 0
            and aligned['remote_ref_updates'] is False
            and aligned['source_branch_refs_updated'] is False
            and aligned['automatic_retry'] is False, 'actual normal clean canonical alignment')
    m.check({r['check']: r['status'] for r in aligned['final_audits']} ==
            {'source': 'verified', 'git': 'verified', 'inputs': 'verified'}, 'complete canonical audits')
    after = aligned['after']
    m.check(after['commit'] == CURRENT_HEAD and after['tree'] == CURRENT_TREE
            and after['parents'] == CURRENT_PARENTS
            and all(after['inventory'][key] == value for key, value in BASELINE.items())
            and after['inventory']['tracked_entries'] == after['inventory']['filesystem_entries'] == 15188,
            'actual canonical full clean source identity')
    m.check(all(aligned['actual'][key] is True for key in (
            'complete_source_clean', 'detached', 'index_equals_tree', 'normal_stat_refresh_verified',
            'physical_bytes_unchanged', 'physical_modes_unchanged')), 'actual complete canonical properties')
    m.write('CANONICAL_ALIGNMENT.RESULT.original.json', aligned_raw)
    m.write('CANONICAL_ALIGNMENT.NORMAL.original.json', normal_raw)
    values = {}
    for name, item in SOURCE_PROOFS.items():
        raw = m.read_input(SOURCE_RUN / item['path'], item)
        values[name] = m.parse(raw)
        m.write('FAILED_SOURCE.'+name+'.original.json', raw)
    terminal_raw = m.read_input(CONTROL / 'SOURCE_GATES_NORMAL.original.json', SOURCE_NORMAL_PIN)
    outer = m.parse(terminal_raw)
    m.check(('resultType' not in outer or outer['resultType'] == 'complete')
            and outer.get('isError') is False and len(outer.get('content', [])) == 1
            and outer['content'][0].get('type') == 'text', 'actual failed-source terminal SDK')
    terminal = m.parse(outer['content'][0]['text'].encode())
    m.check(terminal.get('job_id') == SOURCE_JOB and terminal.get('state') == 'failed'
            and terminal.get('exit_code') == 1 and terminal.get('timed_out') is False
            and terminal.get('cancelled') is False and terminal.get('automatic_retry') is False
            and terminal.get('output_complete') is True and terminal.get('output_durable') is True
            and terminal.get('terminal_publication_confirmed') is True
            and not any(terminal.get('log_truncated', {}).values()), 'known complete failed source terminal, never PASS')
    handoff = values['handoff']; run = values['original_run']
    m.check(handoff['format'] == 'hepta-final-source-gates-handoff-v1'
            and handoff['status'] == handoff['original_run_status'] == 'failed'
            and handoff['source'] == CURRENT_HEAD and handoff['tree'] == CURRENT_TREE
            and handoff['qualification'] is False and handoff['driver_main_entered'] is True
            and handoff['driver_returncode'] == 1
            and handoff['actual_origin_full_physical_observation'] == {
                'extra_physical_entries': 0, 'full_physical_bytes_equal': True,
                'original_source_rows_unchanged': True}, 'actual failed source run with unchanged origin')
    expected = ['source-closure', 'self-test', 'verify']
    m.check(run['schema'] == 'hepta.utility.desktop-source-gates.v1'
            and run['source_sha'] == CURRENT_HEAD and run['source_tree'] == CURRENT_TREE
            and run['status'] == 'failed' and run['actual_A_B_C_qualification'] is False
            and run['attempted'] == run['entrypoints_started'] == expected and run['not_run'] == []
            and [(r['gate'], r['status']) for r in run['gates']] ==
                [('source-closure', 'failed'), ('self-test', 'passed'), ('verify', 'passed')],
            'all original source gates completed; closure failure is retained')
    for row in run['gates']:
        m.check(row['source_sha'] == CURRENT_HEAD and row['source_changed'] is False
                and row['before_inventory_sha256'] == row['after_inventory_sha256'] ==
                    '4db429ba1d54aa7ed6d6ad199694b7410d654ee7f788a631d7f392d7552fc79b'
                and row['execution_error'] is None and row['record_read_error'] is None
                and row['after_inventory_error'] is None
                and row['lifecycle'] == {'attempted': True, 'entrypoint_started': True,
                                        'package': 'completed', 'terminal_observed': True},
                'complete original gate evidence without source changes')
    m.check(values['git_after'] == after['git_state']
            and values['full_comparison']['full_bytes_equal'] is True
            and values['full_comparison']['original_rows_identical'] is True
            and values['full_comparison']['additional_physical_entries'] == [],
            'source-run actual origin Git and physical source still equal the clean alignment')
    m.write('FAILED_SOURCE.NORMAL.original.json', terminal_raw)
    m.result['previous_source_gate_status'] = 'failed'
    m.result['previous_source_gate_job'] = SOURCE_JOB
    m.result['failed_source_result_retained_without_reclassification'] = True
    return aligned


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
            'actual clean canonical HEAD and complete physical baseline')
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
    aligned = prove_actual_clean_source(m)
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
    m.check(m.initial_git_state == aligned['after']['git_state'], 'exact current Git state unchanged after source gates')
    m.jwrite('SOURCE_GIT_STATE.before.json', m.initial_git_state)
    m.initial_inventory = m.inventory_module.inventory(m.REPO)
    m.pin_bytes(m.initial_inventory, BASELINE, 'actual complete clean canonical baseline')
    m.gzrecord('SOURCE.before.inventory.json.gz', m.initial_inventory)
    snapshot = m.parse(m.initial_inventory)
    m.check(snapshot['source'] == {'head': CURRENT_HEAD, 'tree': CURRENT_TREE, 'status': ''}
            and snapshot['tracked_entries'] == snapshot['filesystem_entries'] == 15188
            and all(row.get('matches_index') is True for row in snapshot['files']),
            'actual complete clean source identity and all index-bound leaves')
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
    m.result['actual_canonical_alignment_job'] = CANONICAL_ALIGNMENT['job_id']
    m.result['actual_maintenance_job'] = V5_JOB
    m.result['fmt_base'] = m.check_fmt_base()
    m.initial_environment = m.environment_preflight()
    packet_raw = m.read_input(CONTROL / 'NONRUST_PACKET.json', control['nonrust_packet'])
    m.write('NONRUST_PACKET.original.json', packet_raw)
    packet = m.parse(packet_raw)
    m.check(packet['format'] == 'hepta-reviewed-nonrust-source-apply-v1'
            and packet['source_identity'] == snapshot['source'] and packet['base_inventory'] == BASELINE
            and packet['base_physical_tree'] == BASELINE_TREE, 'ordinary reviewed packet exact baseline')
    changes = packet['changes']
    paths = [row['path'] for row in changes]
    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] == REPAIR_PATHS,
            'only the five reviewed existing non-Rust source-repair paths')
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
