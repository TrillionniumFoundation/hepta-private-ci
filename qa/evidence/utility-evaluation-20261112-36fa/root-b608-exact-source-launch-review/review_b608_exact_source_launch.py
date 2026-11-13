"""Root pure review of fixed source-only request. Never execute input code."""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
P = Path('/tmp/hepta-36fa-final-source-qualification-b608-preparation-v1')
E = P / 'execution-candidate-v1'
PEER = Path('/tmp/hepta-36fa-final-source-b608-exact-independent-peer-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(path):
    return json.loads(path.read_bytes())

def assignments(source):
    return {n.targets[0].id: n for n in ast.parse(source).body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}

def definition_map(source):
    return {n.name: ast.get_source_segment(source, n) for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}

def inverse_assignments(current, original):
    result = current.splitlines(keepends=True)
    old = original.splitlines(keepends=True)
    ca, oa = assignments(current), assignments(original)
    for name in sorted(('BASE', 'PINS'), key=lambda x: ca[x].lineno, reverse=True):
        result[ca[name].lineno - 1:ca[name].end_lineno] = old[oa[name].lineno - 1:oa[name].end_lineno]
    return ''.join(result)

manifest = read(E / 'EXACT_SOURCE_LAUNCH_MANIFEST.json')
request_raw = (E / 'SOURCE_PROCESS_INPUT.candidate.json').read_bytes()
request = json.loads(request_raw)
assert identity(request_raw)['git_blob'] == '465e0eaa1f387ad6bb167a4931328e199a5bf793'
original_request_raw = (P / 'originals/SOURCE_PROCESS_INPUT.cc57-v2.original.json').read_bytes()
original = json.loads(original_request_raw)
assert identity(original_request_raw)['git_blob'] == '3ebc2777182d88bcec1e0a3ad8546af93d5b25f0'
assert set(request) == set(original) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert request['host'] == original['host'] == 'desktop'
assert request['executable'] == original['executable'] == '/usr/bin/python3'
assert request['cwd'] == original['cwd'] == '/home/qian-qi'
assert request['timeout_seconds'] == original['timeout_seconds'] == 7200
assert request['idempotency_key'] == 'hepta-utility-36fa-final-source-gates-b608-v1'
assert request['args'][:2] == original['args'][:2] == ['-B', '-c'] and len(request['args']) == 3
assert {k for k in request if request[k] != original[k]} == {'args', 'stdin', 'idempotency_key'}
assert len(request_raw) == 246727 and len(request['stdin'].encode()) == 240049 < 1048576
bootstrap_raw = (E / 'SOURCE_BOOTSTRAP.candidate.py').read_bytes()
stdin_raw = (E / 'SOURCE_STDIN.candidate.json').read_bytes()
assert request['args'][2].encode() == bootstrap_raw and request['stdin'].encode() == stdin_raw
assert identity(bootstrap_raw)['git_blob'] == 'f8f7d607f3e06ead370d9fa00c1fdfbb56ddbc73'
assert identity(stdin_raw)['git_blob'] == '348f8b7a0cb06713ea855bddeaa7c1151d8ebd01'
old_bootstrap = (P / 'originals/SOURCE_BOOTSTRAP.cc57-v2.original.py').read_text()
bootstrap = bootstrap_raw.decode()
assert original['args'][2] == old_bootstrap
assert identity(old_bootstrap.encode())['git_blob'] == '43aab05122c70c99733a33f445957fe0a8b364a5'
assert inverse_assignments(bootstrap, old_bootstrap) == old_bootstrap
assert definition_map(bootstrap) == definition_map(old_bootstrap)
assert set(definition_map(bootstrap)) == {'check', 'identity', 'real_parents', 'retain', 'stamp'}
trees = [ast.parse(x) for x in (bootstrap, old_bootstrap)]
tries = [[n for n in t.body if isinstance(n, ast.Try)] for t in trees]
assert len(tries[0]) == len(tries[1]) == 1
assert ast.get_source_segment(bootstrap, tries[0][0]) == ast.get_source_segment(old_bootstrap, tries[1][0])
assert '\n'.join(bootstrap.splitlines()[tries[0][0].end_lineno:]) == '\n'.join(old_bootstrap.splitlines()[tries[1][0].end_lineno:])
assert [n.func.id for n in ast.walk(trees[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'exec'] == ['exec']
pins = ast.literal_eval(assignments(bootstrap)['PINS'].value)
packet = json.loads(stdin_raw)
assert set(packet) == {'format', 'files'} and packet['format'] == 'hepta-final-source-qualification-bootstrap-v1'
assert len(packet['files']) == len(pins) == 8 and set(packet['files']) == set(pins)
inputs = {name: base64.b64decode(value, validate=True) for name, value in packet['files'].items()}
old_inputs = {name: base64.b64decode(value, validate=True) for name, value in json.loads(original['stdin'])['files'].items()}
expected = {'qualification-admission.py': 'c77e3be6230d3267c08333be582f69f23c016fb9',
            'source-gates-wrapper.py': '8607fa4bf00fc8cf535849de04d1eb6ff29429b3',
            'native-wrapper.py': 'de3e9dc5e7eb30f47929f9e1ba9f460035a94fae',
            'native-driver.original.py': 'b92ddded4fce78aeb076d022471c62bf81ce2e4f',
            'PLAN.original.json': '3aefbc71d69d8014eed9e5a18269bbcc866a7583',
            'APPROVED_QUALIFICATION_INPUT.json': '720abbdfa96bca8c7e6aaf633a800693960d80db',
            'SOURCE_GATES_CONFIG.json': 'b97682c5a95bb7f09241e54f0b3d13bf7fa791a4',
            'CANONICAL_SUPERVISOR.original.json': '2deafbe4bfc7ad2c84d9e6315c12aaa6493adab2'}
assert set(expected) == set(inputs)
for name, body in inputs.items():
    assert identity(body) == pins[name] and identity(body)['git_blob'] == expected[name]
    assert body == (E / 'inputs' / name).read_bytes()
for name in ('source-gates-wrapper.py', 'native-wrapper.py', 'native-driver.original.py', 'PLAN.original.json'):
    assert inputs[name] == old_inputs[name]
cfg = json.loads(inputs['APPROVED_QUALIFICATION_INPUT.json'])
source = json.loads(inputs['SOURCE_GATES_CONFIG.json'])
assert cfg['state'] == 'READY_FOR_FINAL_SOURCE_QUALIFICATION' and cfg['root_execution_approved'] is True
assert cfg['not_an_execution_approval'] is True and cfg['qualification_execution_dispatched'] is False
assert cfg['normal_native_and_source_results'] is None
assert cfg['source'] == source['source_sha'] == 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert cfg['tree'] == source['source_tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
assert cfg['parents'] == ['d25675445c39f76db69a7bd8e71a1a72e1cd5b9f']
assert cfg['repo'] == source['object_repository'] == '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
assert cfg['admission_path'] == CONTROL + '/qualification-admission.py' and cfg['admission_pin'] == pins['qualification-admission.py']
assert cfg['source_gates_config_path'] == CONTROL + '/SOURCE_GATES_CONFIG.json' and cfg['source_gates_config_pin'] == pins['SOURCE_GATES_CONFIG.json']
assert cfg['canonical_alignment']['supervisor_path'] == CONTROL + '/CANONICAL_SUPERVISOR.original.json'
assert cfg['canonical_alignment']['supervisor'] == pins['CANONICAL_SUPERVISOR.original.json']
assert cfg['native_driver_path'] == CONTROL + '/native-driver.original.py' and cfg['native_driver_pin'] == pins['native-driver.original.py']
assert cfg['plan_path'] == CONTROL + '/PLAN.original.json' and cfg['plan_pin'] == pins['PLAN.original.json']
assert cfg['source_gates_handoff_records'] == CONTROL + '/source-handoff'
assert source['records'] == CONTROL + '/source-gates-records'
assert source['source_checkout'] == '/home/qian-qi/hepta-utility-36fa-source-gates-b608-v1'
assert source['state'] == 'READY_FOR_EXACT_SOURCE_RUN'
assert source['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}
assert source['driver_sha256'] == '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2'
assert source['hepta_ci_exec_sha256'] == '9b2bfaa563fff018df4e4f10944f6fbc63d307fa4c4a7e167c392288edb5a5c1'
closed = read(R / 'ROOT_5A9_ACTUAL_SOURCE_RUNTIME_CLOSURE.json')
assert identity((R / 'ROOT_5A9_ACTUAL_SOURCE_RUNTIME_CLOSURE.json').read_bytes())['git_blob'] == '9144fb5ba97d90393446cd1f919d480c27ca6dbc'
assert closed['status'] == 'ACTUAL_CANONICAL_ALIGNMENT_CLOSED_NOT_QUALIFIED'
assert closed['source']['after']['git_state'] == cfg['current_final_git_state']
assert closed['source']['after']['inventory']['sha256'] == cfg['full_physical_inventory']['sha256']
assert closed['original_normal'] == pins['CANONICAL_SUPERVISOR.original.json']
peer = read(PEER / 'REVIEW.json')
assert identity((PEER / 'REVIEW.json').read_bytes())['git_blob'] == '87c00eacb529b6666404f93e95ad98e1b6840e53'
assert peer['reviewed_request'] == identity(request_raw) and peer['bootstrap'] == identity(bootstrap_raw) and peer['stdin'] == identity(stdin_raw)
assert peer['no_concrete_static_blocker'] is True and peer['execution_approval'] is False and peer['qualification'] is False

report = {'format': 'hepta-root-b608-exact-source-launch-review-v1',
          'status': 'EXACT_SOURCE_REQUEST_REVIEWED_SEPARATE_ROOT_ACTION_REQUIRED',
          'exact_request': identity(request_raw), 'exact_bootstrap': identity(bootstrap_raw), 'exact_stdin': identity(stdin_raw),
          'original_request': identity(original_request_raw), 'original_bootstrap': identity(old_bootstrap.encode()),
          'whole_bootstrap_inverse_base_and_pins_only': True, 'original_function_definitions_byte_equal': 5,
          'entire_staging_try_and_outside_source_exec_byte_equal': True,
          'exact_request_fields': sorted(request), 'host': request['host'], 'cwd': request['cwd'],
          'executable': request['executable'], 'idempotency_key': request['idempotency_key'],
          'outer_timeout_seconds': 7200, 'admission_seconds': 600, 'final_record_seconds': 300,
          'source_phase_budgets_seconds': source['budgets_seconds'], 'eight_inputs': pins,
          'control': CONTROL, 'source_repo': cfg['repo'], 'source_clone': source['source_checkout'],
          'source': cfg['source'], 'tree': cfg['tree'], 'parents': cfg['parents'],
          'actual_canonical_root_closure': identity((R / 'ROOT_5A9_ACTUAL_SOURCE_RUNTIME_CLOSURE.json').read_bytes()),
          'independent_exact_request_peer': identity((PEER / 'REVIEW.json').read_bytes()),
          'scope': 'Fresh external control staging and original source wrapper/5118 source gate only. Native wrapper/driver are staged but not executed by this request.',
          'input_code_executed_by_review': False, 'H_or_live_admission_called_by_review': False,
          'source_or_ref_mutations_by_review': False, 'qualification': False,
          'real_authorized_learning_chains': 0,
          'inherited_failure_limit': 'Secondary SourceChanged before initial_git exists is not proof of source mutation. Preserve primary failure and original unknown/failed distinction.'}
raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
out = R / 'ROOT_B608_EXACT_SOURCE_LAUNCH_REVIEW.json'
with out.open('xb') as f:
    f.write(raw)
print(json.dumps({'path': str(out), **identity(raw)}))
