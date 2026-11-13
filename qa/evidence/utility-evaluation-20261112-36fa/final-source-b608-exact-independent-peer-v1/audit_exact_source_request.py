#!/usr/bin/env python3
"""Inspect complete immutable request bytes. No bootstrap or input code execution."""
from pathlib import Path
import ast
import base64
import difflib
import hashlib
import json

HERE = Path(__file__).resolve().parent
AUTHOR = Path('/tmp/hepta-36fa-final-source-qualification-b608-preparation-v1/execution-candidate-v1')
ORIGINAL_CODE = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')
READY = Path('/tmp/hepta-36fa-final-qualification-ready-config-independent-peer-v1')
ACTUAL = Path('/tmp/hepta-36fa-final-qualification-actual-binding-independent-peer-v1')
EXPECTED_BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(path, expected=None):
    raw = path.read_bytes()
    if expected is not None:
        assert identity(raw)['git_blob'] == expected, (str(path), identity(raw))
    return raw


def assignments(raw):
    tree = ast.parse(raw)
    nodes = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            assert name not in nodes
            nodes[name] = node
    return tree, nodes


def segment(raw, node):
    return b''.join(raw.splitlines(keepends=True)[node.lineno-1:node.end_lineno])


expected_inputs = {
    'qualification-admission.py': 'c77e3be6230d3267c08333be582f69f23c016fb9',
    'source-gates-wrapper.py': '8607fa4bf00fc8cf535849de04d1eb6ff29429b3',
    'native-wrapper.py': 'de3e9dc5e7eb30f47929f9e1ba9f460035a94fae',
    'native-driver.original.py': 'b92ddded4fce78aeb076d022471c62bf81ce2e4f',
    'PLAN.original.json': '3aefbc71d69d8014eed9e5a18269bbcc866a7583',
    'APPROVED_QUALIFICATION_INPUT.json': '720abbdfa96bca8c7e6aaf633a800693960d80db',
    'SOURCE_GATES_CONFIG.json': 'b97682c5a95bb7f09241e54f0b3d13bf7fa791a4',
    'CANONICAL_SUPERVISOR.original.json': '2deafbe4bfc7ad2c84d9e6315c12aaa6493adab2',
}
frozen = {
    'SOURCE_PROCESS_INPUT.candidate.json': '465e0eaa1f387ad6bb167a4931328e199a5bf793',
    'SOURCE_BOOTSTRAP.candidate.py': 'f8f7d607f3e06ead370d9fa00c1fdfbb56ddbc73',
    'SOURCE_STDIN.candidate.json': '348f8b7a0cb06713ea855bddeaa7c1151d8ebd01',
    'EXACT_SOURCE_LAUNCH_MANIFEST.json': 'bb05cb6aa266cab976fb364dc15a0369fcbf1372',
    'EXACT_SOURCE_LAUNCH_REVIEW.json': '6ddbd924836d3a97aac2523503b133538355b7bc',
    'FROM_CC57_V2_BOOTSTRAP.diff': 'fbaff0b425928c1a076f86eebe1b399fc33300f1',
    'SOURCE_PROCESS_INPUT.cc57-v2.original.json': '3ebc2777182d88bcec1e0a3ad8546af93d5b25f0',
}
get_rows = []
for name, expected in frozen.items():
    raw = read(HERE / 'inputs' / name, expected)
    sdk = json.loads(read(HERE / 'github' / (name + '.GET.original.json')))
    value = sdk['structuredContent']; value = value.get('structuredContent', value)
    assert sdk.get('isError') is not True and value['content'].encode() == raw
    get_rows.append({'name': name, **identity(raw), 'actual_full_get_equal': True})

