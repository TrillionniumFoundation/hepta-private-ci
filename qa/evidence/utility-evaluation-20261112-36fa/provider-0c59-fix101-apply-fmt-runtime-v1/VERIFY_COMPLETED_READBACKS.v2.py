"""Offline validation of already captured originals. No H, Git process, or source writes."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-fix101-apply-fmt-v1'
RUN = CONTROL + '/run'
REPO = '/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1'
JOB = '1a1d41eb3ef-392-2b2'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def load(name):
    return json.loads((ROOT / name).read_bytes())


def body(name):
    obj = load(name)
    assert not obj.get('isError'), name
    value = obj.get('structuredContent')
    if value is None:
        blocks = [item['text'] for item in obj['content'] if item['type'] == 'text']
        assert len(blocks) == 1, name
        value = json.loads(blocks[0])
    assert isinstance(value, dict), name
    return value


def create(name, raw):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        with path.open('xb') as output:
            output.write(raw)
    return {'name': name, **pin(raw)}


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def check_pin(raw, expected):
    actual = pin(raw)
    assert actual == {key: expected[key] for key in actual}, (actual, expected)
    return actual


def decode_chunks(names, native_path, expected, output_name):
    raw = b''
    version = None
    observations = []
    for index, name in enumerate(names):
        obj = body(name)
        assert obj['path'] == native_path, name
        if version is None:
            version = obj['version']
        assert obj['version'] == version and obj['size'] == expected['bytes'], name
        assert obj['offset'] == len(raw), name
        chunk = base64.b64decode(obj['data_base64'], validate=True)
        assert hashlib.sha256(chunk).hexdigest() == obj['chunk_sha256'], name
        assert obj['next_offset'] == obj['offset'] + len(chunk), name
        assert obj['eof'] == (index == len(names) - 1), name
        raw += chunk
        observations.append({'sdk': name, **pin((ROOT / name).read_bytes()),
                             'offset': obj['offset'], 'next_offset': obj['next_offset'],
                             'version': version, 'chunk_sha256': obj['chunk_sha256'],
                             'eof': obj['eof']})
    check_pin(raw, expected)
    row = create(output_name, raw)
    return raw, {'native_path': native_path, 'version': version, 'coverage': [0, len(raw)],
                 'complete_eof': True, 'actual_binary_observations': observations, 'decoded': row}


artifacts = load('ARTIFACTS.json')
artifact_map = {row['name']: row for row in artifacts['files']}
assert len(artifact_map) == len(artifacts['files']) == 217
request = load('ACTUAL_PROCESS_INPUT.original.json')
assert set(request) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert request['idempotency_key'] == 'hepta-utility-36fa-provider-0c59-fix101-apply-fmt-v1'
assert request['timeout_seconds'] == 2100
payload = json.loads(request['stdin'])
staging = load('STAGING_READBACK.json')
assert staging['qualification'] is False and staging['source_writes_during_staging'] is False
stage_map = {Path(row['path']).name: row for row in staging['files']}
assert len(stage_map) == 7
staged_expected = {name: base64.b64decode(value, validate=True) for name, value in payload['files'].items()}
assert len(staged_expected) == 4
staged_expected['REPAIR_PROPOSAL.original.json'] = gzip.decompress(staged_expected['REPAIR_PROPOSAL.original.json'])
staged_expected['ACTUAL_BOOTSTRAP.py'] = request['args'][-1].encode()
staged_expected['ACTUAL_BOOTSTRAP_PAYLOAD.json'] = request['stdin'].encode()
staged_expected['ACTUAL_BOOTSTRAP_ARGV.json'] = encode([request['executable'], *request['args']])
stage_reads = {
    'driver.py': ['STAGED_DRIVER_READ_01.original.json'],
    'APPROVED_CONFIG.json': ['STAGED_CONFIG_READ_01.original.json'],
    'FAILED_MAINTENANCE_SUPERVISOR.original.json': ['STAGED_FAILED_NORMAL_READ_01.original.json'],
    'REPAIR_PROPOSAL.original.json': [f'STAGED_REPAIR_READ_{i:02}.original.json' for i in range(1, 4)],
    'ACTUAL_BOOTSTRAP.py': ['STAGED_BOOTSTRAP_READ_01.original.json'],
    'ACTUAL_BOOTSTRAP_ARGV.json': ['STAGED_ARGV_READ_01.original.json'],
    'ACTUAL_BOOTSTRAP_PAYLOAD.json': [f'STAGED_PAYLOAD_READ_{i:02}.original.json' for i in range(1, 3)],
}
assert set(stage_map) == set(stage_reads) == set(staged_expected)
stage_reviews = []
for name, reads in stage_reads.items():
    expected = stage_map[name]
    assert expected['path'] == CONTROL + '/' + name
    check_pin(staged_expected[name], expected)
    raw, row = decode_chunks(reads, expected['path'], expected, 'STAGED_ACTUAL.' + name)
    assert raw == staged_expected[name]
    row['exact_frozen_request_bytes_equal'] = True
    stage_reviews.append(row)

apply_packet = load('apply.after.postimages.json')
change_map = {row['path']: row for row in apply_packet['changes']}
assert len(change_map) == 4
application_reviews = []
for number in range(1, 5):
    decoded = {}
    rows = []
    for kind in ('attempt', 'temporary', 'completed'):
        name = f'APPLY.{number:03}.{kind}.json'
        raw, row = decode_chunks([f'APPLY_{number:03}_{kind.upper()}_READ_01.original.json'],
                                 RUN + '/' + name, artifact_map[name], name)
        decoded[kind] = json.loads(raw)
        rows.append(row)
    attempt, temporary, completed = (decoded[kind] for kind in ('attempt', 'temporary', 'completed'))
    path = attempt['path']
    assert completed['path'] == temporary['source'] == path
    assert attempt['status'] == 'attempted' and attempt['rollback'] is False
    assert completed['status'] == 'observed_complete'
    assert attempt['at'] <= completed['at']
    assert Path(temporary['path']).parent == Path(REPO) / Path(path).parent
    assert Path(temporary['path']).name.startswith('.hepta-36fa-final-')
    change = change_map[path]
    for phase in ('before', 'after'):
        raw = base64.b64decode(change[phase + '_raw_base64'], validate=True)
        assert pin(raw) == attempt[phase]
        source_row = change[phase]
        assert source_row['path'] == path and source_row['stable'] is True
        assert pin(raw) == {'bytes': source_row['bytes'], 'sha256': source_row['sha256'],
                            'git_blob': source_row['working_blob']}
    assert completed['after'] == attempt['after']
    application_reviews.append({'path': path, 'attempt_and_observed_complete': True,
                                'exact_actual_transition_bytes_equal': True,
                                'temporary_path_same_source_parent': True,
                                'records': rows})
assert {row['path'] for row in application_reviews} == set(change_map)

terminal = body('MAIN_STATUS_02.original.json')
assert terminal['job_id'] == JOB and terminal['state'] == 'succeeded' and terminal['exit_code'] == 0
assert terminal['timed_out'] is False and terminal['cancelled'] is False and terminal['automatic_retry'] is False
assert terminal['output_complete'] is True and terminal['output_durable'] is True
assert terminal['terminal_publication_confirmed'] is True
stream_reviews = []
for stream in ('stdout', 'stderr'):
    raw = b''
    parts = []
    for name in ('MAIN_STREAM_READ_01.original.json', 'MAIN_STREAM_READ_02.original.json'):
        record = body(name)
        assert record['job_id'] == JOB
        row = record[stream]
        chunk = bytes.fromhex(row['bytes_hex'])
        assert chunk.decode('utf-8') == row['text']
        assert row['offset'] == len(raw)
        assert row['next_offset'] == row['offset'] + len(chunk)
        raw += chunk
        parts.append({'sdk': name, 'offset': row['offset'], 'next_offset': row['next_offset'],
                      'size_at_observation': row['size'], 'eof_at_observation': row['eof'],
                      'bytes_hex_equals_text': True})
    assert row['eof'] is True and row['size'] == len(raw)
    assert terminal['log_bytes'][stream] == {'seen': len(raw), 'stored': len(raw)}
    assert terminal['log_errors'][stream] is None and terminal['log_truncated'][stream] is False
    assert terminal['log_synced'][stream] is True
    stream_reviews.append({'stream': stream, 'parts': parts, 'complete': True,
                           'decoded': create('MAIN_' + stream.upper() + '.complete.log', raw)})

commands = load('READONLY_COMMANDS.json')
assert len(commands) == 41 and all(row['returncode'] == 0 for row in commands)
guards = {}
for name in ('BUILD_PROCESS_PREFLIGHT.json', 'APPLY.process-preflight.json', 'fmt.process-preflight.json'):
    guard = load(name)
    assert guard['active_matching_processes'] == [] and guard['unreadable_matching_processes'] == []
    guards[name] = {'identity': pin((ROOT / name).read_bytes()), 'active': [], 'unreadable': []}
git_names = ('SOURCE_GIT_STATE.before.json', 'apply.after.git-state.json',
             'fmt.after.git-state.json', 'final.git-state.json')
assert len({(ROOT / name).read_bytes() for name in git_names}) == 1
assert len(load(git_names[0])) == 9
metadata_names = ('SOURCE_GIT_METADATA.before.json', 'SOURCE_GIT_METADATA.after.json')
assert (ROOT / metadata_names[0]).read_bytes() == (ROOT / metadata_names[1]).read_bytes()
inputs = load('INPUT_IDENTITIES.json')
assert len(inputs) == 39
result = load('RESULT.json')
assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
assert result['historical_fix']['returncode'] == 101 and result['historical_fix']['already_consumed'] is True
assert result['prior_fix_reclassified'] is False and result['historical_fix_lint_success'] is False
assert result['qualification'] is False and result['fix_dispatched'] is False
assert result['test_commands_dispatched'] == 0 and result['source_ref_updates'] is False
assert result['attempted_commands'] == ['fmt']
assert len(result['stages']) == 1
stage = result['stages'][0]
assert stage['name'] == 'fmt' and stage['timeout_seconds'] == 900
assert stage['argv'] == ['just', 'fmt', '--base', 'c0f78493f815780f68b9bf5e390a21314d79311f']
assert stage['execution'] == load('fmt.execute_logged.original.json')
assert stage['execution']['returncode'] == 0 and stage['execution']['timed_out'] is False
assert stage['execution']['output_limit_exceeded'] is False
assert len(result['final_audits']) == 3 and all(row['status'] == 'verified' for row in result['final_audits'])
assert result['git_metadata_unchanged'] is True

review = {
    'format': 'hepta-completed-fix101-fmt-original-readback-review-v1',
    'scope': 'Offline validation of already captured originals; no new H or command execution.',
    'job_id': JOB, 'request': pin((ROOT / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes()),
    'result': pin((ROOT / 'RESULT.json').read_bytes()),
    'supervisor_original': pin((ROOT / 'MAIN_STATUS_02.original.json').read_bytes()),
    'qualification': False, 'new_h_operations': 0,
    'historical_fix_returncode': 101, 'historical_fix_reclassified': False,
    'one_original_fmt_returncode': 0, 'one_original_fmt_timeout_seconds': 900,
    'staging': {'actual_file_count': 7, 'complete_external_readback': stage_reviews,
                'metadata_scope': 'The original bootstrap enforces its fixed stable regular owner/mode checks. These external binary reads independently verify bytes, path, version, and complete coverage; they do not add unobserved lstat/mode fields.'},
    'application': application_reviews,
    'streams': stream_reviews,
    'readonly_command_count': len(commands), 'all_readonly_commands_returncode_zero': True,
    'input_identity_count': len(inputs), 'producer_final_inputs_unchanged': True,
    'global_guard_original_samples': guards,
    'guard_scope': 'These are the three recorded point observations, not an exclusive lease on other tasks.',
    'lease': {'original': pin((ROOT / 'SOURCE_COORDINATION_EX.json').read_bytes()),
              'scope': 'Cooperative source writers only; no claim of system-wide exclusion.'},
    'raw_git_state': {'names': list(git_names), 'identity': pin((ROOT / git_names[0]).read_bytes()),
                      'all_four_bytes_equal': True, 'contains_porcelain_status': False},
    'raw_git_metadata': {'names': list(metadata_names), 'identity': pin((ROOT / metadata_names[0]).read_bytes()),
                         'both_bytes_equal': True, 'integers_preserved': 'Original raw bytes; Python JSON integer semantics only.'},
    'final_audits': result['final_audits'],
    'provenance': {
        'fmt_packet': 'The complete gzip was actually read in six fixed-version binary chunks and decoded. Its two ASCII parts are deterministic reconstructions matching original ARTIFACTS pins, not separate native part-path reads.',
        'apply_packet': 'The complete gzip was actually read and decoded. Its ASCII part is a deterministic reconstruction matching original ARTIFACTS pins.',
        'inventory': 'Full inventory recovery is separately owned by ordinary_path. No second native full inventory download or porcelain-status observation is claimed here.'},
    'captured_read_failures_in_this_runtime': [],
}
row = create('COMPLETED_ORIGINAL_READBACK_REVIEW.json', encode(review))
print(json.dumps({'review': row, 'staged_files': 7, 'application_records': 12,
                  'readonly_commands': 41, 'inputs': 39, 'streams': stream_reviews,
                  'qualification': False}, sort_keys=True))
