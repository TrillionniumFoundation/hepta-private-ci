"""Offline, data/AST-only successor review. Never execute reviewed control."""
import ast
import base64
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent
NEW = Path('/tmp/hepta-36fa-native-after-cc57-source-candidate-v1')
OLD = Path('/tmp/hepta-36fa-native-after-cc57-source-hold-v1')
PRIOR = Path('/tmp/hepta-36fa-native-after-cc57-source-peer-v1/REVIEW.json')
INPUTS = Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v2/inputs')
ACTUAL = Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v2')
SOURCE = 'cc57c7198db6293ccca562253c42fffbe2a04633'
TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
JOB = '1a1d23c92f3-2564-1cb4'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(path):
    raw = path.read_bytes()
    return raw, {'path': str(path), **identity(raw)}

def assignments(text):
    return {n.targets[0].id: n for n in ast.parse(text).body if isinstance(n, ast.Assign)
            and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}

def section(text, node):
    return ''.join(text.splitlines(keepends=True)[node.lineno-1:node.end_lineno])

old_raw, old_pin = read(OLD / 'BOOTSTRAP_TEMPLATE.HOLD.py')
new_raw, new_pin = read(NEW / 'NATIVE_BOOTSTRAP.candidate.py')
assert old_pin['git_blob'] == 'fcd164e362993c49affd4893e4108e06100b4726'
assert new_pin['git_blob'] == '1e3402a037b259f44213ac6de487e6d91cc6b445'
old, new = old_raw.decode(), new_raw.decode()
old_a, new_a = assignments(old), assignments(new)
success_nodes = {ast.literal_eval(k): v for k, v in zip(new_a['SOURCE_SUCCESS'].value.keys, new_a['SOURCE_SUCCESS'].value.values)}
pins = {name: ast.literal_eval(success_nodes[name]) for name in ('result', 'original_run_result', 'supervisor')}
inverse = new
for name, value in pins.items():
    before = f"    '{name}': None,\n"
    after = f"    '{name}': {value!r},\n"
    assert old.count(before) == 1 and new.count(after) == 1
    inverse = inverse.replace(after, before, 1)
assert inverse.encode() == old_raw
assert ast.dump(ast.parse(inverse), include_attributes=False) == ast.dump(ast.parse(old), include_attributes=False)
assert ast.literal_eval(success_nodes['job_id']) == JOB

functions = {}
for node in ast.parse(new).body:
    if isinstance(node, ast.FunctionDef):
        prior = next(x for x in ast.parse(old).body if isinstance(x, ast.FunctionDef) and x.name == node.name)
        assert section(new, node) == section(old, prior)
        assert ast.dump(node, include_attributes=False) == ast.dump(prior, include_attributes=False)
        functions[node.name] = {'bytes_equal': True, 'AST_equal': True}
assert len(functions) == 5
assert section(new, new_a['BASE']) == section(old, old_a['BASE'])
assert section(new, new_a['PINS']) == section(old, old_a['PINS'])
tail_marker = '# The original native wrapper owns all gate results and its own failure records.\n'
assert new.split(tail_marker, 1)[1] == old.split(tail_marker, 1)[1]
tree = ast.parse(new)
assert isinstance(tree.body[-1], ast.Expr) and tree.body[-1].value.func.id == 'exec'
assert not any(isinstance(node, ast.Try) for node in tree.body[-3:])

manifest = json.loads((NEW / 'MANIFEST.json').read_bytes())
for row in manifest['files']:
    assert identity(Path(row['path']).read_bytes()) == {k: row[k] for k in ('bytes','sha256','git_blob')}
old_request = json.loads((OLD / 'REQUEST.HOLD.json').read_bytes())
request_raw, request_pin = read(NEW / 'NATIVE_PROCESS_INPUT.candidate.json')
request = json.loads(request_raw)
assert set(request) == set(old_request) == {'host','executable','args','cwd','stdin','idempotency_key','timeout_seconds'}
assert request['args'] == ['-B','-c',new]
assert request['timeout_seconds'] == old_request['timeout_seconds'] == 45000
for field in ('host','executable','cwd','idempotency_key'):
    assert request[field] == old_request[field]
assert request['idempotency_key'] == 'hepta-utility-36fa-final-native-gates-cc57-v1'
payload_raw, payload_pin = read(NEW / 'NATIVE_STDIN.candidate.json')
assert request['stdin'].encode() == payload_raw
payload = json.loads(payload_raw)
old_payload = json.loads(old_request['stdin'])
assert set(payload) == set(old_payload) == {'format','source_supervisor_base64'}
assert payload['format'] == old_payload['format'] == 'hepta-final-native-after-source-bootstrap-v1'
assert old_payload['source_supervisor_base64'] is None
normal = base64.b64decode(payload['source_supervisor_base64'], validate=True)
assert normal == (ACTUAL / 'STATUS_05.original.json').read_bytes()

actual_paths = {'result': ACTUAL / 'SOURCE_HANDOFF_RESULT.json',
                'original_run_result': ACTUAL / 'ORIGINAL_RUN_RESULT.json',
                'supervisor': ACTUAL / 'STATUS_05.original.json'}
actual = {}
for name, path in actual_paths.items():
    raw, row = read(path)
    assert identity(raw) == pins[name]
    actual[name] = row
