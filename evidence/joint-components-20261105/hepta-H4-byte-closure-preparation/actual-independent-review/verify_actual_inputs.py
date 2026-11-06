"""Read-only independent binding check; never imports or executes the exporter."""
from pathlib import Path, PurePosixPath
import ast
import base64
import hashlib
import json
import zlib

W = Path('/workspace/scratch/93bfcfe29fc8')
R = W / 'pq_recovery/h4-actual-archive-plan-review'
P = W / 'w1/h4-reference-export'
INPUTS = {}


def read(path, expected=None, size=None):
    path = path.resolve()
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    assert expected is None or sha == expected, str(path)
    assert size is None or len(raw) == size, str(path)
    INPUTS[str(path.relative_to(W))] = {'bytes': len(raw), 'sha256': sha}
    return raw


def obj(path, expected=None, size=None):
    return json.loads(read(path, expected, size))


def literal(tree, name):
    matches = [node.value for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    assert len(matches) == 1, name
    return ast.literal_eval(matches[0])


def safe_absolute(value, under=None):
    path = PurePosixPath(value)
    assert path.is_absolute() and str(path) == value and '..' not in path.parts
    if under is not None:
        path.relative_to(PurePosixPath(under))


plan_raw = read(P / 'H4-reference-export-plan.json',
                'c917633ed8b22fa7a97455ea06c4a96fecc4a208375899bd3afededebf007619', 1236214)
plan = json.loads(plan_raw)
exporter = read(W / 'w1/h4-content-reference-draft/archive_reference.py',
                'ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425', 43223)
decoder = read(P / 'transport_payload.py',
               '6160a7dc42e570ae51b49ae8c5f44fc59c4eba60b1333577a1c51c0ce4063b84', 1205)
builder = read(P / 'build_frozen_transport.py')
bootstrap = read(P / 'H4-reference-export-bootstrap.py')
request = obj(P / 'H4-reference-export-frozen-launch-request.json',
              '23aab51a4e4802c75d75712e955f3558d28b187e4243d4e68a88bf3e92a3b452', 258170)
transport = obj(P / 'H4-reference-export-transport-manifest.json',
                '78fff1b9faf93f1c8fcd9659010ede4ef4ad13cadc8416cfcb4d72bff92ae2c2', 1668)
assert request.pop('stdin').encode() == bootstrap
assert request == {'host': 'desktop', 'executable': '/usr/bin/python3', 'args': ['-B', '-'],
    'cwd': '/home/qian-qi/work', 'env': {'PYTHONDONTWRITEBYTECODE': '1'},
    'timeout_seconds': 900, 'idempotency_key': '93bfc-hepta-h4-actual-reference-images-export-01'}
bootstrap_ast = ast.parse(bootstrap)
parameters = literal(bootstrap_ast, 'FROZEN_TRANSPORT')
expected = literal(bootstrap_ast, 'EXPECTED')
payload, packed_size, packed_sha, raw_size, raw_sha = parameters
assert packed_size == 190197 <= 4 * 1024 * 1024
assert raw_size == 1706220 <= 4 * 1024 * 1024
assert len(payload) == 4 * ((packed_size + 2) // 3)
packed = base64.b64decode(payload, validate=True)
assert len(packed) == packed_size and hashlib.sha256(packed).hexdigest() == packed_sha
d = zlib.decompressobj()
bundle = d.decompress(packed, raw_size + 1)
assert len(bundle) == raw_size and d.eof and not d.unconsumed_tail and not d.unused_data
assert hashlib.sha256(bundle).hexdigest() == raw_sha and not d.flush()
assert (packed_size, packed_sha, raw_size, raw_sha) == (
    transport['compressed_transport_bytes'], transport['compressed_transport_sha256'],
    transport['decoded_bundle_bytes'], transport['decoded_bundle_sha256'])
document = json.loads(bundle)
assert set(document) == {'files'} and len(document['files']) == 2
originals = {'archive_reference.py': exporter, 'H4-reference-export-plan.json': plan_raw}
actual_names = set()
for row in document['files']:
    assert set(row) == {'name', 'bytes', 'sha256', 'data_base64'}
    assert row['name'] in originals and row['name'] not in actual_names
    actual_names.add(row['name'])
    raw = base64.b64decode(row['data_base64'], validate=True)
    assert raw == originals[row['name']]
    assert row['bytes'] == len(raw) and row['sha256'] == hashlib.sha256(raw).hexdigest()
    assert expected[row['name']] == {'bytes': len(raw), 'sha256': row['sha256']}
assert actual_names == set(originals) == set(expected)
builder_ast = ast.parse(builder)
tails = [node.value.value for node in ast.walk(builder_ast)
         if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
         and node.target.id == 'script' and isinstance(node.value, ast.Constant)
         and isinstance(node.value.value, str)]
assert len(tails) == 1
assert bootstrap.decode() == (decoder.decode() + '\nimport json,os,stat\nfrom pathlib import Path\n'
    + 'FROZEN_TRANSPORT = ' + repr(parameters) + '\n'
    + 'EXPECTED = ' + repr(expected) + '\n' + tails[0])
for key in ('bootstrap', 'launch'):
    row = transport[key]
    read(Path(row['path']), row['sha256'], row['bytes'])

mapping_path = W / 'model_storage/h4-capture-repair/native/joint-h4-native-attempt-1/h4-actual-image-inventory.json'
mapping_raw = read(mapping_path, 'a1e42612d6a89337144b00335da2fa690dc7f503b46532ff795f0c92198bdd9c', 525002)
assert base64.b64decode(plan['source_map']['data_base64'], validate=True) == mapping_raw
assert plan['source_map']['bytes'] == len(mapping_raw)
assert plan['source_map']['sha256'] == hashlib.sha256(mapping_raw).hexdigest()
mapping = json.loads(mapping_raw)
assert (plan['source_commit'], plan['source_tree']) == (
    '6db78eca53a5acdda0d96873d3f4cd65863426f0', 'e91f5994017fc5d2cfe58d405a20ee6ad9376772')
assert (mapping['source_commit'], mapping['source_tree']) == (plan['source_commit'], plan['source_tree'])
assert mapping['status'] == 'PASSED_ONE_SOURCE_DESKTOP_GATES_ONLY'
assert mapping['actual_fd_records'] == 301 and mapping['actual_live_records'] == 294
assert mapping['partial_artifacts'] == []
assert plan['phase'] == 'H4' and plan['native_reexecution'] is False
assert plan['transport_budget_seconds'] == request['timeout_seconds'] == 900
assert plan['part_bytes'] == 4194304 and plan['max_archive_bytes'] == 67108864
assert len(plan_raw) <= 2 * 1024 * 1024
parent_pin = literal(ast.parse(exporter), 'PINNED_PARENT')
assert set(plan['parent']) == set(parent_pin) | {'archive_path', 'completion_path'}
assert all(plan['parent'][key] == value for key, value in parent_pin.items())
parent_index = obj(W / 'w1/h3-elf-export/H3-actual-export-index.json',
                   parent_pin['index_sha256'], parent_pin['index_bytes'])
parent_completion = obj(W / 'w1/h3-elf-export/H3-export-completion.json', parent_pin['completion_sha256'])
assert parent_completion['status'] == 'COMPLETE'
assert parent_completion['archive_sha256'] == parent_pin['archive_sha256']
assert parent_completion['archive_bytes'] == parent_pin['archive_bytes']
assert parent_completion['archive_path'] == plan['parent']['archive_path']
parent_rows = {row['sha256']: row for row in parent_index['files']}
original_rows = {row['sha256']: row for row in mapping['images']}
assert len(parent_rows) == len(original_rows) == len(plan['files']) == 11
seen = set()
for row in plan['files']:
    sha = row['sha256']
    assert sha not in seen
    seen.add(sha)
    original = original_rows[sha]
    assert row['name'] == 'H4/elf/' + sha + '.elf'
    assert row['bytes'] == original['bytes'] == parent_rows[sha]['bytes']
    assert row['source_path'] == original['retained_aliases'][0]
    assert row['aliases'] == original['retained_aliases']
    assert row['original_actual_paths'] == original['actual_paths']
    assert row['original_observations'] == original['observations']
    assert row['representation'] == 'referenced-complete-image'
    assert row['parent_reference'] == {'archive_sha256': parent_pin['archive_sha256'],
        'archive_bytes': parent_pin['archive_bytes'], 'index_sha256': parent_pin['index_sha256'],
        'member': parent_rows[sha]['name'], 'bytes': row['bytes'], 'sha256': sha}
    safe_absolute(row['source_path'], plan['source_root'])
assert len(seen) == 11
assert sum(len(row['aliases']) for row in plan['files']) == 32
assert sum(len(row['original_observations']) for row in plan['files']) == 597
assert plan['total_actual_elf_bytes'] == plan['referenced_elf_bytes'] == 1674575368
assert plan['embedded_elf_bytes'] == 0
assert sum(row['bytes'] for row in plan['files']) == 1674575368
outcome = {key: value for key, value in mapping.items() if key not in ('images', 'source_commit', 'source_tree')}
outcome.update(result=mapping['status'], native_job_id=mapping['job_id'])
assert plan['original_run_outcome'] == outcome
release = obj(W / 'w1/H4-owned-release-probe/proof.json',
              'dcdd164eb680465a440bf9dc4e11ab68c5598d8cb86a4d99320784d0a5b68107')
assert release['job_id'] == plan['release_prerequisite']['job_id'] == mapping['job_id'] == '1a1ade2970f-fc05-5b5c'
assert plan['release_prerequisite']['sha256'] == 'dcdd164eb680465a440bf9dc4e11ab68c5598d8cb86a4d99320784d0a5b68107'
assert release['owned_processes_clear'] is True and release['failures'] == [] and release['processes_killed'] is False
assert release['original_authoritative_terminal'] == {'at_unix_ms': 1793919910435,
    'exit_code': 0, 'state': 'succeeded', 'timed_out': False}
for path in [plan['source_root'], plan['output_directory'], plan['release_prerequisite']['path'],
             plan['parent']['archive_path'], plan['parent']['completion_path']]:
    safe_absolute(path)
assert plan['output_directory'] == '/home/qian-qi/work/hepta-h4-actual-reference-export-20261105-93bfc-01'
assert plan['capture_limits']['actual_remote_reads_pending'] is True

utility = obj(P / 'transport-utility-receipt.json')
assert utility['exit_code'] == 0
for key in ['stdout', 'stderr']:
    row = utility[key]
    raw = read(Path(row['path']), row['sha256'], row['bytes'])
    if key == 'stderr':
        assert raw.count(b' ... ok\n') == 3 and b'Ran 3 tests in 0.001s\n\nOK\n' in raw
for name in ['test_transport_payload.py', 'transport_payload.py']:
    read(P / name, utility[name]['sha256'], utility[name]['bytes'])
frozen = obj(P / 'H4-frozen-archive-preparation-delivery.json')
assert frozen['archive_dispatched'] is False and frozen['actual_native_reruns'] == 0
assert len(frozen['files']) == frozen['file_count'] == 22
assert sum(row['bytes'] for row in frozen['files']) == frozen['total_bytes'] == 2681506
for row in frozen['files']:
    path = Path(row['path'])
    read(path if path.is_absolute() else W / path, row['sha256'], row['bytes'])
for rel in ['pq_recovery/h4-actual-review/review.json', 'pq_recovery/h4-actual-review/delivery-manifest.json',
            'pq_recovery/h4-actual-review/delivery-inventory-review.json',
            'pq_recovery/h4-content-reference-review/review.json',
            'pq_recovery/h4-content-reference-review/delivery-manifest.json']:
    read(W / rel)

for original, meta in INPUTS.items():
    target = R / 'inputs' / original
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = (W / original).read_bytes()
    assert len(raw) == meta['bytes'] and hashlib.sha256(raw).hexdigest() == meta['sha256']
    if target.exists():
        assert target.read_bytes() == raw
    else:
        target.write_bytes(raw)
result = {
    'schema': 'H4-actual-reference-plan-independent-input-binding-v1',
    'status': 'EXACT_FROZEN_INPUTS_AND_BOUNDED_TRANSPORT_MATCH',
    'source_commit': plan['source_commit'], 'source_tree': plan['source_tree'],
    'native_job_id': mapping['job_id'], 'request': request,
    'compressed_bytes': packed_size, 'decoded_bundle_bytes': raw_size,
    'exact_transport_members': sorted(actual_names),
    'bootstrap_decoder_and_reviewed_builder_tail_byte_identical': True,
    'original_inventory_bytes_exact': True, 'original_outcome_fields_exact': True,
    'actual_inventory_images': 11, 'original_aliases': 32, 'original_observations': 597,
    'referenced_complete_images': 11, 'embedded_complete_images': 0,
    'referenced_elf_bytes': 1674575368, 'embedded_elf_bytes': 0,
    'fixed_parent_identity': parent_pin,
    'actual_h4_selected_retained_source_reads_here': 0,
    'actual_h3_whole_archive_reads_here': 0,
    'existing_local_transport_controls': {'passed': 3, 'receipt_elapsed_seconds': utility['elapsed_seconds'],
        'unit_reported_seconds': 0.001, 'independently_rerun': False, 'native_credit': False},
    'inputs': [{'path': path, **meta} for path, meta in sorted(INPUTS.items())],
    'remote_calls': 0, 'native_runs': 0, 'archive_dispatches': 0,
    'archive_completion_or_consumer_credit': False,
}
(R / 'input-binding-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key not in ('inputs', 'fixed_parent_identity')}, ensure_ascii=False))