typed_raw = read(HERE / 'inputs' / 'SOURCE_PROCESS_INPUT.candidate.json')
old_typed_raw = read(HERE / 'inputs' / 'SOURCE_PROCESS_INPUT.cc57-v2.original.json')
typed, old_typed = json.loads(typed_raw), json.loads(old_typed_raw)
expected_keys = {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert set(typed) == set(old_typed) == expected_keys
assert typed['host'] == old_typed['host'] == 'desktop'
assert typed['executable'] == old_typed['executable'] == '/usr/bin/python3'
assert typed['cwd'] == old_typed['cwd'] == '/home/qian-qi'
assert type(typed['timeout_seconds']) is int and typed['timeout_seconds'] == old_typed['timeout_seconds'] == 7200
assert typed['idempotency_key'] == 'hepta-utility-36fa-final-source-gates-b608-v1'
assert len(typed['args']) == len(old_typed['args']) == 3
assert typed['args'][:2] == old_typed['args'][:2] == ['-B', '-c']
bootstrap = read(HERE / 'inputs' / 'SOURCE_BOOTSTRAP.candidate.py')
stdin = read(HERE / 'inputs' / 'SOURCE_STDIN.candidate.json')
assert typed['args'][2].encode() == bootstrap and typed['stdin'].encode() == stdin
assert len(stdin) == 240049 and len(typed_raw) == 246727 and len(stdin) < 1048576 and len(typed_raw) < 1048576
old_bootstrap = old_typed['args'][2].encode()
assert identity(old_bootstrap)['git_blob'] == '43aab05122c70c99733a33f445957fe0a8b364a5'
newtree, newassign = assignments(bootstrap)
oldtree, oldassign = assignments(old_bootstrap)
assert set(newassign) == set(oldassign)
changed_assignments = [name for name in newassign if segment(bootstrap,newassign[name]) != segment(old_bootstrap,oldassign[name])]
assert changed_assignments == ['BASE', 'PINS']
base_node = newassign['BASE'].value
assert isinstance(base_node, ast.Call) and ast.unparse(base_node.func) == 'pathlib.Path'
assert len(base_node.args) == 1 and not base_node.keywords and ast.literal_eval(base_node.args[0]) == EXPECTED_BASE
pins = ast.literal_eval(newassign['PINS'].value)
assert set(pins) == set(expected_inputs)
reversed_lines = bootstrap.splitlines(keepends=True)
for name in sorted(changed_assignments, key=lambda name:newassign[name].lineno, reverse=True):
    node = newassign[name]
    reversed_lines[node.lineno-1:node.end_lineno] = segment(old_bootstrap,oldassign[name]).splitlines(keepends=True)
assert b''.join(reversed_lines) == old_bootstrap
new_functions = sorted((n.name,segment(bootstrap,n)) for n in ast.walk(newtree) if isinstance(n,ast.FunctionDef))
old_functions = sorted((n.name,segment(old_bootstrap,n)) for n in ast.walk(oldtree) if isinstance(n,ast.FunctionDef))
assert new_functions == old_functions and len(new_functions) == 5
new_try = [n for n in newtree.body if isinstance(n,ast.Try)]
old_try = [n for n in oldtree.body if isinstance(n,ast.Try)]
assert len(new_try) == len(old_try) == 1 and segment(bootstrap,new_try[0]) == segment(old_bootstrap,old_try[0])
new_tail = b''.join(bootstrap.splitlines(keepends=True)[new_try[0].end_lineno:])
old_tail = b''.join(old_bootstrap.splitlines(keepends=True)[old_try[0].end_lineno:])
assert new_tail == old_tail
assert any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='exec'
           for n in newtree.body[newtree.body.index(new_try[0])+1:])
expected_diff = ''.join(difflib.unified_diff(old_bootstrap.decode().splitlines(keepends=True),
    bootstrap.decode().splitlines(keepends=True), fromfile='original-source-cc57-v2-43aab051.py',
    tofile='source-b608-candidate.py')).encode()
assert expected_diff == read(HERE / 'inputs' / 'FROM_CC57_V2_BOOTSTRAP.diff')

packet, old_packet = json.loads(stdin), json.loads(old_typed['stdin'])
assert set(packet) == {'format','files'} and packet['format'] == 'hepta-final-source-qualification-bootstrap-v1'
assert set(packet['files']) == set(expected_inputs)
assert old_packet['format'] == packet['format']
decoded, input_rows = {}, []
for name, sha in expected_inputs.items():
    encoded = packet['files'][name]
    assert isinstance(encoded,str)
    raw = base64.b64decode(encoded, validate=True)
    assert base64.b64encode(raw).decode()==encoded
    assert identity(raw) == pins[name] and identity(raw)['git_blob'] == sha
    assert raw == read(AUTHOR / 'inputs' / name, sha)
    decoded[name] = raw
    input_rows.append({'name':name,'native_path':EXPECTED_BASE+'/'+name,**identity(raw)})
unchanged_names = ['source-gates-wrapper.py','native-wrapper.py','native-driver.original.py','PLAN.original.json']
for name in unchanged_names:
    assert decoded[name] == base64.b64decode(old_packet['files'][name],validate=True)
