#!/usr/bin/env python3
"""Read-only exact-byte review; no import or execution of staged programs."""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
D = Path('/tmp/hepta-36fa-source65a-transported-originals-hold-v1')
H = D / 'review-candidate-v1'
E = D / 'execution-candidate-v1'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def check(raw, pin):
    got = identity(raw)
    assert all(got[k] == pin[k] for k in got), (got, pin)
    return got

def load(p):
    return json.loads(p.read_bytes())

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

def definitions(source):
    found = {}
    def walk(node, parents):
        for child in ast.iter_child_nodes(node):
            current = parents
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                current = parents + [child.name]
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    key = '.'.join(current)
                    assert key not in found
                    found[key] = ast.get_source_segment(source, child)
            walk(child, current)
    walk(ast.parse(source), [])
    return found

hold_manifest = load(H / 'MANIFEST.json')
assert identity((H / 'MANIFEST.json').read_bytes())['git_blob'] == '7b7aa021cdc0f75f9a18edc210f7e540e55663c4'
assert len(hold_manifest['files']) == 59
for row in hold_manifest['files']:
    assert row['path'] == str(H / row['name'])
    check((H / row['name']).read_bytes(), row)
    assert row['bytes'] <= 512000
assert hold_manifest['qualification'] is False and hold_manifest['root_execution_approved'] is False
assert hold_manifest['source_request'] is None and hold_manifest['native_request'] is None

execution_manifest = load(E / 'MANIFEST.json')
assert identity((E / 'MANIFEST.json').read_bytes())['git_blob'] == 'e93ec3d768b01726db403511a2ea347dcec8c157'
for row in execution_manifest['files']:
    check((E / row['name']).read_bytes(), row)
assert execution_manifest['not_an_execution_approval'] is True
assert execution_manifest['source_request'] is None and execution_manifest['native_request'] is None
assert all(x is None for x in execution_manifest['actual_stage_fields'].values())
assert set(execution_manifest['actual_stage_fields']) == {'staging_job_id', 'staging_payload', 'staging_result', 'staging_supervisor'}

closed_raw = (H / 'TRANSPORT_MANIFEST.HOLD.json').read_bytes()
closed = json.loads(closed_raw)
writes = load(H / 'STAGING_WRITE_MANIFEST.HOLD.json')
assert writes['root_execution_approved'] is False and writes['automatic_retry'] is False
assert len(writes['writes']) == 17 and closed['historical_original_count'] == 55
check(closed_raw, writes['history_manifest'])
parts = []
requests = []
offset = 0
for i, row in enumerate(writes['writes'], 1):
    assert row['sequence'] == i and row['decoded_offset'] == offset
    body = (H / 'parts' / f'PART_{i:03d}.b64').read_bytes()
    check(body, row['encoded_part'])
    decoded = base64.b64decode(body.strip(), validate=True)
    check(decoded, row['decoded_pin'])
    assert len(decoded) <= 307200
    request_raw = (H / 'write-requests' / f'STAGE_{i:03d}.REQUEST.HOLD.json').read_bytes()
    check(request_raw, row['request'])
    request = json.loads(request_raw)
    assert set(request) == {'data_base64', 'expected_version', 'host', 'path'}
    assert request['expected_version'] == 'absent' and request['host'] == 'desktop'
    assert request['path'] == row['native_path']
    assert base64.b64decode(request['data_base64'], validate=True) == decoded
    assert len(request_raw) <= 512000 and len(request_raw) <= 1048576
    parts.append(decoded)
    requests.append({'sequence': i, 'native_path': request['path'], 'request': identity(request_raw), 'part': identity(decoded)})
    offset += len(decoded)
compressed = b''.join(parts)
check(compressed, writes['gzip'])
packet_raw = gzip.decompress(compressed)
check(packet_raw, writes['packet'])
packet = json.loads(packet_raw)
assert packet['manifest'] == writes['history_manifest']
assert len(packet['files']) == len(closed['rows']) == 55
assert [x['role'] for x in packet['files']] == [x['role'] for x in closed['rows']]
assert len({x['role'] for x in closed['rows']}) == len({x['original_path'] for x in closed['rows']}) == 55
all_bodies = []
for spec, item in zip(closed['rows'], packet['files']):
    assert set(item) == {'role', 'data_base64'}
    body = base64.b64decode(item['data_base64'], validate=True)
    check(body, spec['pin'])
    assert spec['transport_path'] == closed['control'] + '/originals/' + spec['role'] + '.original'
    assert '/.git/' not in spec['original_path'] and not spec['original_path'].endswith('.lock')
    all_bodies.append(identity(body))
assert sum(x['bytes'] for x in all_bodies) == 7976106
assert len({x['git_blob'] for x in all_bodies}) == 50

