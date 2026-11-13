import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
RUN = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1')
RECOVERY = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def identity(value):
    return {k: value[k] for k in ('bytes', 'sha256', 'git_blob')}


def original(raw):
    outer = json.loads(raw)
    assert outer.get('isError') is False
    if outer.get('structuredContent') is not None:
        return outer['structuredContent']
    text = [item['text'] for item in outer['content'] if item['type'] == 'text']
    assert len(text) == 1
    return json.loads(text[0])


index_raw = (RUN / 'RUNTIME_CLOSED_ARCHIVE_INPUTS.json').read_bytes()
assert pin(index_raw)['git_blob'] == 'a7841063b226fb1637c7065e6df9e50d9f0ed5f8'
index = json.loads(index_raw)
assert len(index['entries']) == 120
data = {}
blobs = {}
for entry in index['entries']:
    raw = Path(entry['local_path']).read_bytes()
    assert pin(raw) == identity(entry)
    assert entry['name'] not in data
    data[entry['name']] = raw
    blobs[entry['git_blob']] = raw
recovery_placement_raw = (RECOVERY / 'PLACEMENT.json').read_bytes()
assert pin(recovery_placement_raw)['git_blob'] == '72013de1fe394939b280e0cb0aba68bc4dbe80d2'
for entry in json.loads(recovery_placement_raw)['entries']:
    raw = Path(entry['local_path']).read_bytes()
    assert pin(raw) == identity(entry)
    blobs[entry['git_blob']] = raw

request = json.loads(data['ACTUAL_PROCESS_INPUT.original.json'])
assert pin(data['ACTUAL_PROCESS_INPUT.original.json'])['git_blob'] == 'b63bd0d12684a3ba39e63f1f12fef56cb56cb3d9'
admission = original(data['MAIN_ADMISSION.original.json'])
job = admission['job']
assert job['id'] == '1a1d41eb3ef-392-2b2'
assert admission['reused'] is False and admission['launch']['ok'] is True
assert job['launch_state'] == 'launched' and job['env_keys'] == []
for key in ('host', 'executable', 'args', 'cwd', 'idempotency_key'):
    assert job[key] == request[key]
