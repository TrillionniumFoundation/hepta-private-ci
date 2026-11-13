"""Independent Root replay of the fixed, already completed stage evidence.

Only reads cloud evidence and writes this review. Never imports a project,
executes an original program, contacts H, retries an operation, or changes source.
All native JSON integers are parsed as exact Python ints. Original bytes are
hashed before parsing; no original is reserialized or overwritten.
"""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-b608-history-transport-staging-runtime-v1')
OUT = Path('/tmp/hepta-36fa-root-history-stage-complete-review-v1')
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1'
JOB = '1a1d52e0d88-392-784'
APPROVAL = '75003db540da7000de0b350b5fa53ac0b61c6644'
KEYS = ('bytes', 'sha256', 'git_blob')
used = {}


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        assert key not in value, ('duplicate key', key)
        value[key] = item
    return value


def parse(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates)


def read(name):
    path = ROOT / name
    assert path.parent == ROOT
    raw = path.read_bytes()
    used[name] = pin(raw)
    return raw


def record(name):
    return parse(read(name))


def equal(raw, expected):
    assert pin(raw) == {k: expected[k] for k in KEYS}, (pin(raw), expected)
    return raw


def sdk(name):
    value = record(name)
    assert not value.get('isError'), ('SDK error', name)
    assert len(value['content']) == 1 and value['content'][0]['type'] == 'text'
    return parse(value['content'][0]['text'])


def chunk(name, path, size, version, offset):
    value = sdk(name)
    assert set(value) == {'chunk_sha256', 'data_base64', 'eof', 'next_offset', 'offset', 'path', 'size', 'version'}
    assert value['path'] == path and value['size'] == size
    assert value['version'] == version and value['offset'] == offset
    fields = version.split(':')
    assert len(fields) == 5 and all(x.isdigit() for x in fields)
    assert int(fields[2]) == size
    body = base64.b64decode(value['data_base64'], validate=True)
    assert 0 < len(body) <= 65536
    assert value['next_offset'] == offset + len(body) <= size
    assert value['eof'] is (value['next_offset'] == size)
    assert hashlib.sha256(body).hexdigest() == value['chunk_sha256']
    return body


approval_raw = read('ROOT_APPROVAL.original.json')
assert pin(approval_raw)['git_blob'] == APPROVAL
approval = parse(approval_raw)
assert approval['qualification'] is False
request_raw = equal(read('STAGE_PROCESS_INPUT.original.json'), approval['stage_request'])
request = parse(request_raw)
assert set(request) == {'args', 'cwd', 'executable', 'host', 'idempotency_key', 'stdin', 'timeout_seconds'}
for field in ('cwd', 'executable', 'host', 'idempotency_key', 'timeout_seconds'):
    assert request[field] == approval['stage_request'][field]
assert request['args'][0:2] == ['-B', '-c'] and len(request['args']) == 3
script = equal(read('STAGE_BOOTSTRAP.original.py'), approval['stage_request']['script'])
assert script == request['args'][2].encode()
payload_raw = equal(read('STAGE_STDIN.original.json'), approval['stage_request']['stdin'])
assert payload_raw == request['stdin'].encode()
payload = parse(payload_raw)
constants = {}
for node in ast.parse(script).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id in ('MANIFEST_PIN', 'HISTORICAL_GUARD_PIN', 'PACKET_PIN', 'GZIP_PIN', 'PART_INPUTS'):
            constants[node.targets[0].id] = ast.literal_eval(node.value)
assert len(constants) == 5
manifest_raw = equal(base64.b64decode(payload['manifest_base64'], validate=True), constants['MANIFEST_PIN'])
guard_raw = equal(base64.b64decode(payload['historical_guard_base64'], validate=True), constants['HISTORICAL_GUARD_PIN'])
manifest = parse(manifest_raw)
assert len(manifest['rows']) == 55 and manifest['control'] == BASE

