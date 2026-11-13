"""Root-only immutable request review. No project/H code is executed."""
import ast
import base64
import hashlib
import json
from pathlib import Path

P = Path('/tmp/hepta-36fa-final-source-b608-transported-preparation-v1')
RUNTIME = Path('/tmp/hepta-36fa-b608-history-transport-staging-runtime-v1')
OUT = Path('/tmp/hepta-36fa-root-source-b608-transported-review-v1')
INPUTS = P / 'inputs'
HOLD = P / 'actual-binding-hold-v1'
READY = P / 'execution-candidate-v1'
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v2'
OLD_BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'
KEYS = ('bytes', 'sha256', 'git_blob')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pairs(values):
    result = {}
    for key, value in values:
        assert key not in result
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def file(path, sha=None):
    raw = path.read_bytes()
    if sha is not None:
        assert pin(raw)['git_blob'] == sha, str(path)
    return raw


def differences(left, right, path=()):
    if isinstance(left, dict) and isinstance(right, dict):
        assert left.keys() == right.keys(), path
        result = []
        for key in sorted(left):
            result += differences(left[key], right[key], path + (key,))
        return result
    if left != right:
        return [path]
    return []


old_request_raw = file(INPUTS / 'SOURCE_PROCESS_INPUT.65a.original.json', '465e0eaa1f387ad6bb167a4931328e199a5bf793')
request_raw = file(READY / 'SOURCE_PROCESS_INPUT.candidate.json', 'eb4658e231aac54f226a78585d647e2bab8aa6e1')
assert pin(request_raw)['bytes'] == 280984 and pin(request_raw)['sha256'] == '3245e534618d004ba767b5b2ec5483194bcc5453fe6531ef8aff7ee393fb8214'
old_request, request = parse(old_request_raw), parse(request_raw)
assert set(request) == set(old_request) == {'host', 'executable', 'args', 'cwd', 'stdin', 'timeout_seconds', 'idempotency_key'}
assert request['host'] == 'desktop' and request['executable'] == '/usr/bin/python3'
assert request['cwd'] == '/home/qian-qi' and request['timeout_seconds'] == 7200
assert request['idempotency_key'] == 'hepta-utility-36fa-final-source-gates-b608-v2'
assert differences(old_request, request) == [('args',), ('idempotency_key',), ('stdin',)]
bootstrap = file(READY / 'SOURCE_BOOTSTRAP.candidate.py', '9111aa1eecd218ebe61fde21012a404279ffe431')
old_bootstrap = file(INPUTS / 'SOURCE_BOOTSTRAP.65a.original.py', 'f8f7d607f3e06ead370d9fa00c1fdfbb56ddbc73')
assert request['args'] == ['-B', '-c', bootstrap.decode()]
assert old_request['args'] == ['-B', '-c', old_bootstrap.decode()]
old_tree, tree = ast.parse(old_bootstrap), ast.parse(bootstrap)
old_nodes = {n.targets[0].id: ast.get_source_segment(old_bootstrap.decode(), n) for n in old_tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
new_nodes = {n.targets[0].id: ast.get_source_segment(bootstrap.decode(), n) for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
assert old_nodes.keys() == new_nodes.keys()
assert [name for name in old_nodes if old_nodes[name] != new_nodes[name]] == ['BASE', 'PINS']
inverse = bootstrap.decode()
for name in ('BASE', 'PINS'):
    assert inverse.count(new_nodes[name]) == 1
    inverse = inverse.replace(new_nodes[name], old_nodes[name])
assert inverse.encode() == old_bootstrap
assert new_nodes['BASE'] == "BASE = pathlib.Path('" + BASE + "')"
pins = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'PINS'))
old_pins = ast.literal_eval(next(n.value for n in old_tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'PINS'))
assert len(pins) == len(old_pins) == 8
assert set(pins) - set(old_pins) == {'TRANSPORT_SUPERVISOR.original.json'}
assert set(old_pins) - set(pins) == {'CANONICAL_SUPERVISOR.original.json'}
for name in ('source-gates-wrapper.py', 'native-wrapper.py', 'native-driver.original.py', 'PLAN.original.json'):
    assert pins[name] == old_pins[name]
