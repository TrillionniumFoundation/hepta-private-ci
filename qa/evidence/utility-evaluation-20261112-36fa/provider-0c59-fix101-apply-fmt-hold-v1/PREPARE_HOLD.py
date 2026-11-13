from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1')
RUNTIME = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1')
REPAIR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def put(name, raw):
    p = ROOT / name
    if p.exists():
        assert p.read_bytes() == raw, name
    else:
        with p.open('xb') as f:
            f.write(raw)
    return {'name': name, **pin(raw)}

original = (ROOT / 'ORIGINAL_9101_DRIVER.py').read_bytes()
assert pin(original)['git_blob'] == '9101b44fb2ab24ae41a1344425dd74b536a40de4'
old = original.decode()
proposal_raw = (REPAIR / 'SOURCE_PACKET.json').read_bytes()
assert pin(proposal_raw)['git_blob'] == '12a664ce2905feb8107ae66b303c4975f17a9fe3'
proposal = json.loads(proposal_raw)
artifacts = {r['name']: r for r in json.loads((RUNTIME / 'ARTIFACTS.json').read_bytes())['files']}
three = lambda row: {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
failed_names = ['RESULT.json', 'fix.execute_logged.original.json', 'fix.terminal.json',
                'ARTIFACTS.json', 'SOURCE_GIT_STATE.before.json', 'fix.after.git-state.json',
                'final.git-state.json', 'SOURCE_GIT_METADATA.after.json.gz',
                'final.inventory.json.gz', 'final.postimages.json.gz', 'fix.raw.log']
failed_pins = {}
for name in failed_names:
    path = RUNTIME / name
    if path.exists():
        failed_pins[name] = pin(path.read_bytes())
    else:
        failed_pins[name] = three(artifacts[name])
    if name in artifacts:
        assert failed_pins[name] == three(artifacts[name])
baseline = proposal['actual_baseline_inventory']
witness = proposal['preserved_actual_fix_postimages'][0]
assert len(proposal['changes']) == 4 and len(proposal['preserved_actual_fix_postimages']) == 1
assert witness['path'] == 'codex-rs/hepta-learning-ledger/src/witness.rs'
assert witness['after']['git_blob'] == 'a45cfde5e0d6c17a8b9502f66c43979f26f6bc4d'
raw_meta_pin = pin((RUNTIME / 'SOURCE_GIT_METADATA.after.json').read_bytes())
raw_post_pin = pin((RUNTIME / 'final.postimages.json').read_bytes())
normal_pin = pin((RUNTIME / 'MAIN_STATUS_06.original.json').read_bytes())
maintenance_pin = {'bytes': 68496, 'sha256': 'd47231764a8d85cf60bba499411a08b316798ac6835ae8e7eae95967a79d5259', 'git_blob': '3a0f6dec8127aa9587129d6e0f24bad55837ca13'}
maintenance_config_pin = {'bytes': 13768, 'sha256': 'ccf92346644f428bc66e634c8e4aebe871ed6dcaac354538c1e35862ea83aacf', 'git_blob': 'd27dd8ee763c75eb5a0f195bb034fc9ca32b727e'}

prefix = '''#!/usr/bin/env python3
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
'''
constants = {
    'MAINTENANCE_PIN': maintenance_pin, 'MAINTENANCE_CONFIG_PIN': maintenance_config_pin,
    'BASELINE': baseline, 'WITNESS_PATH': witness['path'], 'WITNESS_PIN': witness['after'],
    'REPAIR_PATHS': [x['path'] for x in proposal['changes']],
    'REPAIR_PROPOSAL_PIN': pin(proposal_raw), 'FAILED_NORMAL_PIN': normal_pin,
    'FAILED_PROOFS': failed_pins, 'FAILED_METADATA_RAW_PIN': raw_meta_pin,
    'FAILED_POSTIMAGES_RAW_PIN': raw_post_pin,
}
for key, value in constants.items():
    prefix += key + ' = ' + repr(value) + '\n'

module = '''def module_from_original():
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
'''

proof = '''def prove_actual_failed_maintenance(m):
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
'''

prepare = '''def prepare(m, control, original):
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
    headers = commit_raw.split(b'\\n\\n', 1)[0].split(b'\\n')
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
'''

tree = ast.parse(old)
lines = old.splitlines(keepends=True)
replacements = {'module_from_original': module, 'prove_actual_clean_source': proof, 'prepare': prepare}
body = ''
for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        block = replacements.get(node.name, ''.join(lines[node.lineno - 1:node.end_lineno]) + '\n')
        if node.name == 'apply_packet':
            block = block.replace('approved non-Rust result', 'approved four-file repair result')
            block = block.replace("m.result['nonrust_application_complete']", "m.result['reviewed_source_repair_complete']")
            block = block.replace('reviewed_nonrust_application_completed', 'reviewed_source_repair_application_completed')
        if node.name == 'retain_terminal':
            block = block.replace('reviewed_nonrust_final_format_terminal', 'reviewed_fix101_repair_format_terminal')
        body += '\n\n' + block.rstrip() + '\n'
main_if = next(n for n in tree.body if isinstance(n, ast.If))
tail = ''.join(lines[main_if.lineno - 1:main_if.end_lineno])
tail = tail.replace('final_nonrust_format_admission_or_retention_error', 'fix101_repair_format_admission_or_retention_error')
driver = (prefix + body + '\n\n' + tail + '\n').encode()
ast.parse(driver.decode())
compile(driver, 'driver-apply-fmt.HOLD.py', 'exec')  # Compile only; never exec definitions or main.
driver_row = put('driver-apply-fmt.HOLD.py', driver)
config = {
    'format':'hepta-fix101-repair-format-approval-v1', 'status':'HOLD_ROOT_EXACT_REVIEW_REQUIRED',
    'root_execution_approved':False, 'driver':pin(driver),
    'original_maintenance_driver':maintenance_pin, 'original_maintenance_config':maintenance_config_pin,
    'source_repo':'/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1',
    'head':proposal['source_identity']['head'], 'head_tree':proposal['source_identity']['tree'],
    'parents':['cc57c7198db6293ccca562253c42fffbe2a04633'],
    'baseline_inventory':baseline,'baseline_physical_tree':proposal['actual_baseline_physical_tree'],
    'leaf_count':15237,'repair_proposal':pin(proposal_raw),'allowed_paths':[x['path'] for x in proposal['changes']],
    'preserved_actual_fix_postimages':[{'path':witness['path'],'mode':witness['mode'],'after':witness['after']}],
    'expected_after_leaf_count':15237,'expected_after_physical_tree':proposal['expected_successor_physical_tree'],
    'fmt_argv':['just','fmt','--base','c0f78493f815780f68b9bf5e390a21314d79311f'],
    'fmt_seconds':900,'preflight_seconds':600,'record_seconds':300,'outer_timeout_seconds':2100,
    'fix_authorized':False,'test_commands_authorized':False,'ref_updates_authorized':False,
    'historical_fix_already_consumed':True,'historical_fix_job':'1a1d3eccd3a-392-231',
    'historical_fix_returncode':101,'prior_fix_reclassification_authorized':False,
}
config_raw = (json.dumps(config, sort_keys=True, indent=2) + '\n').encode()
config_row = put('WAITING_CONFIG.json', config_raw)
diff = ''.join(difflib.unified_diff(old.splitlines(keepends=True),driver.decode().splitlines(keepends=True),fromfile='original-9101.py',tofile='driver-apply-fmt.HOLD.py')).encode()
diff_row = put('FROM_9101.diff',diff)
old_defs = {n.name: ''.join(lines[n.lineno-1:n.end_lineno]) for n in tree.body if isinstance(n,ast.FunctionDef)}
new_lines = driver.decode().splitlines(keepends=True)
new_tree = ast.parse(driver.decode())
new_defs = {n.name: ''.join(new_lines[n.lineno-1:n.end_lineno]) for n in new_tree.body if isinstance(n,ast.FunctionDef)}
scope = {'format':'hepta-fix101-apply-fmt-static-call-scope-v1',
    'original_thin_driver':pin(original),'new_driver':pin(driver),
    'unchanged_definitions':[n for n in old_defs if n in new_defs and old_defs[n]==new_defs[n]],
    'changed_definitions':[n for n in old_defs if n in new_defs and old_defs[n]!=new_defs[n]],
    'removed_definitions':sorted(set(old_defs)-set(new_defs)), 'added_definitions':sorted(set(new_defs)-set(old_defs)),
    'underlying_maintenance_definitions_modified':0,
    'only_new_maintenance_stage_call':"m.stage('fmt', m.FMT, FMT_SECONDS)",
    'never_called':['original maintenance main','original initial_preflight','original validate_config','original validate_materialization_current','fix stage','any test/gate'],
    'historical_materialization_validator_reused':True,
    'current_physical_binding':'actual failed-maintenance final inventory, never the historical clean source argument',
    'actual_original_source_and_git_ns_bytes':'native gzip -> Python bytes/integers, no JavaScript nanosecond reserialization',
    'syntax_compile_only':True,'driver_module_executed':False,'H_calls':0,'source_writes':0,
    'current_subject_is_unqualified':True}
scope_row=put('STATIC_CALL_SCOPE.json',(json.dumps(scope,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'driver':driver_row,'config':config_row,'diff':diff_row,'static':scope_row,'scope':scope},indent=2))