index = record('EXACT_APPROVED_WRITE_INDEX.json')
assert index['approval'] == APPROVAL and len(index['requests']) == 17
assert len(approval['allowed_writes']) == 17
parts = []
part_rows = []
part_reads = 0
for number, (spec, allowed, declared) in enumerate(zip(index['requests'], approval['allowed_writes'], constants['PART_INPUTS'], strict=True), 1):
    assert spec['sequence'] == allowed['sequence'] == number
    path = BASE + f'.payload.json.gz.part-{number:03d}'
    assert path == spec['native_path'] == allowed['path'] == declared['path']
    assert allowed['host'] == 'desktop' and allowed['expected_version'] == 'absent' and allowed['dispatch_limit'] == 1
    assert spec['request'] == {'bytes': allowed['request_bytes'], 'sha256': allowed['request_sha256'], 'git_blob': allowed['request_git_blob']}
    assert spec['part'] == declared['pin']
    intent = record(f'PART_{number:03d}.WRITE_INTENT.json')
    assert intent['approval'] == APPROVAL and intent['sequence'] == number
    assert intent['request'] == spec['request'] and intent['expected_version'] == 'absent'
    assert intent['dispatch_limit'] == 1 and intent['native_path'] == path
    write = sdk(f'PART_{number:03d}.WRITE.original.json')
    assert write['size'] == write['written'] == spec['part']['bytes']
    assert write['sha256'] == spec['part']['sha256'] and write['mode'] == 0o600
    version = write['version']
    plan = record(f'PART_{number:03d}.READ_PLAN.json')['requests']
    offset = 0
    chunks = []
    for req in plan:
        assert req == {'host': 'desktop', 'path': path, 'expected_version': version, 'offset': offset, 'limit': 65536}
        name = f'PART_{number:03d}.READ_{offset:06d}.original.json'
        if number == 8 and offset == 262144:
            failure = record(name)
            assert failure['isError'] is True and pin(read(name))['git_blob'] == 'ee720552601b4fd39acb31c5a6b5128f3dce17cd'
            assert 'failed with 255' in failure['content'][0]['text']
            recovery = record('PART_008.RECONCILE_01.INTENT.json')
            assert recovery['request'] == req and recovery['write_repeated'] is False
            assert recovery['approval'] == APPROVAL
            equal(read(name), recovery['original_failed_read'])
            name = 'PART_008.READ_262144.RECONCILE_01.original.json'
        body = chunk(name, path, spec['part']['bytes'], version, offset)
        chunks.append(body)
        offset += len(body)
        part_reads += 1
    complete = equal(b''.join(chunks), spec['part'])
    assert offset == len(complete) and read(f'PART_{number:03d}.readback.bin') == complete
    parts.append(complete)
    part_rows.append({'sequence': number, 'path': path, 'version': version, 'body': pin(complete), 'successful_read_chunks': len(chunks)})
assert part_reads == 82
assert len(list(ROOT.glob('PART_*.WRITE.original.json'))) == 17
assert len(list(ROOT.glob('PART_*.READ_*.original.json'))) == 83
compressed = equal(b''.join(parts), constants['GZIP_PIN'])
packet_raw = equal(gzip.decompress(compressed), constants['PACKET_PIN'])
packet = parse(packet_raw)
assert packet['manifest'] == pin(manifest_raw) and len(packet['files']) == 55
originals = {}
for entry, spec in zip(packet['files'], manifest['rows'], strict=True):
    assert entry['role'] == spec['role'] and entry['role'] not in originals
    body = equal(base64.b64decode(entry['data_base64'], validate=True), spec['pin'])
    originals[entry['role']] = body
assert sum(map(len, originals.values())) == 7976106

receipt_raw = read('STAGING_READBACK.json')
receipt = parse(receipt_raw)
assert pin(receipt_raw)['git_blob'] == '17d4ea78bc34facc9129c6a634fe750105d75bc4'
receipt_sdk = sdk('STAGING_READBACK_01.original.json')
receipt_body = chunk('STAGING_READBACK_01.original.json', BASE + '/STAGING_READBACK.json', len(receipt_raw), receipt_sdk['version'], 0)
assert receipt_body == receipt_raw
assert receipt['control'] == BASE and receipt['historical_original_count'] == 55
assert receipt['part_inputs'] == constants['PART_INPUTS']
for field in ('automatic_retry', 'main_dispatched', 'old_path_writes', 'qualification', 'source_writes'):
    assert receipt[field] is False
