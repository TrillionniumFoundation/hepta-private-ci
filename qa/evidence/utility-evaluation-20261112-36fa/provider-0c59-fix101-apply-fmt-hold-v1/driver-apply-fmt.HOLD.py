#!/usr/bin/env python3
"""HOLD: apply four reviewed repairs after the consumed fix101, then original fmt.

The exact prior maintenance module supplies the unchanged runtime guard, full
inventory, recorders and one 900-second formatter stage. Its main, fix stage and
clean-materialization initial_preflight are never invoked. The failed original
fix remains failed and consumed; this control does not grant qualification.
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

PREVIOUS = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-maintenance-v1')
PREVIOUS_RUN = PREVIOUS / 'run'
CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-fix101-apply-fmt-v1')
CONFIG = CONTROL / 'APPROVED_CONFIG.json'
OUT = CONTROL / 'run'
LOCK = Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock')
LOCK_ID = {'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1}
MAINTENANCE = PREVIOUS / 'driver-maintenance.py'
MAINTENANCE_CONFIG = PREVIOUS / 'APPROVED_MAINTENANCE_CONFIG.json'
CURRENT_REPO = '/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1'
CURRENT_HEAD = '0c59aaca0b4932507f068c723f73da2f96729b3d'
CURRENT_TREE = '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'
CURRENT_PARENTS = ['cc57c7198db6293ccca562253c42fffbe2a04633']
FAILED_JOB = '1a1d3eccd3a-392-231'
BASELINE_TREE = '4ed32552042fee522965ea54caf95bbebb31ad43'
EXPECTED_APPLY_TREE = '1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1'
LEAVES = 15237
PREFLIGHT_SECONDS = 600
RECORD_SECONDS = 300
FMT_SECONDS = 900
OUTER_SECONDS = 2100
MAINTENANCE_PIN = {'bytes': 68496, 'sha256': 'd47231764a8d85cf60bba499411a08b316798ac6835ae8e7eae95967a79d5259', 'git_blob': '3a0f6dec8127aa9587129d6e0f24bad55837ca13'}
MAINTENANCE_CONFIG_PIN = {'bytes': 13768, 'sha256': 'ccf92346644f428bc66e634c8e4aebe871ed6dcaac354538c1e35862ea83aacf', 'git_blob': 'd27dd8ee763c75eb5a0f195bb034fc9ca32b727e'}
BASELINE = {'bytes': 5629749, 'git_blob': 'd7e2e31df4c8d463b643874bdcd11309a1df02f4', 'sha256': 'b19022cb0957b760703a1193f20b0c2934738e68f7c0cf6956fab34468c41dfa'}
WITNESS_PATH = 'codex-rs/hepta-learning-ledger/src/witness.rs'
WITNESS_PIN = {'bytes': 13300, 'git_blob': 'a45cfde5e0d6c17a8b9502f66c43979f26f6bc4d', 'sha256': 'a7903c5aca69ebda366be3a90869fc83943409c7602da86c4f7f53773eef9154'}
REPAIR_PATHS = ['codex-rs/hepta-agentd/src/authority_host_learning_resident_provider_transport_tests.rs', 'codex-rs/hepta-agentd/src/circuit_original_evaluation_fresh_training_support_tests.rs', 'codex-rs/hepta-agentd/src/circuit_resident_candidate_first_material_support_tests.rs', 'codex-rs/hepta-agentd/src/circuit_resident_candidate_provider_unstarted_material_tests.rs']
REPAIR_PROPOSAL_PIN = {'bytes': 152573, 'sha256': '84b79dd4fc36e070f57f3de05982cd7a55130b5af67f7890a98ad187a1219300', 'git_blob': '12a664ce2905feb8107ae66b303c4975f17a9fe3'}
FAILED_NORMAL_PIN = {'bytes': 910, 'sha256': '80ba7fc0a3ef6b3531b1dd512af833bece7c46f0e52f381ff76d7f759410a8aa', 'git_blob': '5980149603c1ab8f2a4a7aa7f21e9822c28c4c51'}
FAILED_PROOFS = {'RESULT.json': {'bytes': 6574, 'sha256': 'eeef2fb3eed1359272ced60de73861b79752f86235eb7621f40973b0cbd76401', 'git_blob': 'c9ddc9349881689c2825852c746e8235f83cb921'}, 'fix.execute_logged.original.json': {'bytes': 218, 'sha256': 'aac6faadbd3fceb82a7632103c068be6c57a6b1f2222c633938fe67b4bde9e8f', 'git_blob': 'ff6f6805f6f336ce68825793220204ebb333b1b5'}, 'fix.terminal.json': {'bytes': 1391, 'sha256': '85a3a021a3a009ba5f45080390e8b3d9ccdaab37c5c6c569aca3061275692910', 'git_blob': '63b4ec2d123e8eddaeaef3bccc1490285eab8df2'}, 'ARTIFACTS.json': {'bytes': 41231, 'sha256': '9d4fbfbed0635fdbc68d466549a0f0376aa4331c74e25fab328fe76c21b53b8f', 'git_blob': '2f892b28ded54c1fa9b479a22fb544ff8c72d47b'}, 'SOURCE_GIT_STATE.before.json': {'bytes': 489, 'sha256': '34a00b1ea6a7c268b2081a03377d79428ec57fd5586caa89043269ed7fab9660', 'git_blob': '6887b270c7d0c6273c644268d3d260c9aee3aa00'}, 'fix.after.git-state.json': {'bytes': 489, 'sha256': '34a00b1ea6a7c268b2081a03377d79428ec57fd5586caa89043269ed7fab9660', 'git_blob': '6887b270c7d0c6273c644268d3d260c9aee3aa00'}, 'final.git-state.json': {'bytes': 489, 'sha256': '34a00b1ea6a7c268b2081a03377d79428ec57fd5586caa89043269ed7fab9660', 'git_blob': '6887b270c7d0c6273c644268d3d260c9aee3aa00'}, 'SOURCE_GIT_METADATA.after.json.gz': {'bytes': 788, 'sha256': 'c4f804da8488796b3d31b14107d0b5065d5b4751c14300a9a4b8ed8dcfa6bdb3', 'git_blob': '97f706d46e435c0b363ca04b376e76e23e21dbf2'}, 'final.inventory.json.gz': {'bytes': 1265633, 'sha256': '381abec73efc8c28987cff8c81fbf713ed3669c8a9d23444506a75c1ec8614fa', 'git_blob': '107c7e2e2dae02242bee5cad6f3b4eb5056b04e9'}, 'final.postimages.json.gz': {'bytes': 7876, 'sha256': '12bd727f635fd4ce7cba086b28030ddffc3aedcd34b17ea73a2cd8267cbe1b43', 'git_blob': '63b6d2c71df0f04639e57736ae94ad3cb9703121'}, 'fix.raw.log': {'bytes': 128490, 'sha256': 'e5f44de8a9cec68f785de568e24a11be0d68f64a35a64b8ac3d0acc2558332e2', 'git_blob': 'feaf209bf89bcbdc71cdb1787a49c3433745a9cb'}}
FAILED_METADATA_RAW_PIN = {'bytes': 2642, 'sha256': '7549fff731bd055a4dbe895bb0a37fa2486a6e2818e302e8af89495436d704e4', 'git_blob': 'd13c50e149ba23ff1acbd0f99b29669131c1312b'}
FAILED_POSTIMAGES_RAW_PIN = {'bytes': 36709, 'sha256': 'f03d11da7482d4a45e1c92459001b3d3e35a375ded269fb26d634e407cb62d00', 'git_blob': '786b5872a8064d18f6d391b82c7af3813541c0c1'}


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
    module = types.ModuleType('hepta_fix101_retained_original_maintenance')
    module.__file__ = str(MAINTENANCE)
    exec(compile(raw, str(MAINTENANCE), 'exec'), module.__dict__)
    module.check(str(module.REPO) == CURRENT_REPO and module.HEAD == CURRENT_HEAD
                 and module.TREE == CURRENT_TREE and module.PARENTS == CURRENT_PARENTS,
                 'unchanged original module already binds the exact current repository')
    module.OUT = OUT
    module.record_remaining = RECORD_SECONDS
    module.result = {'format': 'hepta-fix101-repair-format-result-v1', 'status': 'HOLD',
                     'source_repo': str(module.REPO), 'source_commit': module.HEAD,
                     'source_tree': module.TREE, 'parents': module.PARENTS,
                     'baseline_physical_tree': BASELINE_TREE, 'baseline_inventory': BASELINE,
                     'test_commands_dispatched': 0, 'qualification': False,
                     'source_ref_updates': False, 'automatic_retry': False,
                     'fix_dispatched': False, 'source_write_attempted': False,
                     'applied_paths': [], 'stages': [], 'cargo_target': str(module.TARGET),
                     'prior_fix_reclassified': False, 'historical_fix_lint_success': False,
                     'budget_scope': 'The prior single fix7200 was consumed and failed101. Only reviewed apply/preflight600, one original fmt900, shared evidence300 and outer2100 are proposed; no fix or tests.'}
    return module, raw


def lock_identity(fd):
    s = os.fstat(fd)
    outside = LOCK.lstat()
    fields = lambda value: {'device': value.st_dev, 'inode': value.st_ino, 'uid': value.st_uid,
                            'mode': stat.S_IMODE(value.st_mode), 'nlink': value.st_nlink}
    if not stat.S_ISREG(s.st_mode) or not stat.S_ISREG(outside.st_mode) or fields(s) != fields(outside) or fields(s) != LOCK_ID:
        raise ValueError('actual same source-coordination inode required')
    return fields(s)


def prove_actual_failed_maintenance(m):
    """Bind the real failed command and actual dirty state without inventing PASS."""
    values = {}
    raw_values = {}
    for name, pin in FAILED_PROOFS.items():
        raw = m.read_input(PREVIOUS_RUN / name, pin)
        raw_values[name] = raw
        m.write('FAILED_MAINTENANCE.' + name, raw)
        if name.endswith('.json'):
            values[name] = m.parse(raw)
    normal_raw = m.read_input(CONTROL / 'FAILED_MAINTENANCE_SUPERVISOR.original.json', FAILED_NORMAL_PIN)
    outer = m.parse(normal_raw)
    m.check(('resultType' not in outer or outer['resultType'] == 'complete')
            and outer.get('isError') is False and len(outer.get('content', [])) == 1
            and outer['content'][0].get('type') == 'text', 'actual failed-maintenance terminal SDK')
    normal = m.parse(outer['content'][0]['text'].encode())
    m.check(normal.get('job_id') == FAILED_JOB and normal.get('state') == 'failed'
            and normal.get('exit_code') == 1 and normal.get('timed_out') is False
            and normal.get('cancelled') is False and normal.get('automatic_retry') is False
            and normal.get('output_complete') is True and normal.get('output_durable') is True
            and normal.get('terminal_publication_confirmed') is True
            and not any(normal.get('log_truncated', {}).values())
            and not any(normal.get('log_errors', {}).values()), 'known complete normal exit1, never PASS')
    m.write('FAILED_MAINTENANCE.NORMAL.original.json', normal_raw)
    observed = values['RESULT.json']; terminal = values['fix.terminal.json']
    execution = values['fix.execute_logged.original.json']
    m.check(observed['format'] == 'hepta-original-scoped-maintenance-result-v1'
            and observed['status'] == 'FAILED_MAINTENANCE'
            and observed['source_repo'] == str(m.REPO) and observed['source_commit'] == CURRENT_HEAD
            and observed['source_tree'] == CURRENT_TREE and observed['parents'] == CURRENT_PARENTS
            and observed['source_preflight_complete'] is True
            and observed['qualification'] is False and observed['test_commands_dispatched'] == 0
            and observed['source_ref_updates'] is False and observed['automatic_retry'] is False
            and observed['attempted_commands'] == ['fix'] and observed['not_run_commands'] == ['fmt'],
            'one actual failed fix and original formatter not attempted')
    m.check(observed['stages'] == [terminal] and terminal['name'] == 'fix'
            and terminal['argv'] == m.FIX and terminal['timeout_seconds'] == m.FIX_SECONDS == 7200
            and terminal['maximum_log_bytes'] == m.MAXIMUM_LOG_BYTES
            and terminal['working_directory'] == str(m.REPO)
            and terminal['status'] == terminal['execution_outcome'] == 'failed'
            and terminal['command_returned'] is True and terminal['execution'] == execution
            and terminal['test_command'] is False and terminal['raw_log_retained'] is True
            and execution['returncode'] == 101 and execution['timed_out'] is False
            and execution['output_limit_exceeded'] is False
            and execution['observed_failed_tests'] == execution['observed_passed_tests'] == 0,
            'original fix terminal and complete log, cost and failure retained')
    raw_log = raw_values['fix.raw.log']
    m.check(len(raw_log) == execution['log_bytes'] and m.sha256(raw_log) == execution['log_sha256'],
            'full original failed command log identity')
    audits = observed['final_audits']
    m.check(len(audits) == 2 and {x['check']: x['status'] for x in audits} ==
            {'actual_complete_source_and_git': 'verified', 'original_inputs': 'verified'}
            and observed['git_metadata_unchanged'] is True, 'actual final Git and input audits')
    by_name = {x['check']: x for x in audits}
    m.check(by_name['original_inputs']['input_count'] == 24 and by_name['original_inputs']['unchanged'] is True
            and by_name['actual_complete_source_and_git']['git_metadata_unchanged'] is True,
            'all24 original inputs and complete original Git metadata retained')
    current = observed['actual_final_source']
    m.check(current == terminal['retention'] == by_name['actual_complete_source_and_git']['complete_final_source']
            and current['complete'] is True and current['inventory'] == BASELINE
            and current['postimages']['change_count'] == 1
            and current['postimages']['paths'] == [WITNESS_PATH]
            and current['postimages']['all_actual_physical_leaf_count'] == LEAVES
            and current['postimages']['all_actual_physical_tree'] == BASELINE_TREE,
            'actual complete failed-fix postimage baseline, only witness changed')
    m.check(observed['actual_materialization_job'] == m.cfg['materialization']['job_id']
            and observed['actual_materialization_result'] == m.cfg['materialization']['result']
            and observed['source_initial_inventory'] == m.cfg['source_inventory'] == m.SUCCESSOR_INVENTORY,
            'failed maintenance belongs to this exact original materialization')
    original_artifacts = values['ARTIFACTS.json']['files']
    artifact_rows = {row['name']: row for row in original_artifacts}
    m.check(len(artifact_rows) == len(original_artifacts), 'unique original failed-run artifact paths')
    for name, pin in FAILED_PROOFS.items():
        if name not in ('RESULT.json', 'ARTIFACTS.json'):
            m.check({key: artifact_rows[name][key] for key in ('bytes', 'sha256', 'git_blob')} == pin,
                    'native ARTIFACTS binds prior original ' + name)
    inventory = gzip.decompress(raw_values['final.inventory.json.gz'])
    metadata = gzip.decompress(raw_values['SOURCE_GIT_METADATA.after.json.gz'])
    postimages = gzip.decompress(raw_values['final.postimages.json.gz'])
    for name, raw, pin in (('final.inventory', inventory, BASELINE),
                           ('final.git-metadata', metadata, FAILED_METADATA_RAW_PIN),
                           ('final.postimages', postimages, FAILED_POSTIMAGES_RAW_PIN)):
        m.pin_bytes(raw, pin, 'actual prior decoded ' + name)
    before_git = values['SOURCE_GIT_STATE.before.json']
    m.check(before_git == values['fix.after.git-state.json'] == values['final.git-state.json']
            == m.cfg['materialization']['git_state'], 'actual prior three raw Git states match materialization')
    packet = m.parse(postimages)
    m.check(packet['format'] == 'hepta-maintenance-actual-source-transition-v1'
            and packet['stage'] == 'final' and packet['source_commit_unchanged'] == CURRENT_HEAD
            and packet['base_inventory_sha256'] == m.SUCCESSOR_INVENTORY['sha256']
            and packet['after_inventory_sha256'] == BASELINE['sha256']
            and packet['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True
            and packet['qualification'] is False and len(packet['changes']) == 1
            and packet['changes'][0]['path'] == WITNESS_PATH, 'complete original witness transition')
    witness = packet['changes'][0]
    witness_raw = base64.b64decode(witness['after_raw_base64'], validate=True)
    m.pin_bytes(witness_raw, WITNESS_PIN, 'actual prior witness bytes are preserved')
    m.result['historical_fix'] = {'job_id': FAILED_JOB, 'result': FAILED_PROOFS['RESULT.json'],
        'supervisor': FAILED_NORMAL_PIN, 'terminal': FAILED_PROOFS['fix.terminal.json'],
        'execution': FAILED_PROOFS['fix.execute_logged.original.json'], 'status': 'failed',
        'returncode': 101, 'timeout_seconds': 7200, 'attempted_count': 1,
        'original_started_at': terminal['started_at'], 'original_finished_at': terminal['finished_at'],
        'already_consumed': True, 'reclassified': False, 'fmt_previously_attempted': False}
    m.result['actual_materialization_job'] = m.cfg['materialization']['job_id']
    m.result['actual_materialization_result'] = m.cfg['materialization']['result']
    return {'inventory': inventory, 'metadata': metadata, 'git_state': before_git,
            'witness': witness, 'witness_raw': witness_raw}


def prepare(m, control, original):
    m.check(os.getuid() == 1000, 'fixed desktop account')
    current = m.regular_read(__file__, 1000000)
    m.check(control['format'] == 'hepta-fix101-repair-format-approval-v1'
            and control['status'] == 'ROOT_APPROVED_TO_EXECUTE' and control['root_execution_approved'] is True,
            'HOLD: exact four-path repair and fmt-only approval absent')
    m.check(control['driver'] == identity(current) and control['original_maintenance_driver'] == MAINTENANCE_PIN
            and control['original_maintenance_config'] == MAINTENANCE_CONFIG_PIN,
            'exact thin driver and byte-unchanged original maintenance/config')
    m.check(control['source_repo'] == str(m.REPO) and control['head'] == m.HEAD and control['head_tree'] == m.TREE
            and control['parents'] == m.PARENTS and control['baseline_inventory'] == BASELINE
            and control['baseline_physical_tree'] == BASELINE_TREE and control['leaf_count'] == LEAVES,
            'actual dirty post-fix baseline and unchanged HEAD identity')
    m.check(control['fmt_argv'] == m.FMT and control['fmt_seconds'] == FMT_SECONDS
            and control['preflight_seconds'] == PREFLIGHT_SECONDS and control['record_seconds'] == RECORD_SECONDS
            and control['outer_timeout_seconds'] == OUTER_SECONDS, 'original fmt and overhead budgets')
    m.check(control['fix_authorized'] is False and control['test_commands_authorized'] is False
            and control['ref_updates_authorized'] is False and control['historical_fix_already_consumed'] is True
            and control['historical_fix_job'] == FAILED_JOB and control['historical_fix_returncode'] == 101
            and control['prior_fix_reclassification_authorized'] is False, 'no fix/test/ref or historical-success fiction')
    m.check(control['preserved_actual_fix_postimages'] == [{'path': WITNESS_PATH, 'mode': '100644', 'after': WITNESS_PIN}],
            'witness exact actual postimage is protected, not manually reapplied')
    m.input_pins[str(Path(__file__))] = identity(current)
    m.input_pins[str(CONFIG)] = identity(m.regular_read(CONFIG))
    m.input_pins[str(MAINTENANCE)] = MAINTENANCE_PIN
    m.write('ACTUAL_DRIVER.py', current); m.write('ORIGINAL_MAINTENANCE_DRIVER.py', original)
    m.write('APPROVED_CONFIG.original.json', m.regular_read(CONFIG))
    old_config_raw = m.read_input(MAINTENANCE_CONFIG, MAINTENANCE_CONFIG_PIN)
    m.cfg = m.parse(old_config_raw)
    m.write('ORIGINAL_MAINTENANCE_CONFIG.json', old_config_raw)
    m.validate_materialization()  # Historical producer proof only; never pass old clean bytes as current source.
    previous = prove_actual_failed_maintenance(m)
    m.inventory_module = m.load_module(m.INVENTORY_FILE, m.INVENTORY_PIN, 'hepta_fix101_original_inventory')
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
                                     'hepta_fix101_original_execute_logged')
    m.initial_git_state = m.git_state()
    m.check(m.initial_git_state == previous['git_state'], 'same current raw HEAD/index/config/refs after failed fix')
    m.jwrite('SOURCE_GIT_STATE.before.json', m.initial_git_state)
    m.initial_inventory = m.inventory_module.inventory(m.REPO)
    m.pin_bytes(m.initial_inventory, BASELINE, 'actual complete dirty post-fix inventory')
    m.check(m.initial_inventory == previous['inventory'], 'current inventory equals actual retained failed-run bytes')
    m.gzrecord('SOURCE.before.inventory.json.gz', m.initial_inventory)
    snapshot = m.parse(m.initial_inventory)
    expected_source = {'head': CURRENT_HEAD, 'tree': CURRENT_TREE, 'status': 'M ' + WITNESS_PATH}
    m.check(snapshot['source'] == expected_source
            and snapshot['tracked_entries'] == snapshot['filesystem_entries'] == LEAVES,
            'exact current source identity with the one real dirty witness')
    dirty_rows = [row for row in snapshot['files'] if row.get('matches_index') is not True]
    m.check(dirty_rows == [previous['witness']['after']], 'only the exact original witness dirty row')
    leaves = m.actual_leaf_map(m.initial_inventory)
    m.check(len(leaves) == LEAVES and m.merkle(leaves) == BASELINE_TREE, 'complete actual before physical tree')
    m.latest_inventory = m.initial_inventory
    m.initial_git_metadata = m.metadata_inventory(m.REPO / '.git')
    m.check(m.initial_git_metadata == previous['metadata'], 'full raw Git metadata unchanged since original final audit')
    m.gzrecord('SOURCE_GIT_METADATA.before.json.gz', m.initial_git_metadata)
    commit_raw = m.git('cat-file', 'commit', CURRENT_HEAD)
    headers = commit_raw.split(b'\n\n', 1)[0].split(b'\n')
    m.check(m.oid('commit', commit_raw) == CURRENT_HEAD and headers[0] == ('tree ' + CURRENT_TREE).encode()
            and [line[7:].decode('ascii') for line in headers if line.startswith(b'parent ')] == CURRENT_PARENTS,
            'actual candidate commit/tree/sole parent, no HEAD or index repair')
    m.write('CURRENT.commit.raw', commit_raw)
    dirty = []
    for row in dirty_rows:
        m.check(row['kind'] == 'file' and row['stable'] is True, 'stable actual dirty file')
        raw = m.read_actual_leaf(row['path'], row)
        m.pin_bytes(raw, WITNESS_PIN, 'complete unchanged actual witness preimage')
        m.check(raw == previous['witness_raw'], 'same actual original witness bytes')
        m.raw_cache[row['working_blob']] = raw
        dirty.append({'row': row, 'raw_base64': base64.b64encode(raw).decode()})
    m.gzrecord('INITIAL_DIRTY_PREIMAGES.json.gz', m.jbytes({'files': dirty, 'source_inventory': BASELINE}))
    m.result['fmt_base'] = m.check_fmt_base()
    m.initial_environment = m.environment_preflight()
    m.check(control['repair_proposal'] == REPAIR_PROPOSAL_PIN, 'one frozen four-file ordinary repair proposal')
    packet_raw = m.read_input(CONTROL / 'REPAIR_PROPOSAL.original.json', REPAIR_PROPOSAL_PIN)
    m.write('REPAIR_PROPOSAL.original.json', packet_raw)
    packet = m.parse(packet_raw)
    m.check(packet['format'] == 'hepta-actual-fix101-minimal-source-repair-proposal-v1'
            and packet['source_identity'] == snapshot['source']
            and packet['actual_baseline_inventory'] == BASELINE
            and packet['actual_baseline_physical_tree'] == BASELINE_TREE
            and packet['actual_maintenance_job'] == FAILED_JOB and packet['source_deletions'] == [],
            'reviewed proposal exact actual failed-run baseline')
    preserved = packet['preserved_actual_fix_postimages']
    m.check(len(preserved) == 1 and preserved[0]['path'] == WITNESS_PATH
            and preserved[0]['mode'] == '100644' and preserved[0]['after'] == WITNESS_PIN
            and preserved[0]['after_text'].encode('utf-8') == previous['witness_raw'],
            'the fifth HEAD delta is retained verbatim, outside the four manual writes')
    changes = packet['changes']; paths = [item['path'] for item in changes]
    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] == REPAIR_PATHS,
            'only four reviewed existing test/support repair paths')
    rows = {row['path']: row for row in snapshot['files']}
    expected = dict(leaves); normalized = []
    for item in changes:
        path = item['path']; row = rows[path]
        m.check(item['mode'] == leaves[path]['mode'] == '100644' and row['kind'] == 'file'
                and row['permissions'] == 0o644 and row['matches_index'] is True,
                'existing normal tracked test/support file, no path or mode expansion')
        before = m.read_actual_leaf(path, row)
        m.pin_bytes(before, item['before'], 'exact actual repair preimage ' + path)
        m.check(before == item['before_text'].encode('utf-8'), 'full original proposal preimage bytes')
        after = item['after_text'].encode('utf-8')
        m.pin_bytes(after, item['after'], 'exact reviewed manual postimage ' + path)
        m.check(after != before, 'no claimed no-op repair')
        m.raw_cache[row['working_blob']] = before
        normalized.append({'path': path, 'mode': item['mode'], 'before': item['before'],
                           'after': item['after'], 'after_base64': base64.b64encode(after).decode('ascii')})
        expected[path] = {'mode': item['mode'], 'sha': item['after']['git_blob'],
                          'bytes': item['after']['bytes'], 'sha256': item['after']['sha256']}
    m.check(expected[WITNESS_PATH] == leaves[WITNESS_PATH], 'manual repair cannot rewrite the retained witness')
    m.check(packet['expected_leaf_count'] == control['expected_after_leaf_count'] == len(expected) == LEAVES
            and packet['expected_successor_physical_tree'] == control['expected_after_physical_tree']
            == m.merkle(expected) == EXPECTED_APPLY_TREE, 'complete approved four-path after-apply tree')
    normalized_packet = {'format': 'hepta-validated-four-path-repair-apply-v1',
                         'source_proposal': REPAIR_PROPOSAL_PIN, 'base_inventory': BASELINE,
                         'expected_after_physical_tree': EXPECTED_APPLY_TREE, 'changes': normalized}
    m.jwrite('VALIDATED_APPLY_PACKET.json', normalized_packet)
    m.verify_original_inputs()
    return normalized_packet, expected


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
    m.check(m.actual_leaf_map(actual) == expected, 'all physical source leaves equal the approved four-file repair result')
    m.check(m.git_state() == m.initial_git_state, 'no index/HEAD/config/ref change by source application')
    m.result['application'] = m.capture_source('apply.after', m.initial_inventory)
    m.check(m.result['application']['postimages']['paths'] == [x['path'] for x in packet['changes']],
            'only exact reviewed application paths changed')
    m.result['reviewed_source_repair_complete'] = True
    m.event('reviewed_source_repair_application_completed', paths=m.result['applied_paths'],
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
    print(json.dumps({'event': 'reviewed_fix101_repair_format_terminal', 'status': m.result['status'],
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
        print(json.dumps({'event': 'fix101_repair_format_admission_or_retention_error', 'status': 'UNKNOWN',
                          'error': repr(error), 'qualification': False}), flush=True)
        code = 1
    sys.exit(code)