assert decoded['qualification-admission.py'] == read(ORIGINAL_CODE / 'qualification-admission.HOLD.py')
assert decoded['APPROVED_QUALIFICATION_INPUT.json'] == read(READY / 'inputs' / 'QUALIFICATION_CONFIG.candidate.json')
assert decoded['SOURCE_GATES_CONFIG.json'] == read(READY / 'inputs' / 'SOURCE_GATES_CONFIG.candidate.json')
assert decoded['CANONICAL_SUPERVISOR.original.json'] == read(ACTUAL / 'actual-inputs' / 'CANONICAL_NORMAL.original.json')
cfg = json.loads(decoded['APPROVED_QUALIFICATION_INPUT.json'])
sourcecfg = json.loads(decoded['SOURCE_GATES_CONFIG.json'])
assert cfg['admission_path'] == EXPECTED_BASE + '/qualification-admission.py'
assert cfg['admission_pin'] == pins['qualification-admission.py']
assert cfg['native_driver_path'] == EXPECTED_BASE+'/native-driver.original.py'
assert cfg['native_driver_pin'] == pins['native-driver.original.py']
assert cfg['plan_path'] == EXPECTED_BASE+'/PLAN.original.json' and cfg['plan_pin'] == pins['PLAN.original.json']
assert cfg['source_gates_config_path'] == EXPECTED_BASE+'/SOURCE_GATES_CONFIG.json'
assert cfg['source_gates_config_pin'] == pins['SOURCE_GATES_CONFIG.json']
assert cfg['canonical_alignment']['supervisor_path'] == EXPECTED_BASE+'/CANONICAL_SUPERVISOR.original.json'
assert cfg['canonical_alignment']['supervisor'] == pins['CANONICAL_SUPERVISOR.original.json']
assert cfg['source'] == sourcecfg['source_sha'] == 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert cfg['tree'] == sourcecfg['source_tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
assert cfg['state'] == 'READY_FOR_FINAL_SOURCE_QUALIFICATION' and cfg['root_execution_approved'] is True
assert sourcecfg['state'] == 'READY_FOR_EXACT_SOURCE_RUN'
assert sourcecfg['budgets_seconds'] == {'source-closure':600,'self-test':300,'verify':4800}
assert cfg['qualification_execution_dispatched'] is False and cfg['normal_native_and_source_results'] is None
assert cfg['not_an_execution_approval'] is True
manifest = json.loads(read(HERE / 'inputs' / 'EXACT_SOURCE_LAUNCH_MANIFEST.json'))
assert manifest['typed_request']['git_blob'] == identity(typed_raw)['git_blob']
assert manifest['bootstrap']['git_blob'] == identity(bootstrap)['git_blob']
assert manifest['stdin']['git_blob'] == identity(stdin)['git_blob']
assert manifest['key'] == typed['idempotency_key'] and manifest['outer_seconds'] == 7200
assert [{k:row[k] for k in ('name','native_path','bytes','sha256','git_blob')} for row in manifest['inputs']] == input_rows
out = {'format':'hepta-b608-exact-source-request-independent-dataflow-v1',
    'actual_full_get_inputs':get_rows, 'typed_request':identity(typed_raw), 'bootstrap':identity(bootstrap),
    'stdin':identity(stdin), 'original_typed_request':identity(old_typed_raw), 'original_bootstrap':identity(old_bootstrap),
    'request_fields':{k:typed[k] for k in sorted(typed) if k not in ('args','stdin')},
    'args_prefix':['-B','-c'],'exact_seven_fields_no_env':True,
    'changed_bootstrap_assignments':changed_assignments,'complete_bootstrap_inverse_equal':True,
    'unchanged_function_names':[x[0] for x in new_functions], 'all_five_function_bytes_unchanged':True,
    'complete_staging_try_bytes_unchanged':True,'wrapper_exec_after_staging_try_bytes_unchanged':True,
    'all_eight_input_names_and_bytes_equal_pins':True,'inputs':input_rows,
    'four_original_payloads_unchanged':unchanged_names,
    'new_payloads_exactly_previously_reviewed': ['qualification-admission.py','APPROVED_QUALIFICATION_INPUT.json',
        'SOURCE_GATES_CONFIG.json','CANONICAL_SUPERVISOR.original.json'],
    'two_renamed_staging_names':{'APPROVED_SOURCE_GATES_CONFIG.json':'SOURCE_GATES_CONFIG.json',
        'CANONICAL_ALIGNMENT_NORMAL.original.json':'CANONICAL_SUPERVISOR.original.json'},
    'input_limit_unchanged':1048576, 'source_outer_seconds':7200,
    'original_source_phase_budgets':sourcecfg['budgets_seconds'],
    'bootstrap_run':False,'input_module_imports':0,'H_calls':0,'gate_test_execution':0,
    'source_or_ref_writes':0,'qualification':False,'execution_approval':False,
    'scope':'Pure exact-byte/AST/base64/JSON review; native paths and live admission checks have not been probed.'}
path=HERE/'EXACT_SOURCE_DATAFLOW.json'
path.open('xb').write((json.dumps(out,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'status':'exact source candidate bytes consistent','report':identity(path.read_bytes()),
    'typed_request':identity(typed_raw),'inputs':len(input_rows),'unchanged_definitions':len(new_functions)},sort_keys=True))