hold_input_raw = (H / 'STAGING_INPUT.HOLD.json').read_bytes()
ready_input_raw = (E / 'STAGING_INPUT.execution-candidate.json').read_bytes()
hold_input, ready_input = json.loads(hold_input_raw), json.loads(ready_input_raw)
assert hold_input['root_execution_approved'] is False and hold_input['status'] == 'HOLD_ROOT_EXACT_REVIEW_REQUIRED'
assert ready_input['root_execution_approved'] is True and ready_input['status'] == 'ROOT_APPROVED_TO_STAGE_ONLY'
inverse = dict(ready_input)
inverse['root_execution_approved'] = False
inverse['status'] = hold_input['status']
assert inverse == hold_input and canonical(inverse) == hold_input_raw
hold_typed_raw = (H / 'STAGING_PROCESS_INPUT.HOLD.json').read_bytes()
ready_typed_raw = (E / 'STAGING_PROCESS_INPUT.execution-candidate.json').read_bytes()
hold_typed, ready_typed = json.loads(hold_typed_raw), json.loads(ready_typed_raw)
assert set(ready_typed) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert ready_typed['host'] == 'desktop' and ready_typed['executable'] == '/usr/bin/python3'
assert ready_typed['args'] == ['-B', '-c', (H / 'TRANSPORT_STAGER.HOLD.py').read_text()]
assert ready_typed['cwd'] == '/home/qian-qi' and ready_typed['timeout_seconds'] == 900
assert ready_typed['stdin'].encode() == ready_input_raw
inverse_typed = dict(ready_typed)
inverse_typed['stdin'] = hold_typed['stdin']
assert inverse_typed == hold_typed and canonical(inverse_typed) == hold_typed_raw
assert len(ready_typed_raw) <= 1048576 and len(ready_input_raw) <= 1048576
assert base64.b64decode(ready_input['manifest_base64'], validate=True) == closed_raw
assert base64.b64decode(ready_input['historical_guard_base64'], validate=True) == (H / 'historical-runtime-guard.HOLD.py').read_bytes()

original_v5 = (R / 'TRANSPORT_REVIEW_ORIGINAL_V5.py').read_text()
original_admission = (R / 'TRANSPORT_REVIEW_ORIGINAL_ADMISSION.exact.py').read_text()
assert identity(original_v5.encode())['git_blob'] == '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'
assert identity(original_admission.encode())['git_blob'] == 'c77e3be6230d3267c08333be582f69f23c016fb9'
changed = {}
for name, old, new, expected in [
    ('historical_v5', original_v5, (H / 'historical-runtime-guard.HOLD.py').read_text(), {'validate_runtime_restoration', 'environment_preflight'}),
    ('admission', original_admission, (H / 'qualification-admission.HOLD.py').read_text(), {
        'Admission.__init__', 'Admission.observed_proof', 'Admission.acquire_and_validate',
        'Admission.before_native_stage', 'Admission.finish', 'Admission._fixed',
        'Admission._artifact', 'Admission._validate_canonical'})]:
    before, after = definitions(old), definitions(new)
    assert set(before).issubset(after)
    differences = {key for key in before if before[key] != after[key]}
    assert differences == expected, (name, differences)
    changed[name] = {'original_definitions': len(before), 'changed_original_definitions': sorted(differences),
                     'preserved_original_definitions': len(before) - len(differences),
                     'added_definitions': sorted(set(after) - set(before))}
assert definitions(original_v5)['read_input'] == definitions((H / 'historical-runtime-guard.HOLD.py').read_text())['read_input']
cfg = load(H / 'QUALIFICATION_CONFIG.HOLD.json')
assert cfg['root_execution_approved'] is False
for key in ('staging_job_id', 'staging_payload', 'staging_result', 'staging_supervisor'):
    assert cfg['history_transport'][key] is None
assert cfg['historical_runtime_guard_pin'] == identity((H / 'historical-runtime-guard.HOLD.py').read_bytes())

report = {
    'format': 'root-exact-transport-stage-candidate-pure-review-v1',
    'status': 'EXACT_BYTE_AND_CLOSED_ROLE_CHECKS_PASSED_NOT_EXECUTION_APPROVAL',
    'hold_manifest': identity((H / 'MANIFEST.json').read_bytes()),
    'execution_manifest': identity((E / 'MANIFEST.json').read_bytes()),
    'hold_files_verified': 59, 'execution_files_verified': len(execution_manifest['files']),
    'stage_request': identity(ready_typed_raw), 'stage_input': identity(ready_input_raw),
    'stager': identity((H / 'TRANSPORT_STAGER.HOLD.py').read_bytes()),
    'write_requests': requests, 'maximum_write_request_bytes': max(x['request']['bytes'] for x in requests),
    'decoded_parts': 17, 'original_roles': 55, 'distinct_bodies': 50, 'raw_original_bytes': 7976106,
    'complete_gzip': identity(compressed), 'complete_packet': identity(packet_raw),
    'ready_to_hold_exact_inverse': True, 'only_ready_input_changes': ['status', 'root_execution_approved'],
    'typed_only_change': 'stdin', 'stager_args_key_timeout_unchanged': True,
    'original_definition_comparison': changed,
    'current_v5_original_identity_retained': '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735',
    'new_source_actual_stage_fields_all_null': True,
    'qualification': False, 'not_an_execution_approval': True,
    'H_calls': 0, 'gate_or_guard_imports_or_execution': 0,
    'limitations': ['Exact byte review does not establish current native availability.',
                    'Independent code review and a separate exact engineering action decision remain required.',
                    'No source or native gate is authorized or started by these candidate fields.']
}
raw = canonical(report)
out = R / 'ROOT_EXACT_TRANSPORT_STAGE_CANDIDATE_REVIEW.json'
assert not out.exists()
out.write_bytes(raw)
print(json.dumps({'path': str(out), **identity(raw)}, sort_keys=True))