stdin = file(READY / 'SOURCE_STDIN.candidate.json', '7b92437a4ee8316725b2bf73b0f88503329c157c')
assert request['stdin'].encode() == stdin
wire = parse(stdin)
assert set(wire) == {'format', 'files'} and wire['format'] == 'hepta-final-source-qualification-bootstrap-v1'
assert set(wire['files']) == set(pins)
payloads = {name: base64.b64decode(data, validate=True) for name, data in wire['files'].items()}
for name, raw in payloads.items():
    assert pin(raw) == pins[name]
    assert base64.b64encode(raw).decode() == wire['files'][name]
assert payloads['qualification-admission.py'] == file(INPUTS / 'qualification-admission.fd67.selected.py', 'fd67cb043f7b6cb8cf042104ac202cb5f0842196')
assert payloads['TRANSPORT_SUPERVISOR.original.json'] == file(RUNTIME / 'STATUS_01.original.json', 'af805a3230601013eb94afd5e40e9ea3e83c61d4')
for name in ('source-gates-wrapper.py', 'native-wrapper.py', 'native-driver.original.py', 'PLAN.original.json'):
    assert payloads[name] == file(INPUTS / name)

original_hold_raw = file(INPUTS / 'QUALIFICATION_CONFIG.transport.HOLD.original.json', '09cc978923c1d0a3d6f920b0e1754025107d7825')
bound_hold_raw = file(HOLD / 'QUALIFICATION_CONFIG.HOLD.json', 'df28b1dc5737f5a5afc06c56022a6ef1e5a3f558')
ready_raw = file(READY / 'QUALIFICATION_CONFIG.execution-candidate.json', 'dca6d215f11d36bc6588a8db6ebdc8f8bbf1de06')
original_hold, bound_hold, ready = map(parse, (original_hold_raw, bound_hold_raw, ready_raw))
assert payloads['APPROVED_QUALIFICATION_INPUT.json'] == ready_raw
bound_diffs = differences(original_hold, bound_hold)
assert bound_diffs == [('admission_pin', 'bytes'), ('admission_pin', 'git_blob'), ('admission_pin', 'sha256'), ('history_transport', 'staging_job_id'), ('history_transport', 'staging_payload'), ('history_transport', 'staging_result'), ('history_transport', 'staging_supervisor')]
assert bound_hold['admission_pin'] == pin(payloads['qualification-admission.py'])
transport = bound_hold['history_transport']
assert transport['staging_job_id'] == '1a1d52e0d88-392-784'
assert transport['staging_payload'] == pin(file(RUNTIME / 'STAGE_STDIN.original.json'))
assert transport['staging_result'] == pin(file(RUNTIME / 'STAGING_READBACK.json'))
assert transport['staging_supervisor'] == pin(payloads['TRANSPORT_SUPERVISOR.original.json'])
assert transport['staging_supervisor_path'] == BASE + '/TRANSPORT_SUPERVISOR.original.json'
assert transport['staging_result_path'] == transport['control'] + '/STAGING_READBACK.json'
restored = parse(bound_hold_raw)
restored['admission_pin'] = original_hold['admission_pin']
for field in ('staging_job_id', 'staging_payload', 'staging_result', 'staging_supervisor'):
    restored['history_transport'][field] = None
assert encoded(restored) == original_hold_raw
ready_diffs = differences(bound_hold, ready)
assert ready_diffs == [('root_execution_approved',), ('source_gates_config_pin', 'bytes'), ('source_gates_config_pin', 'git_blob'), ('source_gates_config_pin', 'sha256'), ('state',)]
source_hold_raw = file(HOLD / 'SOURCE_GATES_CONFIG.HOLD.json', 'acfa7c86f4202d6e7f15399514dc739f4bc33f82')
source_ready_raw = file(READY / 'SOURCE_GATES_CONFIG.execution-candidate.json', '01aa39eaf0334341b2d7944d3457ac09d1577f00')
assert payloads['SOURCE_GATES_CONFIG.json'] == source_ready_raw
source_hold, source_ready = parse(source_hold_raw), parse(source_ready_raw)
assert differences(source_hold, source_ready) == [('state',)]
assert source_ready['state'] == 'READY_FOR_EXACT_SOURCE_RUN'
assert source_ready['budgets_seconds'] == {'self-test': 300, 'source-closure': 600, 'verify': 4800}
assert ready['root_execution_approved'] is True and bound_hold['root_execution_approved'] is False
assert ready['state'] == 'READY_FOR_FINAL_SOURCE_QUALIFICATION'
assert ready['source_gates_config_pin'] == pin(source_ready_raw)
restored = parse(ready_raw)
for field in ('state', 'root_execution_approved', 'source_gates_config_pin'):
    restored[field] = bound_hold[field]
