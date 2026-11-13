import ast
import base64
import difflib
import hashlib
import json
from pathlib import Path

D = Path('/tmp/hepta-36fa-final-source-qualification-b608-preparation-v1')
O = D / 'originals'
C = D / 'execution-candidate-v1'
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'
KEY = 'hepta-utility-36fa-final-source-gates-b608-v1'
NORMAL = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1/STATUS_02.original.json')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def pin(raw, expected):
    assert identity(raw) == expected, (identity(raw), expected)
    return raw

def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, path
    else:
        with path.open('xb') as f:
            f.write(raw)
    return {'local_path': str(path), **identity(raw)}

def jput(path, value):
    return put(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode())

def assignment(text, name):
    nodes = [x for x in ast.parse(text).body if isinstance(x, ast.Assign)
             and len(x.targets) == 1 and isinstance(x.targets[0], ast.Name)
             and x.targets[0].id == name]
    assert len(nodes) == 1
    return ast.get_source_segment(text, nodes[0])

def functions(text):
    return {f'{x.lineno}:{x.name}': ast.get_source_segment(text, x)
            for x in ast.walk(ast.parse(text)) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))}

old_raw = pin((O / 'SOURCE_PROCESS_INPUT.cc57-v2.original.json').read_bytes(), {
    'bytes': 131345, 'sha256': '55c9acefda3fe004b6b29e407256e89a1e99fd5e372b2ca04bf4b27a6f7687f4',
    'git_blob': '3ebc2777182d88bcec1e0a3ad8546af93d5b25f0'})
old = json.loads(old_raw)
assert set(old) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert old['args'][:2] == ['-B', '-c'] and len(old['args']) == 3
assert old['host'] == 'desktop' and old['executable'] == '/usr/bin/python3'
assert old['cwd'] == '/home/qian-qi' and old['timeout_seconds'] == 7200
old_boot = old['args'][2]
old_packet = json.loads(old['stdin'])
assert set(old_packet) == {'format', 'files'}
assert old_packet['format'] == 'hepta-final-source-qualification-bootstrap-v1'
old_pins = ast.literal_eval(assignment(old_boot, 'PINS').split('=', 1)[1].strip())
old_files = {name: pin(base64.b64decode(encoded, validate=True), old_pins[name])
             for name, encoded in old_packet['files'].items()}
assert len(old_files) == 8 and set(old_files) == set(old_pins)

cfg_raw = pin((O / 'QUALIFICATION_CONFIG.execution-candidate.json').read_bytes(), {
    'bytes': 24155, 'sha256': 'ac5663c711d2d47669c334052e09151d2fbda34776ff41b0b8727804d322a840',
    'git_blob': '720abbdfa96bca8c7e6aaf633a800693960d80db'})
source_cfg_raw = pin((O / 'SOURCE_GATES_CONFIG.execution-candidate.json').read_bytes(), {
    'bytes': 831, 'sha256': 'f08beb0e1a0c87117bd7a091ec3c7b4390285cf47a291c0d7569fd0f1d2e197c',
    'git_blob': 'b97682c5a95bb7f09241e54f0b3d13bf7fa791a4'})
admission_raw = pin((O / 'qualification-admission.original.py').read_bytes(), {
    'bytes': 87654, 'sha256': '453de56b668a8361c710be67f058b5a37c8e39be106a28c5bc803783906b6ca2',
    'git_blob': 'c77e3be6230d3267c08333be582f69f23c016fb9'})
normal_raw = pin(NORMAL.read_bytes(), {
    'bytes': 950, 'sha256': 'da2b842525ca95a78f10292fc9db13c30466a2e498b717a51a7ebe3f2714c990',
    'git_blob': '2deafbe4bfc7ad2c84d9e6315c12aaa6493adab2'})
