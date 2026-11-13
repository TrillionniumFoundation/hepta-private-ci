#!/usr/bin/env python3
"""Review only frozen bytes and captured JSON. No input module import or native I/O."""
from pathlib import Path
import ast
import copy
import difflib
import hashlib
import json
import os
import re

HERE = Path(__file__).resolve().parent
OLD = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')
AUTHOR = Path('/tmp/hepta-36fa-final-qualification-admission-actual-binding-v1')
INDEX_PEER = Path('/tmp/hepta-36fa-canonical-5a9-index-metadata-independent-peer-v1')
RUNTIME = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
RECOVERY = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1')
CANONICAL_INPUTS = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(path, expected=None):
    raw = path.read_bytes()
    if expected is not None:
        assert identity(raw)['git_blob'] == expected, (str(path), identity(raw))
    return raw


def obj(sdk):
    value = sdk['structuredContent']
    return value.get('structuredContent', value)


def differences(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict):
        assert before.keys() == after.keys(), path
        rows = []
        for key in sorted(before):
            rows.extend(differences(before[key], after[key], path + '/' + key))
        return rows
    return [] if before == after else [{'path': path, 'before': before, 'after': after}]


def enc(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


input_pins = {
    'QUALIFICATION_CONFIG.HOLD.json': '083694f6a08cb7a9fbaeea2227b2f60f8608219a',
    'SOURCE_GATES_CONFIG.HOLD.json': '0d3c48853572dc89a823ca9afb5d5487868189e6',
    'CONFIG_DELTA.patch': 'bbd010763051eb402f03ac4c59f2940ecd211e21',
    'FIELD_CHANGES.json': 'e49c946202fcc11b4d5b56359bad0ba69cd09433',
    'PURE_CAPTURED_PREDICATE_REVIEW.json': '0fb5501082685edb815fd6a5a9948ca4c1bb8f27',
}
actual_pins = {
    'CANONICAL_NORMAL.original.json': '2deafbe4bfc7ad2c84d9e6315c12aaa6493adab2',
    'COMMANDS.json': '42892d9ac0723d2db86f9f0bda89ad822311b06a',
    'MUTATION_PROGRESS.json': '530806cf0cbf1922c6e2c2dfea152a94967928f4',
    'INPUTS.final.json': '47477f42fd23094aae63beca190bd42def89fd08',
    'CANONICAL_APPROVED_CONFIG.original.json': '0f69f739486c1dc3506f61c0e8a6ef3737fbe17e',
}
get_rows = []
for folder, pins in [('inputs', input_pins), ('actual-inputs', actual_pins)]:
    for name, expected in pins.items():
        raw = read(HERE / folder / name, expected)
        sdk = json.loads(read(HERE / 'github' / (name + '.GET.original.json')))
        assert not sdk.get('isError') and obj(sdk)['content'].encode() == raw
        get_rows.append({'name': name, **identity(raw), 'actual_full_get_equal': True})

old_cfg_raw = read(OLD / 'QUALIFICATION_CONFIG.HOLD.json', '460139b9ce065184a0809def0823d8d20c45fe41')
old_source_raw = read(OLD / 'SOURCE_GATES_CONFIG.HOLD.json', 'e908def6523ea6bbca2381832297d76ea5178073')
code = read(OLD / 'qualification-admission.HOLD.py', 'c77e3be6230d3267c08333be582f69f23c016fb9')
cfg_raw = read(HERE / 'inputs' / 'QUALIFICATION_CONFIG.HOLD.json')
source_raw = read(HERE / 'inputs' / 'SOURCE_GATES_CONFIG.HOLD.json')
cfg, source_cfg = json.loads(cfg_raw), json.loads(source_raw)
old_cfg, old_source_cfg = json.loads(old_cfg_raw), json.loads(old_source_raw)
field_changes = json.loads(read(HERE / 'inputs' / 'FIELD_CHANGES.json'))
qchanges = differences(old_cfg, cfg)
schanges = differences(old_source_cfg, source_cfg)
assert qchanges == field_changes['qualification_changes'] and len(qchanges) == 39
assert schanges == field_changes['source_gate_changes'] and len(schanges) == 6
patch = b''
for name, before, after in [('QUALIFICATION_CONFIG.HOLD.json', old_cfg_raw, cfg_raw),
                            ('SOURCE_GATES_CONFIG.HOLD.json', old_source_raw, source_raw)]:
    patch += ''.join(difflib.unified_diff(before.decode().splitlines(keepends=True),
                                        after.decode().splitlines(keepends=True),
                                        fromfile='frozen-c77e-layer/' + name,
                                        tofile='actual-5a9-layer/' + name)).encode()
assert read(HERE / 'inputs' / 'CONFIG_DELTA.patch') == patch

untouched = [key for key in sorted(cfg) if cfg[key] == old_cfg[key]]
for key in ('runtime_guard', 'coordination_lock', 'isolated_materialization', 'actual_maintenance',
            'final_format', 'archive_restoration', 'admission_pin', 'native_driver_pin', 'plan_pin',
            'historical_source_repo', 'provenance_donor_repo', 'repo', 'target'):
    assert key in untouched, key
assert cfg['normal_native_and_source_results'] is None
assert cfg['qualification_execution_dispatched'] is False
assert cfg['root_execution_approved'] is False and cfg['not_an_execution_approval'] is True
assert cfg['state'] == source_cfg['state'] == 'HOLD_FOR_EXACT_ROOT_QUALIFICATION_APPROVAL'
assert cfg['admission_pin'] == identity(code)
assert cfg['source_gates_config_pin'] == identity(source_raw)
assert source_cfg['budgets_seconds'] == old_source_cfg['budgets_seconds'] == {
    'source-closure': 600, 'self-test': 300, 'verify': 4800}

# Extract literal constants and these eight data-only functions, never a class,
# constructor, loader, observer, source/native entrypoint, acquire or finish.
tree = ast.parse(code)
constants, definitions = {}, {}
for node in tree.body:
    if isinstance(node, ast.Assign):
        assert len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        if isinstance(node.value, ast.Call):
            assert isinstance(node.value.func, ast.Name) and node.value.func.id == 'Path'
            assert len(node.value.args) == 1 and not node.value.keywords
            constants[node.targets[0].id] = Path(ast.literal_eval(node.value.args[0]))
        else:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
    elif isinstance(node, ast.FunctionDef):
        definitions[node.name] = node
    elif isinstance(node, ast.ClassDef):
        for method in node.body:
            if isinstance(method, ast.FunctionDef):
                definitions[node.name + '.' + method.name] = method
pure = ['check', 'exact_pin', 'pin_fields', 'audited', 'canonical_to_v5_projection',
        'native_projection', 'Admission._require_complete_bindings', 'Admission._check_canonical']
ns = {'Path': Path, 'hashlib': hashlib, 'json': json, 'os': os, 're': re, **constants}
for name in pure:
    node = copy.deepcopy(definitions[name]); node.decorator_list = []
    assert not any(isinstance(n, ast.Call) and ast.unparse(n.func) in
                   {'open', 'os.open', 'os.mkdir', 'exec', 'eval', 'compile', 'Path.read_bytes'}
                   for n in ast.walk(node)), name
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<selected-frozen-pure-data>', 'exec'), ns)
ns['_require_complete_bindings'](cfg)

old_peer = json.loads(read(INDEX_PEER / 'INDEX_METADATA_DATAFLOW.json', '6f7995ceedad50b72f6b5298a39cccf973cc1a1a'))
old_review = read(INDEX_PEER / 'REVIEW.json', 'e8c87c9ef2dfb09f1db40533b675b4032c852f9d')
result_raw = read(INDEX_PEER / 'inputs' / 'RESULT.json', '5aa9590a7b68504bd58ad0d0b889605c7e8ad71d')
catalog_raw = read(INDEX_PEER / 'inputs' / 'ARTIFACTS.json', '84efb7055e5f8d4bbb5d37e1fa93769d36e69ded')
aligned, artifacts = json.loads(result_raw), json.loads(catalog_raw)
catalog = {row['name']: row for row in artifacts}
assert len(catalog) == len(artifacts)
proof = cfg['canonical_alignment']
assert proof['result'] == identity(result_raw) and proof['artifacts'] == identity(catalog_raw)
assert artifacts == aligned['artifacts'] + [dict(identity(result_raw), name='RESULT.json')]
control_raw = read(HERE / 'actual-inputs' / 'CANONICAL_APPROVED_CONFIG.original.json')
control = json.loads(control_raw)
final_format_raw = read(OLD / 'inputs' / 'FINAL_FORMAT_50F_RESULT.json', '800869ed57256984964dd3c8b9f29e09c496438a')
final_format = json.loads(final_format_raw)
ns['_check_canonical'](aligned, final_format, cfg, control)

normal_raw = read(HERE / 'actual-inputs' / 'CANONICAL_NORMAL.original.json')
normal_sdk = json.loads(normal_raw)
assert not normal_sdk['isError'] and normal_sdk['structuredContent'] is None
assert len(normal_sdk['content']) == 1 and normal_sdk['content'][0]['type'] == 'text'
normal = json.loads(normal_sdk['content'][0]['text'])
assert normal['job_id'] == proof['job_id'] == '1a1d4cbd33e-392-5a9'
assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert not normal['timed_out'] and not normal['cancelled'] and not normal['automatic_retry']
assert all(normal[key] is True for key in ('output_complete', 'output_durable', 'terminal_publication_confirmed', 'audit_recorded'))
assert all(normal['log_bytes'][stream]['seen'] == normal['log_bytes'][stream]['stored']
           and normal['log_synced'][stream] is True and normal['log_errors'][stream] is None
           and normal['log_truncated'][stream] is False for stream in ('stdout', 'stderr'))
assert proof['supervisor'] == identity(normal_raw)

pin_map = {
    'allowed_metadata_delta': ('GIT_METADATA.allowed-actual-delta.json', False),
    'before_git_metadata_raw': ('GIT_METADATA.before.json.gz', True),
    'final_git_metadata_raw': ('GIT_METADATA.final.json.gz', True),
    'final_git_metadata_gzip': ('GIT_METADATA.final.json.gz', False),
    'complete_entry_delta': ('INDEX.complete-entry-delta.json.gz', True),
    'final_index_raw': ('INDEX.final.raw.gz', True),
    'final_index_audit': ('INDEX.final.audit.json.gz', True),
    'commands': ('COMMANDS.json', False), 'progress': ('MUTATION_PROGRESS.json', False),
    'inputs': ('INPUTS.final.json', False),
}
pin_checks = []
for key, (name, raw_flag) in pin_map.items():
    prefix = 'raw_' if raw_flag else ''
    pin = {field: catalog[name][prefix + field] for field in ('bytes', 'sha256', 'git_blob')}
    assert proof[key] == pin, key
    pin_checks.append({'config_field': 'canonical_alignment.' + key, 'original_artifact': name,
                       'raw_projection': raw_flag, 'pin': pin})
for name, key in [('COMMANDS.json', 'commands'), ('MUTATION_PROGRESS.json', 'progress'), ('INPUTS.final.json', 'inputs')]:
    raw = read(HERE / 'actual-inputs' / name)
    assert identity(raw) == proof[key]
commands = json.loads(read(HERE / 'actual-inputs' / 'COMMANDS.json'))
intents = json.loads(read(HERE / 'actual-inputs' / 'MUTATION_PROGRESS.json'))
assert commands == aligned['commands'] and intents == aligned['mutation_intents']
assert len(commands) == 94 and len(intents) == 33
inputs = json.loads(read(HERE / 'actual-inputs' / 'INPUTS.final.json'))
canonical_control = str(constants['CANONICAL_CONTROL'])
assert inputs[canonical_control + '/driver.py'] == constants['CANONICAL_DRIVER_PIN']
assert inputs[canonical_control + '/APPROVED_CONFIG.json'] == proof['approved_config'] == identity(control_raw)
packet_raw = read(CANONICAL_INPUTS / 'CANONICAL_PACKET.json', 'bb4b4abd809047be4c9402b95fa2a2dc30b2ab78')
assert inputs[canonical_control + '/CANONICAL_PACKET.json'] == proof['canonical_packet'] == identity(packet_raw)

clean_raw = read(RECOVERY / 'SOURCE.final.inventory.exact_recovered.json', '457adb9bf9ba3a844e9dfa149be49460bb306998')
clean = json.loads(clean_raw)
assert identity(clean_raw) == cfg['full_physical_inventory']
assert clean['source'] == {'head': cfg['source'], 'tree': cfg['tree'], 'status': ''}
assert clean['tracked_entries'] == clean['filesystem_entries'] == len(clean['files']) == 15243
assert all(row['matches_index'] is True for row in clean['files'])
native_expected = ns['native_projection'](clean)
assert identity(native_expected) == cfg['full_native_inventory']
assert cfg['expected_inventory_sha256'] == identity(native_expected)['sha256']
rows = {row['path']: row for row in clean['files']}
workflow = cfg['source_control_pin_overrides'][0]
assert workflow['final_actual_confirmed'] is True
assert dict(workflow, final_actual_confirmed=False) == old_cfg['source_control_pin_overrides'][0]
row = rows[workflow['path']]
assert {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']} == workflow['reviewed_current_pin']
plan_raw = read(OLD / 'inputs' / 'PLAN_3AEF.json', '3aefbc71d69d8014eed9e5a18269bbcc866a7583')
plan = json.loads(plan_raw)
original_controls = plan['unchanged_original_controls']['reviewed_source_pins']['files']
assert len(original_controls) == 12
for original in original_controls:
    expected = workflow['reviewed_current_pin'] if original['path'] == workflow['path'] else original
    row = rows[original['path']]
    assert all(row[k] == expected[k] for k in ('bytes', 'sha256'))
    assert row['index_blob'] == row['working_blob'] == expected['git_blob']

metadata_raw = read(INDEX_PEER / 'inputs' / 'GIT_METADATA.final.json', 'f4032cd8f6c1cceb7c46085664d8a28f24a1a31d')
assert identity(metadata_raw) == cfg['canonical_complete_git_metadata'] == proof['final_git_metadata_raw']
projected = ns['canonical_to_v5_projection'](json.loads(metadata_raw))
assert projected == read(INDEX_PEER / 'CANONICAL_FINAL_V5_PROJECTION.derived.json', '8d4b2850c10642466b55471af2191f2a5c5332fa')
index_raw = read(RUNTIME / 'artifacts' / 'INDEX.final.raw', 'fb90fea0dfd1896de5d9737f529c4999728f9a28')
assert identity(index_raw) == cfg['canonical_original_index'] == proof['final_index_raw']
assert cfg['current_final_git_state'] == json.loads(read(INDEX_PEER / 'inputs' / 'GIT_STATE.final.json')) == aligned['after']['git_state']
assert all(source_cfg[k] == cfg[v] for k, v in [('object_repository', 'repo'), ('source_sha', 'source'), ('source_tree', 'tree'), ('run_identity', 'run_identity')])
expected_paths = {
    'admission_path': CONTROL + '/qualification-admission.py', 'plan_path': CONTROL + '/PLAN.original.json',
    'native_driver_path': CONTROL + '/native-driver.original.py', 'records': CONTROL + '/native-records',
    'source_gates_config_path': CONTROL + '/SOURCE_GATES_CONFIG.json',
    'source_gates_handoff_records': CONTROL + '/source-handoff',
    'root_parent': '/run/hepta-utility-36fa-final-b608-v1',
}
assert all(cfg[key] == value for key, value in expected_paths.items())
assert proof['supervisor_path'] == CONTROL + '/CANONICAL_SUPERVISOR.original.json'
assert source_cfg['records'] == CONTROL + '/source-gates-records'
assert source_cfg['source_checkout'] == '/home/qian-qi/hepta-utility-36fa-source-gates-b608-v1'

# Evaluate only the existing admission constructor's first, pure guard expression.
# Do not invoke or compile the constructor body.
first_guard = definitions['Admission.__init__'].body[0]
assert isinstance(first_guard, ast.Expr) and isinstance(first_guard.value, ast.Call)
assert ast.unparse(first_guard.value.func) == 'check'
condition = first_guard.value.args[0]
assert eval(compile(ast.Expression(condition), '<only-existing-pure-state-expression>', 'eval'), {}, {'cfg': cfg}) is False
assert source_cfg['state'] != 'READY_FOR_EXACT_SOURCE_RUN'

out = {
    'format': 'hepta-actual-binding-independent-dataflow-v1',
    'input_full_get': get_rows,
    'frozen_code': identity(code), 'before_config': identity(old_cfg_raw), 'after_config': identity(cfg_raw),
    'before_source_config': identity(old_source_raw), 'after_source_config': identity(source_raw),
    'complete_diff_byte_equal': True, 'no_configuration_keys_added_or_removed': True,
    'qualification_changes': qchanges, 'source_gate_changes': schanges,
    'unchanged_qualification_subtrees': untouched,
    'extracted_pure_functions': pure, 'pure_binding_and_canonical_predicates_accept_actual_captured_data': True,
    'canonical_pins_equal_original_catalog': pin_checks,
    'canonical_normal': {'pin': identity(normal_raw), 'job_id': normal['job_id'], 'complete_actual_terminal': True},
    'complete_commands_equal_result': 94, 'complete_intents_equal_result': 33,
    'full_actual_clean_inventory': identity(clean_raw), 'expected_only_native_projection': identity(native_expected),
    'actual_full_metadata': identity(metadata_raw), 'derived_only_v5_projection': identity(projected),
    'actual_index': identity(index_raw),
    'prior_independent_index_metadata_review': identity(old_review),
    'source_control_inventory_bindings': {'count': 12, 'original_pins_unchanged': 11, 'workflow': workflow},
    'paths_are_offline_parameters_not_observed_created': expected_paths,
    'execution_guard_conditions': {'admission_first_guard': False, 'source_config_ready_state': False,
                                   'root_execution_approved': False, 'qualification_execution_dispatched': False},
    'H_calls': 0, 'live_lstat_calls': 0, 'input_module_imports': 0,
    'constructor_acquire_finish_calls': 0, 'gate_test_commands': 0,
    'qualification': False, 'new_live_v5_or_native_snapshot': False,
}
output = HERE / 'FROZEN_BINDING_DATAFLOW.json'
output.open('xb').write((json.dumps(out, sort_keys=True, indent=2) + '\n').encode())
print(json.dumps({'status': 'captured actual binding consistent; execution remains HOLD',
                  'qualification_changes': len(qchanges), 'source_gate_changes': len(schanges),
                  'output': identity(output.read_bytes())}, sort_keys=True))