assert encoded(restored) == bound_hold_raw
restored = parse(source_ready_raw)
restored['state'] = source_hold['state']
assert encoded(restored) == source_hold_raw
assert ready['source'] == source_ready['source_sha'] == 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert ready['tree'] == source_ready['source_tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
assert ready['expected_file_count'] == 15243 and ready['normal_native_and_source_results'] is None
assert ready['not_an_execution_approval'] is True and ready['qualification_execution_dispatched'] is False
manifest_raw = file(RUNTIME / 'FILE_004.readback.bin', '5d2e19cadd569f9dd37f0f87997b115d7ed3ef2a')
manifest = parse(manifest_raw)
canonical = next(row for row in manifest['rows'] if row['role'] == 'canonical.supervisor')
assert canonical['pin'] == ready['canonical_alignment']['supervisor'] == old_pins['CANONICAL_SUPERVISOR.original.json']
assert canonical['original_path'] == ready['canonical_alignment']['supervisor_path']
assert 'cfg.canonical_alignment.supervisor' in canonical['original_consumers']
assert len(manifest['rows']) == 55
original_functions = [ast.get_source_segment(old_bootstrap.decode(), n) for n in old_tree.body if isinstance(n, ast.FunctionDef)]
functions = [ast.get_source_segment(bootstrap.decode(), n) for n in tree.body if isinstance(n, ast.FunctionDef)]
assert functions == original_functions and len(functions) == 4
review = {
    'format': 'hepta-root-exact-source-request-byte-review-v1',
    'request': pin(request_raw), 'bootstrap': pin(bootstrap), 'stdin': pin(stdin),
    'original_failed_request': pin(old_request_raw), 'original_failed_job': '1a1d4f0c3d4-392-65a',
    'original_failure_remains_failure': True,
    'typed_request_changed_fields_only': [list(p) for p in differences(old_request, request)],
    'bootstrap_changes_only': ['BASE', 'PINS'],
    'bootstrap_whole_inverse_exact': True,
    'unchanged_top_level_functions': len(functions), 'nested_stamp_and_try_and_final_exec_unchanged': True,
    'payloads': [{'name': name, **pin(raw)} for name, raw in payloads.items()],
    'original_four_program_and_plan_payloads_unchanged': True,
    'actual_binding_fields_only': [list(p) for p in bound_diffs],
    'ready_permission_fields_only': [list(p) for p in ready_diffs],
    'all_HOLD_and_permission_inverses_exact': True,
    'canonical_supervisor_slot': {'old_direct_payload_removed': True, 'original_pin_and_path_retained_in_config': True,
                                  'all_55_fixed_historical_map_validation_retained': True, 'row': canonical},
    'new_stage_supervisor_slot': {'name': 'TRANSPORT_SUPERVISOR.original.json', 'actual_stage_job': transport['staging_job_id'], 'pin': transport['staging_supervisor']},
    'source_subject': ready['source'], 'source_tree': ready['tree'], 'expected_files': ready['expected_file_count'],
    'budgets_seconds': source_ready['budgets_seconds'], 'outer_timeout_seconds': 7200,
    'no_environment_field': True, 'original_authority_guards_and_native_plan_unchanged_by_this_preparation': True,
    'prior_independent_fd67_review': '7dccd7414f5dcce595a7f5ad3056bb3e6e349756',
    'complete_stage_replay': 'b0434543015a01fac8d60267981f08af8160be50',
    'needs_separate_exact_Root_dispatch_approval': True,
    'H_calls': 0, 'source_or_native_executed': False, 'qualification': False, 'real_qualified_task_chains': 0,
}
result = encoded(review)
with (OUT / 'ROOT_EXACT_SOURCE_REQUEST_REVIEW.json').open('xb') as stream:
    stream.write(result)
print(json.dumps({'review': pin(result), 'request': pin(request_raw), 'H_calls': 0, 'qualification': False}))