cfg = json.loads(cfg_raw)
source_cfg = json.loads(source_cfg_raw)
normal_sdk = json.loads(normal_raw)
assert normal_sdk.get('isError') is not True
normal = json.loads(normal_sdk['content'][0]['text'])
assert normal['job_id'] == cfg['canonical_alignment']['job_id'] == '1a1d4cbd33e-392-5a9'
assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert normal['timed_out'] is False and normal['cancelled'] is False and normal['automatic_retry'] is False
assert all(normal[x] is True for x in ('output_complete', 'output_durable', 'terminal_publication_confirmed'))
assert cfg['state'] == 'READY_FOR_FINAL_SOURCE_QUALIFICATION' and cfg['root_execution_approved'] is True
assert cfg['not_an_execution_approval'] is True and cfg['qualification_execution_dispatched'] is False
assert cfg['source'] == source_cfg['source_sha'] == 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert cfg['tree'] == source_cfg['source_tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
assert cfg['expected_file_count'] == 15243
assert cfg['admission_pin'] == identity(admission_raw)
assert cfg['canonical_alignment']['supervisor'] == identity(normal_raw)
assert cfg['source_gates_config_pin'] == identity(source_cfg_raw)
assert source_cfg['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}
assert cfg['repo'] == source_cfg['object_repository'] == '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
assert source_cfg['source_checkout'] == '/home/qian-qi/hepta-utility-36fa-source-gates-b608-v1'
assert cfg['root_parent'] == '/run/hepta-utility-36fa-final-b608-v1'

fixed = ['source-gates-wrapper.py', 'native-wrapper.py', 'native-driver.original.py', 'PLAN.original.json']
files = {
    'qualification-admission.py': admission_raw,
    'source-gates-wrapper.py': old_files['source-gates-wrapper.py'],
    'native-wrapper.py': old_files['native-wrapper.py'],
    'native-driver.original.py': old_files['native-driver.original.py'],
    'PLAN.original.json': old_files['PLAN.original.json'],
    'APPROVED_QUALIFICATION_INPUT.json': cfg_raw,
    'SOURCE_GATES_CONFIG.json': source_cfg_raw,
    'CANONICAL_SUPERVISOR.original.json': normal_raw,
}
pins = {name: identity(raw) for name, raw in files.items()}
assert len(files) == 8
for name in fixed:
    assert files[name] == old_files[name] and pins[name] == old_pins[name]
assert cfg['admission_path'] == BASE + '/qualification-admission.py'
assert cfg['plan_path'] == BASE + '/PLAN.original.json' and cfg['plan_pin'] == pins['PLAN.original.json']
assert cfg['native_driver_path'] == BASE + '/native-driver.original.py' and cfg['native_driver_pin'] == pins['native-driver.original.py']
assert cfg['canonical_alignment']['supervisor_path'] == BASE + '/CANONICAL_SUPERVISOR.original.json'
assert cfg['source_gates_config_path'] == BASE + '/SOURCE_GATES_CONFIG.json'
assert cfg['source_gates_handoff_records'] == BASE + '/source-handoff'
assert cfg['records'] == BASE + '/native-records'
assert source_cfg['records'] == BASE + '/source-gates-records'

old_base_line = assignment(old_boot, 'BASE')
old_pins_line = assignment(old_boot, 'PINS')
new_base_line = 'BASE = pathlib.Path(' + repr(BASE) + ')'
new_pins_line = 'PINS = ' + repr(pins)
assert old_boot.count(old_base_line) == old_boot.count(old_pins_line) == 1
boot = old_boot.replace(old_base_line, new_base_line).replace(old_pins_line, new_pins_line)
assert boot.replace(new_base_line, old_base_line).replace(new_pins_line, old_pins_line) == old_boot
assert functions(boot) == functions(old_boot)
assert len(functions(boot)) == 5
old_ast, new_ast = ast.parse(old_boot), ast.parse(boot)
assert ast.dump(old_ast.body[-1], include_attributes=False) == ast.dump(new_ast.body[-1], include_attributes=False)
assert isinstance(new_ast.body[-1], ast.Expr) and isinstance(new_ast.body[-1].value, ast.Call)
assert isinstance(new_ast.body[-1].value.func, ast.Name) and new_ast.body[-1].value.func.id == 'exec'
assert old_boot.split('# Main failure is owned by the unchanged original wrapper, not the stager.')[1] == boot.split('# Main failure is owned by the unchanged original wrapper, not the stager.')[1]
packet = {'format': old_packet['format'], 'files': {n: base64.b64encode(b).decode() for n, b in files.items()}}
stdin = json.dumps(packet, ensure_ascii=False, separators=(',', ':')) + '\n'
typed = dict(old)
typed['args'] = ['-B', '-c', boot]
typed['stdin'] = stdin
typed['idempotency_key'] = KEY
changed_fields = [k for k in old if typed[k] != old[k]]
assert changed_fields == ['args', 'stdin', 'idempotency_key']
typed_raw = (json.dumps(typed, ensure_ascii=False, indent=2) + '\n').encode()
assert len(stdin.encode()) <= 1048576 and len(typed_raw) <= 1048576
assert set(typed) == set(old) and 'env' not in typed
for n, b in files.items():
    put(C / 'inputs' / n, b)
boot_pin = put(C / 'SOURCE_BOOTSTRAP.candidate.py', boot.encode())
stdin_pin = put(C / 'SOURCE_STDIN.candidate.json', stdin.encode())
typed_pin = put(C / 'SOURCE_PROCESS_INPUT.candidate.json', typed_raw)
diff_pin = put(C / 'FROM_CC57_V2_BOOTSTRAP.diff', ''.join(difflib.unified_diff(old_boot.splitlines(True), boot.splitlines(True), fromfile='original-source-cc57-v2-43aab051.py', tofile='source-b608-candidate.py')).encode())
readback = jput(C / 'EXACT_SOURCE_LAUNCH_REVIEW.json', {
    'format': 'hepta-final-source-exact-launch-static-review-v1',
    'status': 'PREPARED_REQUIRES_ROOT_EXACT_EXECUTION_APPROVAL',
    'original_request': identity(old_raw), 'original_bootstrap': identity(old_boot.encode()),
    'bootstrap_changed_assignments': ['BASE', 'PINS'],
    'complete_inverse_bootstrap_equal': True, 'five_function_definitions_byte_equal': True,
    'source_only_exec_tail_byte_equal_and_outside_staging_try': True,
    'actual_typed_field_names': list(typed), 'typed_changed_fields': changed_fields,
    'host': typed['host'], 'cwd': typed['cwd'], 'executable': typed['executable'],
    'args_prefix': typed['args'][:2], 'no_env_field': True,
    'outer_timeout_seconds': 7200, 'original_gate_budgets_seconds': source_cfg['budgets_seconds'],
    'original_admission_and_finalization_budgets_seconds': [600, 300],
    'native_dispatch_in_this_request': False, 'source_only_dispatch_after_exact_eight_file_readback': True,
    'new_key': KEY, 'new_control': BASE, 'fixed_payloads_unchanged': fixed,
    'changed_payloads': ['qualification-admission.py', 'APPROVED_QUALIFICATION_INPUT.json', 'SOURCE_GATES_CONFIG.json', 'CANONICAL_SUPERVISOR.original.json'],
    'staging_filename_mapping': {'APPROVED_SOURCE_GATES_CONFIG.json': 'SOURCE_GATES_CONFIG.json', 'CANONICAL_ALIGNMENT_NORMAL.original.json': 'CANONICAL_SUPERVISOR.original.json'},
    'staging_filename_mapping_reason': 'Exact current configuration paths; names change only in PINS and stdin files map. The original bootstrap helpers and source-only execution tail are unchanged.',
    'all_eight_input_decoded_bytes_equal': True, 'input_pins': pins,
    'canonical_supervisor_actual_job': normal['job_id'], 'canonical_supervisor_actual_normal_exit': normal['exit_code'],
    'configuration_bytes_preserved_without_parse_reserialize': True,
    'source_identity': {'commit': cfg['source'], 'tree': cfg['tree'], 'file_count': cfg['expected_file_count']},
    'typed_bytes': len(typed_raw), 'stdin_bytes': len(stdin.encode()), 'typed_stdin_cap_bytes': 1048576,
    'remaining_new_work': 'Root exact request review and separate execution decision. No H staging, source gate, or native main has been dispatched by this preparation.',
    'current_native_file_existence_not_reprobed': True,
    'cooperative_source_lock_is_original_admission_SH_not_a_bootstrap_EX': True,
    'qualified_source_or_native_result': None})
manifest = jput(C / 'EXACT_SOURCE_LAUNCH_MANIFEST.json', {
    'format': 'hepta-final-source-eight-input-exact-launch-manifest-v1',
    'status': 'CANDIDATE_ONLY_ROOT_EXACT_APPROVAL_REQUIRED',
    'control': BASE, 'key': KEY,
    'bootstrap': boot_pin, 'stdin': stdin_pin, 'typed_request': typed_pin, 'bootstrap_diff': diff_pin,
    'static_review': readback,
    'inputs': [{'name': n, 'local_path': str(C / 'inputs' / n), 'native_path': BASE + '/' + n, **p} for n, p in pins.items()],
    'cfg_owner': '/root/ordinary_path', 'cfg_and_admission_changed_by_preparer': False,
    'original_template_git': '3ebc2777182d88bcec1e0a3ad8546af93d5b25f0',
    'expected_source': cfg['source'], 'expected_tree': cfg['tree'],
    'outer_seconds': 7200, 'native_main_not_started': True,
    'root_execution_decision': None})
print(json.dumps({'bootstrap': boot_pin, 'stdin': stdin_pin, 'typed': typed_pin, 'diff': diff_pin, 'review': readback, 'manifest': manifest}, sort_keys=True))