assert request['timeout_seconds'] == 2100
normal = original(data['MAIN_STATUS_02.original.json'])
assert normal['job_id'] == job['id'] and normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert all(normal[k] is True for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed'))
assert all(normal[k] is False for k in ('timed_out', 'cancelled', 'automatic_retry'))
assert normal['log_truncated'] == {'stderr': False, 'stdout': False}
assert normal['log_errors'] == {'stderr': None, 'stdout': None}

artifacts = json.loads(data['ARTIFACTS.json'])
known = {e['git_blob']: identity(e) for e in index['entries']}
for entry in artifacts['files']:
    known[entry['git_blob']] = identity(entry)
    if 'raw_git_blob' in entry:
        known[entry['raw_git_blob']] = {'bytes': entry['raw_bytes'], 'sha256': entry['raw_sha256'], 'git_blob': entry['raw_git_blob']}
groups = {}
streams = {'stdout': [], 'stderr': []}
read_count = 0
for name, raw in data.items():
    if not re.search(r'_READ_\d+\.original\.json$', name):
        continue
    read_count += 1
    value = original(raw)
    if 'data_base64' in value:
        body = base64.b64decode(value['data_base64'], validate=True)
        assert hashlib.sha256(body).hexdigest() == value['chunk_sha256']
        assert value['offset'] + len(body) == value['next_offset'] <= value['size']
        groups.setdefault((value['path'], value['version']), []).append((value, body, name))
    else:
        assert value['job_id'] == job['id'] and value['audit_recorded'] is True
        assert set(value) == {'audit_recorded', 'job_id', 'stdout', 'stderr'}
        for stream in streams:
            chunk = value[stream]
            body = bytes.fromhex(chunk['bytes_hex'])
            assert body == chunk['text'].encode()
            assert chunk['offset'] + len(body) == chunk['next_offset'] <= chunk['size']
            streams[stream].append((chunk, body, name))
assert read_count == 51
binary_checks = []
for (path, version), chunks in sorted(groups.items()):
    chunks.sort(key=lambda item: item[0]['offset'])
    body = bytearray()
    for value, chunk, name in chunks:
        assert value['offset'] == len(body)
        body.extend(chunk)
    assert chunks[-1][0]['eof'] is True and len(body) == chunks[-1][0]['size']
    body = bytes(body)
    observed = pin(body)
    assert known[observed['git_blob']] == observed
    if observed['git_blob'] in blobs:
        assert blobs[observed['git_blob']] == body
    expanded = None
    if path.endswith('.gz'):
        raw = gzip.decompress(body)
        expanded = pin(raw)
        assert known[expanded['git_blob']] == expanded
        if expanded['git_blob'] in blobs:
            assert blobs[expanded['git_blob']] == raw
    binary_checks.append({'path': path, 'version': version, 'original_sdk_chunks': len(chunks),
                          'complete_raw_identity': observed, 'gzip_expanded_identity': expanded})
stream_checks = []
for stream, chunks in streams.items():
    body = bytearray()
    for value, chunk, name in chunks:
        assert value['offset'] == len(body)
        body.extend(chunk)
    assert chunks[-1][0]['eof'] is True
    body = bytes(body)
    assert len(body) == normal['log_bytes'][stream]['seen'] == normal['log_bytes'][stream]['stored']
    assert body == data['MAIN_' + stream.upper() + '.complete.log']
    stream_checks.append({'stream': stream, 'original_sdk_chunks': len(chunks), 'identity': pin(body)})

packet_checks = []
selected = ('apply.after.postimages.json.gz', 'fmt.after.postimages.json.gz',
            'final.postimages.json.gz', 'final.inventory.json.gz')
for name in selected:
    entries = [e for e in artifacts['files'] if e['name'] == name]
    assert len(entries) == 1
    entry = entries[0]
    compressed = bytearray()
    for part in entry['parts']:
        ascii_raw = blobs[part['git_blob']]
        assert pin(ascii_raw) == identity(part)
        chunk = base64.b64decode(ascii_raw.strip(), validate=True)
        assert part['decoded_offset'] == len(compressed) and part['decoded_bytes'] == len(chunk)
        assert hashlib.sha256(chunk).hexdigest() == part['decoded_sha256']
        compressed.extend(chunk)
    compressed = bytes(compressed)
    assert pin(compressed) == identity(entry)
    expanded = gzip.decompress(compressed)
    assert pin(expanded) == {'bytes': entry['raw_bytes'], 'sha256': entry['raw_sha256'], 'git_blob': entry['raw_git_blob']}
    if name == 'final.inventory.json.gz':
        assert expanded == (ROOT / 'ACTUAL_FMT_FINAL_INVENTORY.reconstructed.json').read_bytes()
    packet_checks.append({'name': name, 'ascii_parts': len(entry['parts']), 'gzip': pin(compressed), 'raw': pin(expanded)})

states = ('SOURCE_GIT_STATE.before.json', 'apply.after.git-state.json', 'fmt.after.git-state.json', 'final.git-state.json')
assert all(data[name] == data[states[0]] for name in states)
assert pin(data[states[0]])['git_blob'] == '6887b270c7d0c6273c644268d3d260c9aee3aa00'
assert data['SOURCE_GIT_METADATA.before.json'] == data['SOURCE_GIT_METADATA.after.json']
assert pin(data['SOURCE_GIT_METADATA.after.json'])['git_blob'] == 'd13c50e149ba23ff1acbd0f99b29669131c1312b'
inputs = json.loads(data['INPUT_IDENTITIES.json'])
commands = json.loads(data['READONLY_COMMANDS.json'])
assert len(inputs) == 39 and len(commands) == 41 and all(c['returncode'] == 0 for c in commands)
result = json.loads(data['RESULT.json'])
assert result['historical_fix']['returncode'] == 101 and result['historical_fix']['already_consumed'] is True
assert result['historical_fix_lint_success'] is False and result['prior_fix_reclassified'] is False
assert result['attempted_commands'] == ['fmt'] and result['fix_dispatched'] is False
assert result['test_commands_dispatched'] == 0 and result['qualification'] is False
assert all(a['status'] == 'verified' for a in result['final_audits'])
assert result['stages'] == [json.loads(data['fmt.terminal.json'])]
assert result['stages'][0]['execution'] == json.loads(data['fmt.execute_logged.original.json'])
assert result['stages'][0]['execution']['returncode'] == 0

review = {
    'format': 'hepta-root-actual-fmt-original-runtime-closure-review-v1',
    'scope': 'Independent offline full-original SDK decoding, byte/pin/coverage and receipt comparison. No fresh H inspection, command execution, grant, source activation or behavioral qualification.',
    'runtime_closed_input_index': pin(index_raw), 'runtime_local_files_checked_against_root_full_git_get_pins': 120,
    'inventory_recovery_placement': pin(recovery_placement_raw), 'job_id': job['id'],
    'request': pin(data['ACTUAL_PROCESS_INPUT.original.json']), 'admission': pin(data['MAIN_ADMISSION.original.json']),
    'supervisor_normal': pin(data['MAIN_STATUS_02.original.json']), 'result': pin(data['RESULT.json']),
    'original_read_sdks': read_count, 'binary_reads': binary_checks, 'streams': stream_checks,
    'lossless_original_containers': packet_checks, 'raw_git_state_four_paths_equal': True,
    'raw_git_metadata_both_paths_and_previous_failed_final_equal': True,
    'nanosecond_policy': 'Original metadata and SDK bytes retained unchanged; Python integers only. No JavaScript reserialization of raw nanosecond fields or request fingerprints.',
    'inputs_reported_unchanged': len(inputs), 'readonly_commands_all_returned_zero': len(commands),
    'original_complete_producer_audits': ['actual_complete_source_and_git', 'original_inputs', 'same_source_coordination_lock'],
    'lease_limit': 'Cooperative source writers only. Three process-guard samples are point observations, not system-wide exclusion.',
    'retention_limit': '217 native artifact records are not claimed to have each been externally downloaded. The 555136-byte HEAD working patch is retained on the original host and its pin is recorded; it is not a downloaded evidence leaf.',
    'inventory_and_final_transition_provenance': 'Exact reconstruction, independently checked against all original raw/gzip/part pins; not a second native full-inventory or final-postimage download.',
    'historical_fix_returncode': 101, 'historical_fix_lint_success': False, 'current_fmt_returncode': 0,
    'tests_dispatched': 0, 'qualification': False, 'real_qualified_chains': 0,
}
target = ROOT / 'ROOT_ACTUAL_FMT_RUNTIME_CLOSURE_REVIEW.json'
target.write_text(json.dumps(review, sort_keys=True, indent=2) + '\n')
print(json.dumps({'review': pin(target.read_bytes()), 'read_sdks': read_count,
                  'complete_binary_paths': len(binary_checks), 'lossless_containers': len(packet_checks)}, sort_keys=True))