assert receipt['compressed_packet'] == pin(compressed) and receipt['packet'] == pin(packet_raw)
assert receipt['manifest'] == pin(manifest_raw)
expected = {
    BASE + '/ACTUAL_TRANSPORT_BOOTSTRAP.py': script,
    BASE + '/ACTUAL_TRANSPORT_ARGV.json': (json.dumps([request['executable'], *request['args']], ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode(),
    BASE + '/ACTUAL_TRANSPORT_PAYLOAD.json': payload_raw,
    BASE + '/TRANSPORT_MANIFEST.json': manifest_raw,
    BASE + '/historical-runtime-guard.py': guard_raw,
}
expected.update({row['transport_path']: originals[row['role']] for row in manifest['rows']})
assert len(expected) == 60 and len(receipt['files']) == 60
assert {row['path']: {k: row[k] for k in KEYS} for row in receipt['files']} == {path: pin(body) for path, body in expected.items()}
fixed_plan = record('FIXED_61_READBACK_PLAN.json')
assert fixed_plan['job_id'] == JOB and fixed_plan['file_count_including_receipt'] == 61
assert fixed_plan['same_version_required'] is True and len(fixed_plan['remaining_fixed_files']) == 60
assert {row['path'] for row in fixed_plan['remaining_fixed_files']} == set(expected)
file_rows = []
file_reads = 1
whole_bytes = len(receipt_raw)
for number, spec in enumerate(fixed_plan['remaining_fixed_files'], 1):
    assert spec['number'] == number
    path = spec['path']
    equal(expected[path], spec)
    local_plan = record(f'FILE_{number:03d}.READ_PLAN.json')
    assert local_plan['expected'] == spec
    version = local_plan['version']
    chunks = []
    offset = 0
    names = sorted(ROOT.glob(f'FILE_{number:03d}.READ_*.original.json'))
    assert names
    for name in names:
        assert name.name == f'FILE_{number:03d}.READ_{offset:06d}.original.json'
        body = chunk(name.name, path, spec['bytes'], version, offset)
        chunks.append(body)
        offset += len(body)
        file_reads += 1
    complete = equal(b''.join(chunks), spec)
    assert complete == expected[path] == read(f'FILE_{number:03d}.readback.bin')
    assert offset == spec['bytes']
    whole_bytes += len(complete)
    file_rows.append({'number': number, 'path': path, 'version': version, 'body': pin(complete), 'successful_read_chunks': len(chunks)})
assert file_reads == 177 and whole_bytes == 8301563
assert len(list(ROOT.glob('FILE_*.READ_*.original.json'))) == 176
complete_report = record('COMPLETE_61_READBACK_REVIEW.json')
assert pin(read('COMPLETE_61_READBACK_REVIEW.json'))['git_blob'] == '3b1c1096f1cd29805f55553ad6a51ffbbae86501'
assert complete_report['all_complete_same_version_readback'] is True and complete_report['required_files'] == 61
assert complete_report['job_id'] == JOB and complete_report['source_or_native_qualification'] is False

review = {
    'format': 'hepta-root-independent-complete-history-stage-replay-v1',
    'approval': APPROVAL, 'job_id': JOB,
    'verification': 'Root-authored independent strict raw-SDK reconstruction; no project or original verifier executed',
    'same_version_part_writes': 17, 'successful_part_read_chunks': 82,
    'retained_failed_part_read_chunks': 1, 'same_version_reconciliation_only': True,
    'successful_fixed_file_read_chunks': file_reads, 'complete_fixed_files': 61,
    'complete_fixed_file_bytes': whole_bytes, 'complete_historical_originals': 55,
    'original_historical_bytes': 7976106, 'parts': part_rows, 'files': file_rows,
    'receipt': {'body': pin(receipt_raw), 'version': receipt_sdk['version']},
    'original_SDK_bytes_preserved': True, 'native_integers_parsed_as_exact_Python_ints': True,
    'all_expected_approved_control_and_original_bytes_match': True,
    'actual_dispatch_and_terminal_binding_review': 'e76c421524b51eecb885a0af98fe141f5c865063',
    'actual_core_stage_review': '931cbc2857c8c987c56a012d72ffe36f455cab92',
    'prior_partial_reviews_preserved': True,
    'archival_transport_full_Git_GET_verification': 'separate required closure; this script reads the closed cloud originals',
    'limits': ['Binary read responses bind exact versions and bytes; they do not independently expose owner UID or full nine-field stat.',
               'Owned 0600 and nine-stat checks are performed by the exact approved stage program; its unchanged read-back code and normal exit are separately bound.',
               'Worker request digest canonicalization remains unreconstructed; full saved request and echoed admission fields are separately bound.',
               'Historical producer bytes are not current live source, environment, or Git observations.'],
    'source_or_native_dispatched_by_this_script': False, 'H_calls': 0,
    'qualification': False, 'real_qualified_task_chains': 0,
    'inputs': [{'name': name, **value} for name, value in sorted(used.items())],
}
raw = (json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
path = OUT / 'ROOT_COMPLETE_READBACK_REVIEW.json'
if path.exists():
    assert path.read_bytes() == raw
else:
    with path.open('xb') as stream:
        stream.write(raw)
print(json.dumps({'review': pin(raw), 'input_files': len(used), 'complete_files': 61, 'complete_bytes': whole_bytes, 'qualification': False}))
