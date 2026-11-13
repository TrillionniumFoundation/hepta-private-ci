import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
D = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1')
L = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-launch-v1/execution-candidate-v1')
C = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-preparation-v1')
N = Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-format-runtime-v1')
X = Path('/tmp/hepta-36fa-a489-final-nonrust-exact-recovery-v1')

def typed(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': typed('blob', raw)}

def read(path, sha=None):
    raw = Path(path).read_bytes()
    if sha is not None:
        assert typed('blob', raw) == sha, str(path)
    return raw

def assignments(source):
    return {n.targets[0].id: n for n in ast.parse(source).body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}

def inverse(current, original, allowed):
    ca, oa = assignments(current), assignments(original)
    changed = {k for k in ca.keys() & oa.keys() if ast.get_source_segment(current, ca[k]) != ast.get_source_segment(original, oa[k])}
    assert changed == set(allowed), changed
    restored = current
    for key in allowed:
        c, o = ast.get_source_segment(current, ca[key]), ast.get_source_segment(original, oa[key])
        assert restored.count(c) == 1
        restored = restored.replace(c, o, 1)
    assert restored == original
    cf = [ast.get_source_segment(current, n) for n in ast.walk(ast.parse(current)) if isinstance(n, ast.FunctionDef)]
    of = [ast.get_source_segment(original, n) for n in ast.walk(ast.parse(original)) if isinstance(n, ast.FunctionDef)]
    assert cf == of
    return {'changed_assignments_only': sorted(changed), 'whole_inverse_equal': True,
            'all_function_definitions_byte_identical': len(cf),
            'top_level_functions_byte_identical': sum(isinstance(n, ast.FunctionDef) for n in ast.parse(current).body)}

request_raw = read(L / 'ACTUAL_PROCESS_INPUT.candidate.json', 'fd655e0dea612e9dd13d4026c11d01b811c8fd8d')
stdin_raw = read(L / 'ACTUAL_STDIN.candidate.json', '268aacaec6be37bf047b34278656d83008a1a34a')
bootstrap_raw = read(L / 'ACTUAL_BOOTSTRAP.candidate.py', '601a3b9448f46c44936ea7789b57d6499e584926')
request, stdin = json.loads(request_raw), json.loads(stdin_raw)
assert set(request) == {'host', 'cwd', 'executable', 'args', 'stdin', 'timeout_seconds', 'idempotency_key'}
assert request['host'] == 'desktop' and request['cwd'] == '/home/qian-qi' and request['executable'] == '/usr/bin/python3'
assert request['args'] == ['-B', '-c', bootstrap_raw.decode()]
assert request['stdin'] == stdin_raw.decode()
assert request['timeout_seconds'] == 900
assert request['idempotency_key'] == 'hepta-utility-36fa-provider-coordinator-a489-final-canonical-alignment-v1'
assert len(request_raw) <= 1048576 and len(stdin_raw) <= 1048576
assert set(stdin) == {'format', 'files'} and stdin['format'] == 'hepta-final-canonical-alignment-bootstrap-v1'
expected_paths = {
    'driver.py': C / 'driver.HOLD.py',
    'FINAL_FORMAT_NORMAL.original.json': N / 'STATUS_02.original.json',
    'CANONICAL_PACKET.json': D / 'CANONICAL_PACKET.json',
    'APPROVED_CONFIG.json': D / 'APPROVED_CONFIG.execution-candidate.json',
}
assert set(stdin['files']) == set(expected_paths)
pins = ast.literal_eval(assignments(bootstrap_raw.decode())['PINS'].value)
assert set(pins) == set(expected_paths)
decoded = {}
for name, path in expected_paths.items():
    raw = base64.b64decode(stdin['files'][name], validate=True)
    if name == 'CANONICAL_PACKET.json':
        assert pins[name]['bytes'] <= 40000000
        raw = gzip.decompress(raw)
    assert raw == read(path) and pin(raw) == pins[name]
    decoded[name] = raw
original_bootstrap = read(R / 'ORIGINAL_CANONICAL_BOOTSTRAP_139630.py', '13963075b37d38b1ef88fd7d3e76201b2318dbbe').decode()
bootstrap_inverse = inverse(bootstrap_raw.decode(), original_bootstrap, ['BASE', 'PINS'])
driver_raw = decoded['driver.py']
assert typed('blob', driver_raw) == 'e8d606b801b54ab949c5f215c49cdf47ed0ea89a'
original_driver = read(R / 'ORIGINAL_CANONICAL_DRIVER_765ADA.py', '765ada67a33f4d9aeaf29c9c522898057083cafb').decode()
driver_inverse = inverse(driver_raw.decode(), original_driver, ['REPO', 'CONTROL', 'INVENTORY', 'OLD', 'OLD_TREE', 'OLD_PARENTS', 'LEAVES'])
assert driver_inverse['top_level_functions_byte_identical'] == 46

config = json.loads(decoded['APPROVED_CONFIG.json'])
held = json.loads(read(C / 'WAITING_CONFIG.json'))
changed_fields = {k for k in config if config[k] != held[k]}
expected_changed = {'status', 'root_execution_approved', 'actual_final_postimages_reviewed', 'after_commit', 'after_tree', 'after_parents',
                    'after_inventory', 'before_inventory', 'canonical_object_count', 'canonical_packet', 'expected_before_git_state',
                    'reviewed_formatter_changed_paths', 'final_format'}
assert changed_fields == expected_changed and set(config) == set(held)
assert (config['action_seconds'], config['record_seconds'], config['outer_seconds']) == (600, 180, 900)
assert all(config[k] is False for k in ['physical_source_writes_authorized', 'dependency_installation_authorized',
                                      'cargo_or_formatter_authorized', 'test_commands_authorized', 'remote_ref_updates_authorized', 'qualification'])
assert config['status'] == 'ROOT_APPROVED_FOR_ONE_CANONICAL_ALIGNMENT' and config['root_execution_approved'] is True
assert config['not_an_execution_approval'] is True
packet = json.loads(decoded['CANONICAL_PACKET.json'])
assert config['canonical_packet'] == pin(decoded['CANONICAL_PACKET.json'])
assert packet['format'] == 'hepta-final-canonical-source-alignment-packet-v1'
assert packet['source_repo'] == config['source_repo'] and packet['complete_leaf_count'] == config['complete_leaf_count'] == 15243
assert packet['before'] == {'commit': config['before_commit'], 'tree': config['before_tree'], 'parents': config['before_parents'],
                            'inventory': config['before_inventory'], 'git_state': config['expected_before_git_state']}
assert packet['after'] == {'commit': config['after_commit'], 'tree': config['after_tree'], 'parents': config['after_parents'], 'inventory': config['after_inventory']}
assert (config['before_commit'], config['before_tree']) == ('d25675445c39f76db69a7bd8e71a1a72e1cd5b9f', 'a489b394666b8141840275128a780605b024cde0')
assert (config['after_commit'], config['after_tree']) == ('b6084394a4a38ab495c16eaba09e879f04a96f8e', '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638')
assert config['after_parents'] == [config['before_commit']]
objects = {}
for o in packet['objects']:
    assert set(o) == {'type', 'sha', 'sha256', 'bytes', 'raw_base64'}
    raw = base64.b64decode(o['raw_base64'], validate=True)
    assert o['type'] in ['blob', 'tree', 'commit'] and typed(o['type'], raw) == o['sha']
    assert len(raw) == o['bytes'] and hashlib.sha256(raw).hexdigest() == o['sha256'] and o['sha'] not in objects
    objects[o['sha']] = raw
assert len(objects) == config['canonical_object_count'] == 29
assert objects[config['after_commit']] == read(R / 'FINAL_B6084394_COMMIT.raw')

# Invoke only the unchanged pure guards on already observed original bytes.
names = {'check', 'sha256', 'oid', 'nodup', 'parse', 'inventory_summary', 'physical_projection', 'parse_supervisor', 'validate_final_format'}
nodes = [n for n in ast.parse(driver_raw).body if isinstance(n, ast.FunctionDef) and n.name in names]
assert {n.name for n in nodes} == names
readbacks = {
    config['final_format']['result_path']: read(N / 'RESULT.json'),
    config['final_format']['supervisor_path']: decoded['FINAL_FORMAT_NORMAL.original.json'],
    config['final_format']['git_state_path']: read(N / 'final.git-state.json'),
}
retained = {}
def exact_read(path, expected):
    raw = readbacks[str(path)]
    assert pin(raw) == expected
    return raw
namespace = {'json': json, 'hashlib': hashlib, 'LEAVES': 15243, 'cfg': config, 'result': {},
             'REPO': Path(config['source_repo']), 'OLD': config['before_commit'], 'OLD_TREE': config['before_tree'],
             'OLD_PARENTS': config['before_parents'], 'NEW_TREE': config['after_tree'],
             'read_input': exact_read, 'write': lambda name, raw: retained.setdefault(name, raw)}
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<unchanged-canonical-pure-guards>', 'exec'), namespace)
before_raw = read(X / 'final.inventory.exact_recovered.json', 'e3ce3d7bba028e29efca751c6f43fde124b05ea0')
after_raw = read(D / 'EXPECTED_AFTER_INVENTORY.json', '457adb9bf9ba3a844e9dfa149be49460bb306998')
assert namespace['inventory_summary'](before_raw) == config['before_inventory']
assert namespace['inventory_summary'](after_raw) == config['after_inventory']
assert namespace['physical_projection'](before_raw) == namespace['physical_projection'](after_raw)
namespace['validate_final_format']()
assert len(retained) == 3
assert json.loads(after_raw)['source'] == {'head': config['after_commit'], 'tree': config['after_tree'], 'status': ''}
assert all(r['matches_index'] is True for r in json.loads(after_raw)['files'])
assert namespace['result']['final_format']['job_id'] == '1a1d4a979d9-392-50f'

encoding = json.loads(read(L / 'ENCODING_MANIFEST.json'))
for member in encoding['members']:
    pieces = []
    for part in member['parts']:
        raw = read(L / part['name'])
        assert pin(raw) == {k: part[k] for k in ['bytes', 'sha256', 'git_blob']}
        block = base64.b64decode(raw.removesuffix(b'\n'), validate=True)
        assert pin(block) == part['decoded'] and sum(map(len, pieces)) == part['decoded_offset']
        pieces.append(block)
    packed = b''.join(pieces)
    assert pin(packed) == member['gzip']
    raw = gzip.decompress(packed)
    assert pin(raw) == member['raw'] and raw == read(L / member['name'])

report = {'format': 'hepta-root-b608-exact-canonical-launch-review-v1', 'status': 'EXACT_CANDIDATE_REVIEWED_PENDING_PEER_AND_ROOT_APPROVAL',
          'request': pin(request_raw), 'bootstrap': pin(bootstrap_raw), 'stdin': pin(stdin_raw),
          'original_bootstrap': pin(original_bootstrap.encode()), 'bootstrap_inverse': bootstrap_inverse,
          'driver': pin(driver_raw), 'original_driver': pin(original_driver.encode()), 'driver_inverse': driver_inverse,
          'config': pin(decoded['APPROVED_CONFIG.json']), 'config_changed_fields': sorted(changed_fields),
          'packet': pin(decoded['CANONICAL_PACKET.json']), 'objects': 29,
          'before_actual': packet['before'], 'after_expected_projection_only': packet['after'],
          'unchanged_pure_guards_executed': sorted(names), 'original_final_format_guard_retained_copies': sorted(retained),
          'all_15243_physical_rows_exactly_preserved': True, 'all_29_raw_objects_typed_hash_valid': True,
          'request_fields': sorted(request), 'environment_override': False, 'action_record_outer_seconds': [600, 180, 900],
          'stdin_and_request_below_original_one_MiB': True, 'bootstrap_has_no_lock': True,
          'driver_single_original_exclusive_lock_retained': True,
          'scope': 'One original create-only four-input bootstrap and original canonical index/HEAD alignment. Existing source bytes/modes and repository refs stay unchanged.',
          'H_calls': 0, 'source_or_ref_mutations': 0, 'canonical_alignment_observed': False,
          'qualification': False, 'real_qualified_chains': 0,
          'approval_boundary': 'Configuration is executable-shaped data. This report is not dispatch authorization; separate exact Root approval follows independent peer and full Git readback.'}
raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
(R / 'ROOT_B608_EXACT_CANONICAL_LAUNCH_REVIEW.json').write_bytes(raw)
print(json.dumps({'review': pin(raw), 'request': pin(request_raw), 'bootstrap_inverse': bootstrap_inverse, 'driver_inverse': driver_inverse, 'qualification': False}))
