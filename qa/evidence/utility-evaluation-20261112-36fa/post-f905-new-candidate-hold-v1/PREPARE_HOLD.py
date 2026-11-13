"""Pure local binding and documentation generation. No source/control main is loaded."""
import ast
import base64
import hashlib
import json
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-post-f905-new-candidate-hold-v1')
RUNTIME = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1')
COORDINATOR = Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1')
INVENTORY = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1/final.inventory.exact_recovered.json')
CC57 = 'cc57c7198db6293ccca562253c42fffbe2a04633'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def fixed(path, blob):
    path = Path(path)
    raw = path.read_bytes()
    identity = pin(raw)
    assert identity['git_blob'] == blob, (path, identity)
    return raw, {'path': str(path), **identity}


def put(name, obj):
    raw = (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode()
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == raw
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), **pin(raw)}


inputs = {}
for label, path, blob in (
        ('previous_consumer_contract', '/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1/SUCCESSOR_CONSUMER_CONTRACT.HOLD.json', '0408b91078bff736a637bdca050e7361df70e37f'),
        ('original_materializer', '/tmp/hepta-36fa-new-source-materializer-hold-v1/driver.HOLD.py', '6d1537fcd58540da64c18916369f4f04d2a0dce1'),
        ('original_materialization_packet', '/tmp/hepta-36fa-new-source-materializer-hold-v1/MATERIALIZATION_PACKET.HOLD.json', '728a9251a3ee0e5fca4dd4cc43e8629bbfa9185c'),
        ('original_maintenance', '/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1/driver-maintenance.HOLD.py', '3a0f6dec8127aa9587129d6e0f24bad55837ca13'),
        ('old_four_path_thin_driver', '/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1/driver-apply-fmt.HOLD.py', '0938761e369ddfa215da98b70423cfd5d48ac819'),
        ('actual_previous_format_result', RUNTIME / 'RESULT.json', '23c8f1375aa98a4c166a9ff4245d8500f060d97f'),
        ('actual_previous_format_supervisor', RUNTIME / 'MAIN_STATUS_02.original.json', 'ddcc52ca523df364e431cc051a91a0d532346bd1'),
        ('actual_previous_format_git_state', RUNTIME / 'final.git-state.json', '6887b270c7d0c6273c644268d3d260c9aee3aa00'),
        ('actual_previous_format_git_metadata', RUNTIME / 'SOURCE_GIT_METADATA.after.json', 'd13c50e149ba23ff1acbd0f99b29669131c1312b'),
        ('actual_previous_inventory_exact_recovery', INVENTORY, 'e1e48f35bb6cf5a3dd86c59472da77df87154b6a'),
        ('coordinator_layer_not_final_source', COORDINATOR / 'SOURCE_PACKET.json', '773d67128190fd2e1c3271c372f72e2a5537d1e8')):
    raw, identity = fixed(path, blob)
    inputs[label] = identity

result = json.loads((RUNTIME / 'RESULT.json').read_bytes())
assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED' and result['qualification'] is False
assert result['historical_fix']['returncode'] == 101 and result['prior_fix_reclassified'] is False
assert result['fix_dispatched'] is False and result['attempted_commands'] == ['fmt']
assert len(result['stages']) == 1 and result['stages'][0]['execution']['returncode'] == 0
assert all(row['status'] == 'verified' for row in result['final_audits'])
inventory = json.loads(INVENTORY.read_bytes())
assert pin(INVENTORY.read_bytes()) == result['actual_final_source']['inventory']
assert inventory['source']['head'] == result['source_commit'] and inventory['source']['tree'] == result['source_tree']
assert inventory['tracked_entries'] == inventory['filesystem_entries'] == len(inventory['files']) == 15237
rows = {row['path']: row for row in inventory['files']}
assert sum(row['matches_index'] is not True for row in rows.values()) == 63
layer = json.loads((COORDINATOR / 'SOURCE_PACKET.json').read_bytes())
assert layer['base_source_identity'] == inventory['source']
assert layer['base_complete_inventory'] == pin(INVENTORY.read_bytes())
assert layer['base_actual_physical_tree'] == result['actual_final_source']['postimages']['all_actual_physical_tree']
assert layer['canonical_source_deletions'] == [] and layer['qualification'] is False
new, changed = [], []
for item in layer['source_changes']:
    path = item['path']
    assert item['mode'] == '100644'
    after = base64.b64decode(item['after_base64'], validate=True)
    assert pin(after) == item['after']
    if item['before'] is None:
        assert item['before_base64'] is None and path not in rows
        new.append(path)
    else:
        before = base64.b64decode(item['before_base64'], validate=True)
        assert pin(before) == item['before']
        row = rows[path]
        assert row['kind'] == 'file' and row['permissions'] == 0o644
        assert pin(before) == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
        changed.append(path)
