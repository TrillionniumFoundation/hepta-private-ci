#!/usr/bin/env python3
"""Pure local preparation; never imports or executes either native main."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-preparation-v1')
CANON = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-preparation-v1')
RUNTIME = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')
MAINT = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1')
RECOVERY = Path('/tmp/hepta-36fa-a489-actual-maintenance-source-review-v1')
FENCES = Path('/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1')
NATIVE_REPO = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
NATIVE_MAINT = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1'
NATIVE_CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1'
NATIVE_CANON = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()

def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ('refuse changed preparation artifact', str(path))
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return identity(raw)

def exactly_once(text, before, after):
    assert text.count(before) == 1, ('replacement occurrence', before[:160])
    return text.replace(before, after, 1)

def functions(text):
    lines = text.splitlines(True)
    return {n.name: ''.join(lines[n.lineno-1:n.end_lineno])
            for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

def replace_function(text, name, replacement):
    return exactly_once(text, functions(text)[name], replacement.strip())

original = (ROOT/'inputs/ORIGINAL_NONRUST_FMT_080753.py').read_bytes()
assert identity(original)['git_blob'] == '080753bf6fa5070c0f71096ace0cf199762ee42c'
module_raw = (MAINT/'driver-maintenance.HOLD.py').read_bytes()
assert identity(module_raw)['git_blob'] == '59461030d4160f7ad6a978df5a7b6aaeb33fb2a6'
module_config_raw = (MAINT/'execution-candidate-v1/MAINTENANCE_CONFIG.execution-candidate.json').read_bytes()
assert identity(module_config_raw)['git_blob'] == '7bddb6c423afbe739bc36a7df2516730911a9337'
actual = json.loads((RUNTIME/'RESULT.json').read_bytes())
artifacts = json.loads((RUNTIME/'ARTIFACTS.json').read_bytes())
catalog = {row['name']: row for row in artifacts['files']}
assert len(catalog) == len(artifacts['files'])
baseline_raw = (RECOVERY/'final.inventory.exact_recovered.json').read_bytes()
baseline = json.loads(baseline_raw)
assert identity(baseline_raw) == actual['actual_final_source']['inventory']
fences = json.loads((FENCES/'MANIFEST.json').read_bytes())
apply_paths = sorted(row['path'] for row in fences['fence_bindings'] if row['operation'] == 'modify')
assert apply_paths == ['.github/blob-size-allowlist.txt', 'CALLERS.toml',
                       'qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json',
                       'qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py']
assert fences['base_physical_tree'] == 'c026a8d7e93c958b39a36c666debecb3dba4be14'
assert fences['leaf_count'] == 15243

pins = {
    'MAINTENANCE_PIN': identity(module_raw),
    'MAINTENANCE_CONFIG_PIN': identity(module_config_raw),
    'MAINTENANCE_RESULT_PIN': identity((RUNTIME/'RESULT.json').read_bytes()),
    'MAINTENANCE_NORMAL_PIN': identity((RUNTIME/'STATUS_06.original.json').read_bytes()),
    'MAINTENANCE_GIT_PIN': identity((RUNTIME/'final.git-state.json').read_bytes()),
    'MAINTENANCE_ARTIFACTS_PIN': identity((RUNTIME/'ARTIFACTS.json').read_bytes()),
    'MAINTENANCE_INPUTS_PIN': identity((RUNTIME/'INPUT_IDENTITIES.json').read_bytes()),
    'MAINTENANCE_LEASE_PIN': identity((RUNTIME/'SOURCE_COORDINATION_EX.json').read_bytes()),
    'BASELINE': identity(baseline_raw),
    'BASELINE_GZIP_PIN': {key: catalog['final.inventory.json.gz'][key] for key in ('bytes','sha256','git_blob')},
    'MAINTENANCE_METADATA_GZIP_PIN': {key: catalog['SOURCE_GIT_METADATA.after.json.gz'][key] for key in ('bytes','sha256','git_blob')},
    'MAINTENANCE_METADATA_PIN': {'bytes': catalog['SOURCE_GIT_METADATA.after.json.gz']['raw_bytes'],
                              'sha256': catalog['SOURCE_GIT_METADATA.after.json.gz']['raw_sha256'],
                              'git_blob': catalog['SOURCE_GIT_METADATA.after.json.gz']['raw_git_blob']},
}
assert pins['MAINTENANCE_RESULT_PIN']['git_blob'] == 'b87aed7647ac34e3db0e381110bf685438aee0ee'
assert pins['MAINTENANCE_NORMAL_PIN']['git_blob'] == '70e1866f963a2a2a8d6f3bd468ddd0c291fbf871'

source = original.decode()
source = exactly_once(source,
    'This thin control imports the unchanged, pinned V5 recorder and maintenance\nfunctions. It never calls that module\'s main/initial_preflight/fix. Approval and\nthe ordinary agent\'s final packet are intentionally absent in the draft config.',
    'This thin control imports the exact 594610 recorder and maintenance functions\nused by completed job 41e. It never calls that module\'s main/initial_preflight/fix.\nActual 41e proof and current full bytes replace the historical SH73/V5 binding.\nApproval and the final immutable non-Rust packet remain absent in the HOLD config.')
begin = source.index('EVIDENCE = ')
end = source.index('\n\n\ndef identity(', begin)
globals_text = '\n'.join([
    'EVIDENCE = Path(' + repr(NATIVE_MAINT) + ')',
    'CONTROL = Path(' + repr(NATIVE_CONTROL) + ')',
    "CONFIG = CONTROL / 'APPROVED_CONFIG.json'",
    "OUT = CONTROL / 'run'",
    "LOCK = Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock')",
    "LOCK_ID = {'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1}",
    "MAINTENANCE = EVIDENCE / 'driver-maintenance.py'",
    "MAINTENANCE_CONFIG = EVIDENCE / 'APPROVED_MAINTENANCE_CONFIG.json'",
    "MAINTENANCE_RUN = EVIDENCE / 'run'",
    "MAINTENANCE_JOB = '1a1d47cebc8-392-41e'",
    *[name + ' = ' + repr(pin) for name, pin in pins.items()],
    "BASELINE_TREE = 'c026a8d7e93c958b39a36c666debecb3dba4be14'",
    'LEAVES = 15243',
    'NONRUST_PATHS = ' + repr(tuple(apply_paths)),
    'PREFLIGHT_SECONDS = 600', 'RECORD_SECONDS = 300', 'FMT_SECONDS = 900',
])
source = source[:begin] + globals_text + source[end:]
module_function = functions(source)['module_from_original']
for before, after in [('V5_PIN','MAINTENANCE_PIN'), ('V5','MAINTENANCE'),
                      ('hepta_final_format_original_v5','hepta_final_format_original_594610')]:
    module_function = module_function.replace(before, after)
source = replace_function(source, 'module_from_original', module_function)

proof_function = r'''
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
'''
source = replace_function(source, 'prove_actual_capture', proof_function)
prepare = functions(source)['prepare']
prepare = prepare.replace("control['original_v5_driver'] == V5_PIN", "control['original_maintenance_driver'] == MAINTENANCE_PIN")
prepare = prepare.replace("m.input_pins[str(V5)] = V5_PIN", "m.input_pins[str(MAINTENANCE)] = MAINTENANCE_PIN")
prepare = prepare.replace("m.write('MAINTENANCE_V5.original.py', original)", "m.write('MAINTENANCE_594610.original.py', original)")
start = prepare.index('    old_cfg_raw = ')
finish = prepare.index('    m.inventory_module = ', start)
prepare = prepare[:start] + '''    old_cfg_raw = m.read_input(MAINTENANCE_CONFIG, MAINTENANCE_CONFIG_PIN)
    m.cfg = m.parse(old_cfg_raw)  # Only the unchanged environment admission consumes this exact completed-maintenance config.
    m.write('MAINTENANCE_APPROVED_CONFIG.original.json', old_cfg_raw)
    maintenance, prior_snapshot, old_git, old_metadata = prove_actual_maintenance(m)
''' + prepare[finish:]
prepare = exactly_once(prepare,
    "    old_git = m.parse(m.read_input(EVIDENCE / 'run-v5' / 'final.git-state.json', V5_GIT_PIN))\n    m.check(m.initial_git_state == old_git, 'exact original Git state unchanged after V5')",
    "    m.check(m.initial_git_state == old_git, 'exact original Git state unchanged after 41e')")
prepare = prepare.replace("snapshot['source'] == captured['source_identity']", "snapshot == prior_snapshot")
prepare = prepare.replace('== 15188', '== LEAVES')
prepare = exactly_once(prepare,
    "    m.initial_git_metadata = m.metadata_inventory(m.REPO / '.git')\n    m.gzrecord('SOURCE_GIT_METADATA.before.json.gz', m.initial_git_metadata)",
    "    m.initial_git_metadata = m.metadata_inventory(m.REPO / '.git')\n    m.check(m.initial_git_metadata == old_metadata, 'all original Git metadata bytes unchanged since 41e')\n    m.gzrecord('SOURCE_GIT_METADATA.before.json.gz', m.initial_git_metadata)")
prepare = exactly_once(prepare,
    "    m.result['actual_capture_job'] = CAPTURE_JOB\n    m.result['actual_maintenance_job'] = V5_JOB",
    "    m.result['actual_maintenance_job'] = MAINTENANCE_JOB\n    m.result['actual_maintenance_result'] = MAINTENANCE_RESULT_PIN\n    m.result['baseline_observation_scope'] = 'Exact 41e final inventory and complete live re-read under this new EX; no new SH73 capture is asserted.'")
prepare = prepare.replace("packet['source_identity'] == captured['source_identity']", "packet['source_identity'] == prior_snapshot['source']")
old_safe = """    safe = {row['path'] for row in capture_packet['files'] if
            row['path'] in ('CALLERS.toml', '.github/blob-size-allowlist.txt') or
            (row['path'].startswith('qa/b4-no-bypass/') and row['path'].endswith('.py'))}"""
new_safe = """    safe = {row['path'] for row in prior_snapshot['files'] if row['path'] in NONRUST_PATHS}"""
prepare = exactly_once(prepare, old_safe, new_safe)
prepare = exactly_once(prepare,
    "    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] and paths\n            and set(paths) <= safe, 'exact approved existing non-Rust paths only')",
    "    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] == list(NONRUST_PATHS)\n            and set(paths) == safe, 'only the four exact approved existing non-Rust paths')")
source = replace_function(source, 'prepare', prepare)
assert not any(name in source for name in ('CAPTURE_JOB', 'V5_RESULT_PIN', 'V5_GIT_PIN', 'capture_packet'))
compile(source, 'driver.HOLD.py', 'exec')
driver_pin = save(ROOT/'driver.HOLD.py', source.encode())
save(ROOT/'FROM_080753.diff', ''.join(difflib.unified_diff(original.decode().splitlines(True), source.splitlines(True),
    fromfile='original-080753.py', tofile='driver.HOLD.py')).encode())
original_functions = functions(original.decode())
new_functions = functions(source)
unchanged = [name for name, value in original_functions.items() if name in new_functions and new_functions[name] == value]
assert unchanged == ['identity','first_read','lock_identity','apply_packet','retain_terminal','main']
assert set(original_functions) - set(unchanged) == {'module_from_original','prove_actual_capture','prepare'}
save(ROOT/'STATIC_CALL_SCOPE.json', encode({
    'format':'hepta-final-nonrust-thin-static-scope-v1',
    'original_080753':identity(original), 'thin_driver':driver_pin,
    'unchanged_exact_function_bodies':unchanged,
    'adapted_functions':['module_from_original','prepare'],
    'replaced_proof_function':{'before':'prove_actual_capture','after':'prove_actual_maintenance'},
    'imported_module':identity(module_raw), 'imported_module_bytes_modified':False,
    'imported_main_called':False,'imported_initial_preflight_called':False,'imported_validate_config_called':False,
    'fix_dispatched':False,'test_commands_dispatched':0,'H_calls':0,
    'single_lock_owner':'Original unchanged thin main opens and holds one EX. Future staging/bootstrap must not acquire another EX.',
    'original_budgets':{'preflight_and_apply':600,'fmt':900,'retention':300,'outer':2100},
    'explicit_scope_delta':'The historical 73-file capture is not replayed or claimed. Actual 41e complete inventory/full current source and four exact existing paths bind this successor. The one precise existing contract JSON is allowed; no general JSON allowance.',
}))
hold = {
    'format':'hepta-final-nonrust-format-approval-v1','status':'HOLD_ROOT_EXACT_REVIEW_REQUIRED',
    'root_execution_approved':False,'driver':driver_pin,'original_maintenance_driver':pins['MAINTENANCE_PIN'],
    'source_repo':NATIVE_REPO,'head':actual['source_commit'],'head_tree':actual['source_tree'],
    'baseline_inventory':pins['BASELINE'],'baseline_physical_tree':fences['base_physical_tree'],
    'fmt_argv':actual['stages'][1]['argv'],'fmt_seconds':900,'preflight_seconds':600,'record_seconds':300,
    'outer_seconds':2100,'fix_authorized':False,'test_commands_authorized':False,'ref_updates_authorized':False,
    'nonrust_packet':None,'allowed_paths':apply_paths,'expected_after_leaf_count':15243,
    'expected_after_physical_tree':None,
    'actual_prior_maintenance':{'job_id':'1a1d47cebc8-392-41e','result':pins['MAINTENANCE_RESULT_PIN'],
        'supervisor':pins['MAINTENANCE_NORMAL_PIN'],'git_state':pins['MAINTENANCE_GIT_PIN'],
        'complete_git_metadata':pins['MAINTENANCE_METADATA_PIN']},
    'root_input_review':None,'source_peer_review':None,
    'waiting_for':['Strict immutable four-path packet, source peer and Root exact input/launcher review'],
    'native_calls_dispatched':0,
}
save(ROOT/'WAITING_CONFIG.json', encode(hold))
save(ROOT/'INPUT_BINDINGS.json', encode({'format':'hepta-last-nonrust-original-bindings-v1',
    'actual_maintenance_job':'1a1d47cebc8-392-41e','pins':pins,'native_source':NATIVE_REPO,
    'native_prior_records':NATIVE_MAINT+'/run','proposed_create_only_control':NATIVE_CONTROL,
    'proposed_four_staged_files':['driver.py','APPROVED_CONFIG.json','NONRUST_PACKET.json','MAINTENANCE_NORMAL.original.json'],
    'future_native_request':None,'future_actual_result':None,'qualification':False,
    'baseline_inventory_origin':'Complete original bytes exactly recovered offline and matched to actual 41e ARTIFACTS raw/gzip/part identities. Runtime will read the existing original gzip and independently recapture every current physical source leaf.'}))

canon_original = (ROOT/'inputs/ORIGINAL_CANONICAL_765ADA.py').read_bytes()
assert identity(canon_original)['git_blob'] == '765ada67a33f4d9aeaf29c9c522898057083cafb'
canon = canon_original.decode()
substitutions = [
    ("REPO = pathlib.Path('/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1')", 'REPO = pathlib.Path('+repr(NATIVE_REPO)+')'),
    ("CONTROL = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/final-canonical-alignment-v1')", 'CONTROL = pathlib.Path('+repr(NATIVE_CANON)+')'),
    ("INVENTORY = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/inventory-driver-v2.py')", 'INVENTORY = pathlib.Path('+repr(NATIVE_MAINT+'/inventory-driver.original.py')+')'),
    ("OLD = '9c4a11f61d30e9cc352bf44d56c98909d202a55d'", "OLD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'"),
    ("OLD_TREE = 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'", "OLD_TREE = 'a489b394666b8141840275128a780605b024cde0'"),
    ("OLD_PARENTS = ['86dd56a930277e0d1aef3e475e35c2b5d60b43b7']", "OLD_PARENTS = ['cc57c7198db6293ccca562253c42fffbe2a04633']"),
    ('LEAVES = 15188','LEAVES = 15243'),
]
for before,after in substitutions:canon=exactly_once(canon,before,after)
inverse=canon
for before,after in reversed(substitutions):inverse=exactly_once(inverse,after,before)
assert inverse.encode()==canon_original
assert functions(canon)==functions(canon_original.decode())
assert len(functions(canon))==46
compile(canon,'canonical-driver.HOLD.py','exec')
canon_pin=save(CANON/'driver.HOLD.py',canon.encode())
save(CANON/'FROM_765ADA.diff',''.join(difflib.unified_diff(canon_original.decode().splitlines(True),canon.splitlines(True),
    fromfile='original-765ada.py',tofile='driver.HOLD.py')).encode())
save(CANON/'EXACT_CONSTANT_SUBSTITUTIONS.json',encode({'original':identity(canon_original),'candidate':canon_pin,
    'substitutions':[{'before':before,'after':after}for before,after in substitutions],
    'inverse_equal':True,'unchanged_function_count':46,'native_calls':0}))
canonical_cfg={
    'format':'hepta-final-canonical-alignment-config-v1','status':'HOLD_ACTUAL_FINAL_FORMAT_AND_ROOT_CANONICAL_INPUTS',
    'root_execution_approved':False,'source_repo':NATIVE_REPO,'control_dir':NATIVE_CANON,'output_dir':NATIVE_CANON+'/run',
    'driver':canon_pin,'before_commit':actual['source_commit'],'before_tree':actual['source_tree'],'before_parents':actual['parents'],
    'action_seconds':600,'record_seconds':180,'outer_seconds':900,'complete_leaf_count':15243,
    'physical_source_writes_authorized':False,'dependency_installation_authorized':False,
    'cargo_or_formatter_authorized':False,'test_commands_authorized':False,'remote_ref_updates_authorized':False,
    'after_commit':None,'after_tree':None,'after_parents':None,'before_inventory':None,'after_inventory':None,
    'expected_before_git_state':None,'canonical_packet':None,'canonical_object_count':None,
    'reviewed_formatter_changed_paths':None,'actual_final_postimages_reviewed':False,
    'final_format':{'job_id':None,'result_path':NATIVE_CONTROL+'/run/RESULT.json','result':None,
                    'supervisor_path':NATIVE_CANON+'/FINAL_FORMAT_NORMAL.original.json','supervisor':None,
                    'git_state_path':NATIVE_CONTROL+'/run/final.git-state.json','git_state':None},
    'qualification':False,'not_an_execution_approval':True,
}
save(CANON/'WAITING_CONFIG.json',encode(canonical_cfg))
save(CANON/'PLAN.HOLD.json',encode({'format':'hepta-d256-last-canonical-alignment-plan-v1','status':'HOLD',
    'original_driver':identity(canon_original),'driver':canon_pin,'unchanged_function_count':46,
    'exact_constant_changes':7,'source_repo':NATIVE_REPO,'before_commit':actual['source_commit'],
    'before_tree':actual['source_tree'],'before_parents':actual['parents'],'complete_leaf_count':15243,
    'requires_actual_successful_final_nonrust_fmt':True,
    'successor_consumer_contract':'Original 765ada validate_final_format remains byte-identical and consumes hepta-reviewed-nonrust-final-format-result-v1, with actual one fmt900, three final audits, full physical inventory and exact Git state. No old fix101 exception is used.',
    'physical_source_writes':False,'remote_ref_updates':False,'test_or_formatter_commands':False,
    'permitted_future_mutations':['Only missing exact approved canonical objects','Full normal index read-tree without -u/-m/--reset and explicit stat refresh','write-tree exact approved root','Detached HEAD CAS after all original checks'],
    'scope':'The original whole-source, independent object closure, raw index, metadata allowlist, input and same-lock audits remain unchanged. Existing historical current metadata and later canonical metadata are kept separate.',
    'limits':'Original 600/180/900 budgets and original child cleanup behavior are preserved; no new claim of stronger process cleanup is made.',
    'pending':['Actual final nonRust+fmt normal/result/full inventory/postimages review','Root canonical authentic commit/tree/parents and bounded object packet','Exact four-input staging/typed request and Root approval'],
    'future_native_request':None,'H_calls':0,'qualification':False}))
print(json.dumps({'nonrust_driver':driver_pin,'canonical_driver':canon_pin,'functions_unchanged_nonrust':unchanged,
                  'functions_unchanged_canonical':46,'paths':apply_paths,'config_approved':False,'H_calls':0},indent=2))
