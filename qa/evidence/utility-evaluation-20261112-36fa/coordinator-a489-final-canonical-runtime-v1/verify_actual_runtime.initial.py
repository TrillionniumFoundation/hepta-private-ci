"""Offline reconciliation of the one completed canonical job's original records."""
import base64
import gzip
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1'
REPO = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
JOB = '1a1d4cbd33e-392-5a9'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def get(name):
    return json.loads((ROOT / name).read_bytes())

def payload(name):
    outer = get(name)
    assert not outer.get('isError'), name
    texts = [row['text'] for row in outer['content'] if row['type'] == 'text']
    assert len(texts) == 1
    return json.loads(texts[0])

def create(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), **identity(raw)}

approval = get('ROOT_EXACT_APPROVAL.original.json')
request_raw = (ROOT / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes()
assert identity(request_raw) == approval['exact_request']
request = json.loads(request_raw)
assert sorted(request) == approval['exact_request_fields']
assert request['idempotency_key'] == approval['idempotency_key']
assert request['host'] == 'desktop' and request['cwd'] == '/home/qian-qi' and request['executable'] == '/usr/bin/python3'
assert request['timeout_seconds'] == 900 and request['args'][:2] == ['-B', '-c'] and len(request['args']) == 3
assert identity(request['args'][2].encode()) == approval['exact_bootstrap']
assert identity(request['stdin'].encode()) == approval['exact_stdin']
admission = payload('MAIN_ADMISSION.original.json')
assert admission['job']['id'] == JOB and admission['job']['idempotency_key'] == request['idempotency_key']
assert admission['job']['args'] == request['args'] and admission['job']['executable'] == request['executable']
assert admission['job']['cwd'] == request['cwd'] and admission['job']['env_keys'] == []
assert admission['launch']['ok'] and admission['job']['launch_state'] == 'launched' and not admission['reused']
normal = payload('STATUS_02.original.json')
assert normal['job_id'] == JOB and normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert normal['output_complete'] and normal['output_durable'] and normal['terminal_publication_confirmed']
assert not normal['timed_out'] and not normal['cancelled'] and not normal['automatic_retry']
streams = payload('STREAM_READ_01.original.json')
assert streams['job_id'] == JOB
for label in ('stdout', 'stderr'):
    row = streams[label]
    raw = bytes.fromhex(row['bytes_hex'])
    assert raw == row['text'].encode() == (ROOT / (label.upper() + '.original.txt')).read_bytes()
    assert row['offset'] == 0 and row['next_offset'] == row['size'] == len(raw) and row['eof']
    assert normal['log_bytes'][label] == {'seen': len(raw), 'stored': len(raw)}
    assert normal['log_synced'][label] and not normal['log_truncated'][label] and normal['log_errors'][label] is None

result = get('RESULT.json')
catalogue_rows = get('ARTIFACTS.json')
catalogue = {row['name']: row for row in catalogue_rows}
assert len(catalogue_rows) == len(catalogue) == 505
assert result['artifacts'] == [row for row in catalogue_rows if row['name'] != 'RESULT.json']
assert identity((ROOT / 'RESULT.json').read_bytes()) == {key: catalogue['RESULT.json'][key] for key in ('bytes', 'sha256', 'git_blob')}
assert result['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY' and result['local_head_advanced']
assert result['source_repo'] == REPO and not result['qualification'] and result['test_commands_dispatched'] == 0
assert result['physical_source_writes_dispatched'] == 0 and not result['cargo_or_formatter_started']
assert not result['dependency_installation_started'] and not result['source_branch_refs_updated'] and not result['remote_ref_updates']
assert result['action_budget_seconds'] == 600 and result['record_budget_seconds'] == 180 and not result['automatic_retry']
assert [(row['check'], row['status']) for row in result['final_audits']] == [('source', 'verified'), ('git', 'verified'), ('inputs', 'verified')]
assert result['before'] == approval['before']
assert {key: result['after'][key] for key in ('commit', 'tree', 'parents', 'inventory')} == approval['expected_after_not_yet_observed']
commands = get('artifacts/COMMANDS.json')
mutations = get('artifacts/MUTATION_PROGRESS.json')
assert commands == result['commands'] and len(commands) == 94
assert mutations == result['mutation_intents'] and len(mutations) == 33
assert all(row['actual_terminal'] == 'observed' and row['returncode'] == 0 and row['timed_out'] is False for row in commands)
assert all(row['terminal'] == 'observed' and 'completed_at' in row for row in mutations)
batch = get('artifacts/OBJECT_BATCH.terminal.json')
assert batch['actual_terminal'] == 'observed' and batch['returncode'] == 0
assert batch['objects'] == batch['objects_observed'] == result['actual']['verified_snapshot_objects'] == 16523
assert (ROOT / 'artifacts/OBJECT_BATCH.stderr').read_bytes() == b''
for name in ('initial.process-preflight.json', 'immediately-before-object-import.process-preflight.json', 'immediately-before-index-head-change.process-preflight.json'):
    guard = get('artifacts/' + name)
    assert guard['active_matching_processes'] == [] and guard['unreadable_matching_processes'] == []
lease = get('artifacts/SOURCE_COORDINATION_EX.json')
assert lease['lock_acquired'] == 'LOCK_EX|LOCK_NB' and lease['device'] == 2050 and lease['inode'] == 50139448
assert lease['mode'] == 0o600 and lease['uid'] == 1000 and lease['nlink'] == 1
assert lease['path'] == '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock'

raw_inputs = json.loads(request['stdin'])['files']
decoded_inputs = {name: base64.b64decode(value, validate=True) for name, value in raw_inputs.items()}
decoded_inputs['CANONICAL_PACKET.json'] = gzip.decompress(decoded_inputs['CANONICAL_PACKET.json'])
cfg = json.loads(decoded_inputs['APPROVED_CONFIG.json'])
packet = json.loads(decoded_inputs['CANONICAL_PACKET.json'])
pins = {'driver.py': approval['four_inputs']['driver'], 'APPROVED_CONFIG.json': approval['four_inputs']['configuration'], 'CANONICAL_PACKET.json': approval['four_inputs']['canonical_packet'], 'FINAL_FORMAT_NORMAL.original.json': approval['four_inputs']['final_format_normal']}
assert set(decoded_inputs) == set(pins)
for name, raw in decoded_inputs.items():
    assert identity(raw) == pins[name]
imported = get('artifacts/OBJECT_IMPORT.json')
assert imported['verified_objects'] == 29 and imported['existing_objects_retained']
assert set(imported['actually_added_objects']) == {row['sha'] for row in packet['objects']} and len(imported['actually_added_objects']) == 29
inputs = get('artifacts/INPUTS.final.json')
assert len(inputs) == 8
for name, pin in pins.items():
    assert inputs[CONTROL + '/' + name] == pin
assert identity((ROOT / 'artifacts/FINAL_FORMAT_RESULT.original.json').read_bytes()) == result['final_format']['result']
assert identity((ROOT / 'artifacts/FINAL_FORMAT_SUPERVISOR.original.json').read_bytes()) == result['final_format']['supervisor']
assert identity((ROOT / 'artifacts/FINAL_FORMAT_GIT_STATE.original.json').read_bytes()) == result['final_format']['git_state']

metadata = {}
for side in ('before', 'final'):
    state = get('artifacts/GIT_STATE.' + side + '.json')
    result_side = 'before' if side == 'before' else 'after'
    assert state == result[result_side]['git_state']
    m = get('artifacts/GIT_METADATA.' + side + '.json')
    assert m['root'] == REPO + '/.git'
    rows = {row['path']: row for row in m['files']}
    assert len(rows) == len(m['files'])
    metadata[side] = rows
    raw_index = (ROOT / 'artifacts' / ('INDEX.' + side + '.raw')).read_bytes()
    assert len(raw_index) == state['index_bytes'] == rows['index']['bytes']
    assert hashlib.sha256(raw_index).hexdigest() == state['index_sha256'] == rows['index']['sha256']
    assert rows['HEAD']['sha256'] == state['head_raw_sha256']
    assert rows['config']['bytes'] == state['config_bytes'] and rows['config']['sha256'] == state['config_sha256']
    assert state['refs_bytes'] == 0 and state['refs_sha256'] == hashlib.sha256(b'').hexdigest()
assert (ROOT / 'artifacts/HEAD.before.raw').read_bytes() == (result['before']['commit'] + '\n').encode()
changes = [{'path': path, 'before': metadata['before'].get(path), 'after': metadata['final'].get(path)} for path in sorted(set(metadata['before']) | set(metadata['final']), key=lambda text: text.encode()) if metadata['before'].get(path) != metadata['final'].get(path)]
assert changes == result['git_metadata_actual_changes'] == get('artifacts/GIT_METADATA.allowed-actual-delta.json')
assert len(changes) == 61

staging_manifest = get('STAGING_READBACK.json')
staging_rows = {pathlib.PurePosixPath(row['path']).name: row for row in staging_manifest['files']}
assert len(staging_rows) == 7 and not staging_manifest['qualification'] and not staging_manifest['source_writes_during_staging']
staging = []
for name in ('ACTUAL_BOOTSTRAP.py', 'ACTUAL_BOOTSTRAP_ARGV.json', 'driver.py', 'APPROVED_CONFIG.json', 'FINAL_FORMAT_NORMAL.original.json'):
    original = payload('control.' + name + '.READ_01.original.json')
    raw = base64.b64decode(original['data_base64'], validate=True)
    assert original['path'] == CONTROL + '/' + name and original['offset'] == 0
    assert original['next_offset'] == original['size'] == len(raw) and original['eof']
    assert hashlib.sha256(raw).hexdigest() == original['chunk_sha256']
    assert identity(raw) == {key: staging_rows[name][key] for key in ('bytes', 'sha256', 'git_blob')}
    if name == 'ACTUAL_BOOTSTRAP.py':
        assert raw == request['args'][2].encode()
    elif name == 'ACTUAL_BOOTSTRAP_ARGV.json':
        assert json.loads(raw) == [request['executable'], *request['args']]
    else:
        assert raw == decoded_inputs[name]
    staging.append({'name': name, 'provenance': 'complete original native binary read', 'version': original['version'], **create(ROOT / 'staging' / name, raw)})
for name, raw in [('ACTUAL_BOOTSTRAP_PAYLOAD.json', request['stdin'].encode()), ('CANONICAL_PACKET.json', decoded_inputs['CANONICAL_PACKET.json'])]:
    assert identity(raw) == {key: staging_rows[name][key] for key in ('bytes', 'sha256', 'git_blob')}
    staging.append({'name': name, 'provenance': 'pre-held exact dispatched bytes, equal to original producer full-readback pins; not a new external download', **identity(raw)})
staging_review = {'format': 'hepta-canonical-original-staging-identity-closure-v1', 'job_id': JOB, 'original_manifest': identity((ROOT / 'STAGING_READBACK.json').read_bytes()), 'records': staging, 'external_full_file_reads': 5, 'large_preheld_bodies_bound_to_original_full_readback': 2, 'qualification': False}
create(ROOT / 'STAGING_IDENTITY_REVIEW.json', (json.dumps(staging_review, sort_keys=True, indent=2) + '\n').encode())

binary_reads = []
groups = {}
for path in sorted(ROOT.iterdir()):
    if not re.fullmatch(r'.+\.READ_[0-9]{2}\.original\.json', path.name):
        continue
    observation = payload(path.name)
    raw = base64.b64decode(observation['data_base64'], validate=True)
    assert hashlib.sha256(raw).hexdigest() == observation['chunk_sha256']
    binary_reads.append({'sdk_path': str(path), 'sdk_identity': identity(path.read_bytes()), 'native_path': observation['path'], 'version': observation['version'], 'offset': observation['offset'], 'next_offset': observation['next_offset'], 'size': observation['size'], 'eof': observation['eof'], 'chunk_sha256': observation['chunk_sha256']})
    groups.setdefault(observation['path'], []).append(observation)
for path, observations in groups.items():
    observations.sort(key=lambda row: row['offset'])
    cursor = 0
    for row in observations:
        assert row['offset'] == cursor and row['version'] == observations[0]['version'] and row['size'] == observations[0]['size']
        cursor = row['next_offset']
    assert cursor == observations[0]['size'] and observations[-1]['eof']
assert len(binary_reads) == 58 and len(groups) == 31

report = {'format': 'hepta-canonical-single-job-actual-native-runtime-closure-v1', 'status': 'ACTUAL_RECORDS_RECONCILED', 'job_id': JOB, 'approval': identity((ROOT / 'ROOT_EXACT_APPROVAL.original.json').read_bytes()), 'request': identity(request_raw), 'normal': identity((ROOT / 'STATUS_02.original.json').read_bytes()), 'result': identity((ROOT / 'RESULT.json').read_bytes()), 'original_artifact_catalogue': identity((ROOT / 'ARTIFACTS.json').read_bytes()), 'canonical_status': result['status'], 'before': result['before'], 'after': result['after'], 'commands_observed_zero': len(commands), 'mutations_observed': len(mutations), 'original_inputs': len(inputs), 'original_process_guard_observations': 3, 'complete_original_stream_bytes': {'stdout': 706, 'stderr': 0}, 'actual_metadata_delta_rows': len(changes), 'index_complete_delta_rows': len(get('artifacts/INDEX.complete-entry-delta.json')), 'three_final_audits': result['final_audits'], 'staging': staging_review, 'binary_reads': binary_reads, 'external_complete_native_paths': len(groups), 'external_binary_read_calls': len(binary_reads), 'original_artifact_catalogue_rows': len(catalogue_rows), 'catalogue_scope_note': 'The 505 original catalogue rows are retained as producer identities; this report does not claim that all 505 files were externally downloaded.', 'index_audit_recovery': identity((ROOT / 'recovered-index-audit/EXACT_RECOVERY_REVIEW.json').read_bytes()), 'index_audit_scope_note': 'Actual before/final raw index files were downloaded completely. Audit bytes are exact recovered content matching all original raw/gzip/part pins; no additional native lstat or audit-file download.', 'inventory_scope_note': 'The original producer performed full before/final source inventories; ordinary_path separately binds pre-held complete bytes to every actual raw/gzip/part pin. This report does not claim a second external full-inventory download.', 'head_final_scope_note': 'No separate HEAD.final.raw artifact was emitted. The original final Git state, metadata and successful detached HEAD CAS retain its observed identity.', 'transport_failures_in_this_closed_native_read_set': 0, 'qualification': False, 'source_or_native_tests_dispatched': 0, 'source_branch_refs_updated': False}
raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
print(json.dumps({'review': create(ROOT / 'ACTUAL_RUNTIME_READBACK_REVIEW.json', raw), 'binary_reads': len(binary_reads), 'paths': len(groups), 'commands': len(commands), 'mutations': len(mutations), 'inputs': len(inputs), 'staging': identity((ROOT / 'STAGING_IDENTITY_REVIEW.json').read_bytes())}))