assert len(new) == 6 and len(changed) == 3

materializer = Path(inputs['original_materializer']['path']).read_text()
maintenance = Path(inputs['original_maintenance']['path']).read_text()
functions = {}
for label, source, names in (
        ('materializer', materializer, ('derive_candidate_inventory', 'expected_graphs', 'source_leaf', 'source_physical', 'old_git_state', 'load_provided_input', 'preflight', 'initialize_index')),
        ('maintenance', maintenance, ('validate_config', 'validate_materialization', 'validate_materialization_current', 'initial_preflight', 'environment_preflight', 'stage', 'finalize_source', 'finalize_inputs'))):
    definitions = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    for name in names:
        node = definitions[name]
        body = ast.get_source_segment(source, node).encode()
        functions[label + '.' + name] = {'line_start': node.lineno, 'line_end': node.end_lineno, **pin(body)}
assert "PARENT == DONOR_HEAD" in materializer
assert "len(fixed['parts']) == (2 if label == 'base' else 3)" in materializer
assert "fixed['maximum_decoded_part'] == 524288" in materializer
assert 'FIX=["just","fix","-p","codex-hepta-intelligence-eval","-p","codex-hepta-agentd","-p","codex-hepta-learning-ledger"]' in maintenance

chain = {
    'format': 'hepta-post-f905-successor-consumer-chain-hold-v1',
    'status': 'HOLD_FINAL_SOURCE_AND_ACTUAL_SUCCESSOR_PROOFS_ABSENT',
    'selected_route': 'B_new_independent_clean_candidate',
    'dispatch_authorized': False, 'qualification': False,
    'original_contract': inputs['previous_consumer_contract'],
    'historical_failed_fix': result['historical_fix'],
    'actual_completed_repair_and_fmt_only': {
        'job_id': '1a1d41eb3ef-392-2b2', 'result': inputs['actual_previous_format_result'],
        'supervisor': inputs['actual_previous_format_supervisor'],
        'status': result['status'], 'applied_existing_paths': result['applied_paths'],
        'attempted_commands': ['fmt'], 'fix_dispatched': False,
        'historical_fix_lint_success': False, 'prior_fix_reclassified': False,
        'fmt_returncode': 0, 'fmt_timeout_seconds': 900,
        'actual_formatter_paths': result['formatter_changed_paths'],
        'inventory': result['actual_final_source']['inventory'],
        'physical_tree': result['actual_final_source']['postimages']['all_actual_physical_tree'],
        'raw_git_state': inputs['actual_previous_format_git_state'],
        'raw_git_metadata': inputs['actual_previous_format_git_metadata'],
        'runtime_placement_git_blob': '77aec000a9d4d22e93f1750a19f750f4f1c3a487'},
    'new_candidate_contract': {
        'sole_parent': CC57,
        'clean_donor_repo': '/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1',
        'clean_donor_commit': CC57, 'clean_donor_leaves': 15188,
        'clean_donor_snapshot_union_objects': 16449,
        'old_experimental_repo_is_not_clean_donor': True,
        'new_destination_repo': None, 'candidate_commit': None, 'candidate_tree': None,
        'complete_inventory': None, 'native_five_field_projection': None,
        'final_full_source_map': None, 'final_overlay_counts': None,
        'actual_materialization_job': None, 'actual_materialization_result': None,
        'actual_materialization_supervisor': None, 'actual_materialization_records': None,
        'actual_new_raw_index': None, 'actual_new_raw_git_state': None,
        'actual_new_raw_git_metadata': None},
    'new_maintenance_contract': {
        'original_driver': inputs['original_maintenance'],
        'new_source_attempt_count': 1, 'actual_attempt_started': False,
        'historical_fix_consumption_reset': False,
        'fix_argv': ['just', 'fix', '-p', 'codex-hepta-intelligence-eval', '-p', 'codex-hepta-agentd', '-p', 'codex-hepta-learning-ledger'],
        'fmt_argv': ['just', 'fmt', '--base', 'c0f78493f815780f68b9bf5e390a21314d79311f'],
        'fix_seconds': 7200, 'fmt_seconds': 900, 'preflight_seconds': 600, 'record_seconds': 300, 'outer_seconds': 9300,
        'fmt_requires_this_new_fix_normal_zero': True,
        'existing_target': '/data/hepta-utility-36fa-final-native-target-v1',
        'minimum_target_free_bytes': 34359738368, 'create_target_if_absent': False,
        'source_gate_or_native_test_authorized': False,
        'approval': None, 'request': None, 'job_id': None, 'result': None, 'supervisor': None},
    'final_qualification': {
        'canonical_source': None, 'source_gate_handoff': None, 'source_gate_result': None,
        'native_gate_result': None, 'fourteen_native_phases_preserved': True,
        'ledger_already_in_original_ordinary_lib_collection': True,
        'root_method_selection': 'The original b92 reads the eventual exact workflow AST parents. Preserve existing 39 and reviewed 9 through the workflow source; no driver-filter or phase mutation is proposed.'},
    'consumer_validator_implemented_here': False,
}
required = {
    'format': 'hepta-selected-route-b-required-immutable-inputs-v1', 'status': 'HOLD',
    'source_map_and_getter_registration_layers_pending': True,
    'materializer_base': inputs['original_materializer'],
    'materializer_budget': {'action': 600, 'records': 180, 'outer': 900},
    'original_format_base': {'commit': 'c0f78493f815780f68b9bf5e390a21314d79311f',
                              'tree': '313ee34febc8ccc54c611ab56286e289518c63cb',
                              'objects': 16094, 'supplied_objects': 83, 'shared_donor_objects': 16011},
    'staging_contract': {'base_part_count': 2, 'candidate_part_count': 3,
                         'maximum_decoded_part': 524288, 'mode': 384,
                         'transport_request_maximum_bytes': 1048576,
                         'new_raw_candidate_pin': None, 'new_gzip_candidate_pin': None,
                         'each_exact_write_request': None,
                         'fit_must_be_measured_not_predicted': True,
                         'overflow_action': 'Hold and identify the concrete contract gap; no automatic bound or part-count increase.'},
    'files_to_freeze': [
        'FINAL_SOURCE_MAP.json', 'CANDIDATE_COMMIT.raw', 'CANDIDATE_OBJECT_INPUT.json',
        'EXPECTED_CLEAN_INVENTORY.json', 'EXPECTED_NATIVE_FIVE_FIELD.json',
        'MATERIALIZATION_PACKET.HOLD.json', 'STAGE_BASE_001.REQUEST.HOLD.json',
        'STAGE_BASE_002.REQUEST.HOLD.json', 'STAGE_CANDIDATE_001.REQUEST.HOLD.json',
        'STAGE_CANDIDATE_002.REQUEST.HOLD.json', 'STAGE_CANDIDATE_003.REQUEST.HOLD.json',
        'driver.HOLD.py', 'APPROVAL_CANDIDATE_CONFIG.json',
        'MATERIALIZATION_BOOTSTRAP.candidate.py', 'MATERIALIZATION_STDIN.candidate.json',
        'MATERIALIZATION_PROCESS_INPUT.candidate.json'],
    'maintenance_inputs_after_actual_materialization': [
        'driver-maintenance.HOLD.py', 'MAINTENANCE_CONFIG.HOLD.json',
        'STAGING_BOOTSTRAP.HOLD.py', 'STAGING_PAYLOAD.HOLD.json', 'STAGING_REQUEST.HOLD.json',
        'LAUNCHER.HOLD.py', 'PROCESS_INPUT.HOLD.json'],
    'retained_history_never_overwritten': [
        'failed fix job 1a1d3eccd3a-392-231', 'fmt-only job 1a1d41eb3ef-392-2b2',
        '0c59 candidate object and experimental repository', 'actual f905 physical evidence',
        'original runtime ENV_READY and restoration records'],
    'all_future_execution_pins': None,
}
review = {
    'format': 'hepta-selected-route-b-static-input-review-v1',
    'inputs': inputs, 'definition_identities': functions,
    'actual_final_inventory_rows': 15237, 'actual_final_dirty_rows': 63,
    'known_coordinator_layer_only': {'paths': 9, 'new': new, 'modified': changed,
                                   'expected_after_leaves': 15243,
                                   'expected_after_tree': layer['expected_after_physical_tree'],
                                   'is_final_source': False},
    'no_final_source_identity_fabricated': True,
    'no_control_function_or_main_executed': True, 'H_calls': 0,
    'source_or_ref_writes': False, 'tests': 0,
}
for name, value in (('CONSUMER_CHAIN.HOLD.json', chain), ('REQUIRED_IMMUTABLE_INPUTS.HOLD.json', required),
                    ('STATIC_INPUT_REVIEW.json', review)):
    print(json.dumps(put(name, value), sort_keys=True))