result = json.loads(actual_paths['result'].read_bytes())
run = json.loads(actual_paths['original_run_result'].read_bytes())
envelope = json.loads(normal)
assert envelope['isError'] is False and len(envelope['content']) == 1
assert envelope['content'][0]['type'] == 'text'
terminal = json.loads(envelope['content'][0]['text'])
assert terminal['job_id'] == JOB and terminal['state'] == 'succeeded' and terminal['exit_code'] == 0
assert all(terminal[k] is False for k in ('timed_out','cancelled','automatic_retry'))
assert all(terminal[k] is True for k in ('output_complete','output_durable','terminal_publication_confirmed'))
assert not any(terminal['log_truncated'].values())
assert not any(terminal['log_errors'].values()) and all(terminal['log_synced'].values())
assert terminal['log_bytes']['stdout'] == {'seen':6169, 'stored':6169}
assert (result['source'],result['tree']) == (SOURCE,TREE)
assert result['status'] == 'passed' and result['driver_main_entered'] is True
assert result['driver_returncode'] == 0 and result['original_run_status'] == 'passed'
assert result['actual_origin_full_physical_observation'] == {'extra_physical_entries':0, 'full_physical_bytes_equal':True, 'original_source_rows_unchanged':True}
assert run['source_sha'] == SOURCE and run['source_tree'] == TREE and run['status'] == 'passed'
assert run['run_identity'] == 'hepta-utility-36fa-source-gates-cc57-v2'
expected_gates = ['source-closure','self-test','verify']
assert run['attempted'] == run['entrypoints_started'] == expected_gates and run['not_run'] == []
assert [g['gate'] for g in run['gates']] == expected_gates
for gate in run['gates']:
    assert gate['status'] == 'passed' and gate['source_sha'] == SOURCE and gate['source_changed'] is False
    assert gate['run_identity'] == run['run_identity']
    assert gate['before_inventory_sha256'] == gate['after_inventory_sha256'] == 'f7db5e671a913b26a8798ec9e8ea5bdd265e6ace80ec85cdea7e6c22bb66387a'
    assert all(gate[k] is None for k in ('after_inventory_error','execution_error','record_read_error'))
    assert gate['original_record_retained_unchanged'] is True
    assert gate['lifecycle'] == {'attempted':True,'entrypoint_started':True,'package':'completed','terminal_observed':True}

prior_raw, prior_pin = read(PRIOR)
assert prior_pin['git_blob'] == '581a64610daf35c4bc1be2e54651e13cc66badfa'
prior = json.loads(prior_raw)
original_inputs = ast.literal_eval(new_a['PINS'].value)
assert len(original_inputs) == 8
input_rows=[]
for name, expected in original_inputs.items():
    raw, row = read(INPUTS / name)
    assert identity(raw) == expected
    input_rows.append(row)
assert input_rows == prior['eight_exact_inputs']
cfg = json.loads((INPUTS / 'APPROVED_QUALIFICATION_INPUT.json').read_bytes())
assert (cfg['source'],cfg['tree'],cfg['parents']) == (SOURCE,TREE,['246d8cb614770252ee42029a5c014f2a4904176a'])
plan = json.loads((INPUTS / 'PLAN.original.json').read_bytes())
assert len(plan['phases']) == prior['budget_and_runtime_contract']['plan_phase_count'] == 14
assert len(next(p for p in plan['phases'] if p['id'] == 'root')['prepared_parent_names']) == 33

report = {
    'format':'hepta-cc57-native-candidate-narrow-independent-review-v1',
    'reviewed_at_utc':datetime.now(timezone.utc).isoformat(),
    'conclusion':'NO_CONCRETE_BLOCKER_IN_EXACT_THREE_PIN_SUCCESSOR; ROOT_FULL_EVIDENCE_AND_LAUNCH_APPROVAL_STILL_REQUIRED',
    'qualification':False, 'H_calls':0,'source_writes':0,'ref_updates':0,'reviewed_control_main_executions':0,'tests_or_gates_run':0,
    'hold_template':old_pin,'candidate_bootstrap':new_pin,'candidate_typed_request':request_pin,'candidate_payload':payload_pin,
    'previous_independent_review':prior_pin,
    'exact_delta':{'SOURCE_SUCCESS_only_three_nulls_replaced':True,'inverse_whole_bootstrap_equal':True,'inverse_AST_equal':True,
        'five_functions':functions,'native_exec_outside_staging_try_byte_equal':True,'BASE_and_eight_PINS_unchanged':True,
        'request_only_args_code_and_stdin_changed':True,'typed_fields':sorted(request),'no_env_field':True,
        'outer_timeout_seconds':45000,'idempotency_key_unchanged':request['idempotency_key'],
        'stdin_exact_STATUS05_bytes':True},
    'actual_source_proof_pins':actual,'source_job_id':JOB,'terminal':terminal,
    'source_result':result,
    'original_run_summary':{'status':run['status'],'source_sha':run['source_sha'],'source_tree':run['source_tree'],
        'run_identity':run['run_identity'],'gates':[{'gate':g['gate'],'status':g['status'],'elapsed_seconds':g['elapsed_seconds'],
        'source_changed':g['source_changed'],'before_inventory_sha256':g['before_inventory_sha256'],
        'after_inventory_sha256':g['after_inventory_sha256']} for g in run['gates']]},
    'eight_inputs_rehashed_equal_prior_peer_review':input_rows,
    'unchanged_execution_contract':prior['budget_and_runtime_contract'],
    'limitations':['This is offline data/AST/byte validation of the exact candidate. No reviewed code was imported, executed, or dispatched.',
       'The three small actual source records bind the observed normal source job and all three reported gates. This audit does not replace Root review of complete raw gate output, frozen clone and origin before/after inventories, and retained originals.',
       'Native qualification has not been run by this reviewer. Source mechanism success is not a real authorized A/B/C task, independent evaluation outcome, deployment adoption, or daemon/Root real-task closure.']
}
(OUT/'REVIEW.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({'review':identity((OUT/'REVIEW.json').read_bytes()),'conclusion':report['conclusion']},sort_keys=True))
