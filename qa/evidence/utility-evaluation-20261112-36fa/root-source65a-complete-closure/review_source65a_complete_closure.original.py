#!/usr/bin/env python3
"""Pure review of already captured originals; never import or execute their code."""
import ast
import base64
import hashlib
import json
from collections import defaultdict
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
D = Path('/tmp/hepta-36fa-final-source-qualification-b608-runtime-v1')
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'
JOB = '1a1d4f0c3d4-392-65a'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def check(raw, wanted):
    actual = pin(raw)
    assert all(actual[k] == wanted[k] for k in ('bytes', 'sha256', 'git_blob')), (actual, wanted)
    return actual

def sdk(raw):
    obj = json.loads(raw)
    assert obj.get('isError') is not True, obj
    data = obj.get('structuredContent')
    if not isinstance(data, dict) or not data:
        data = json.loads(next(x['text'] for x in obj['content'] if x['type'] == 'text'))
    return data

ledger = json.loads((R / 'ROOT_SOURCE65A_COMPLETE_GIT_READBACK.json').read_bytes())
placement_raw = (D / 'PLACEMENT.json').read_bytes()
check(placement_raw, ledger['placement'])
placement = json.loads(placement_raw)
assert len(placement['entries']) == len(ledger['entries']) == 93
root_gets = {x['path']: x['pin'] for x in ledger['entries']}
originals = {}
for entry in placement['entries']:
    raw = Path(entry['local_path']).read_bytes()
    check(raw, entry)
    check(raw, root_gets[entry['path']])
    originals[entry['path']] = raw
assert len(originals) == 93
closed = json.loads((D / 'CLOSED_RUNTIME_ARCHIVE_INPUTS.json').read_bytes())
assert closed['count'] == len(closed['entries']) == 88
for entry in closed['entries']:
    check(originals[entry['evidence_path']], entry)

chunks = defaultdict(list)
failed = []
for entry in closed['entries']:
    name = Path(entry['path']).name
    if '.READ_OFFSET_' not in name and '.RECOVERY_READ_OFFSET_' not in name and name not in {
        'SOURCE_HANDOFF_RESULT.json.READ_01.original.json', 'STAGING_READBACK.json.READ_01.original.json'}:
        continue
    raw = originals[entry['evidence_path']]
    obj = json.loads(raw)
    if obj.get('isError'):
        assert name == 'FILE.staging.qualification-admission.py.READ_OFFSET_000000.original.json'
        assert 'failed with 255' in obj['content'][0]['text']
        failed.append({'sdk': entry['evidence_path'], **pin(raw)})
        continue
    data = sdk(raw)
    body = base64.b64decode(data['data_base64'], validate=True)
    assert hashlib.sha256(body).hexdigest() == data['chunk_sha256']
    assert data['next_offset'] == data['offset'] + len(body)
    chunks[data['path']].append((data, body, entry['evidence_path'], pin(raw)))
assert len(failed) == 1 and sum(map(len, chunks.values())) == 37
decoded = {}
readbacks = []
for path, pieces in sorted(chunks.items()):
    assert path.startswith(BASE + '/')
    pieces.sort(key=lambda x: x[0]['offset'])
    offset = 0
    version = pieces[0][0]['version']
    size = pieces[0][0]['size']
    body_parts = []
    for i, (data, body, source, sdk_pin) in enumerate(pieces):
        assert data['path'] == path and data['version'] == version and data['size'] == size
        assert data['offset'] == offset and data['eof'] is (i == len(pieces) - 1)
        offset = data['next_offset']
        body_parts.append(body)
    assert offset == size
    body = b''.join(body_parts)
    assert len(body) == size
    assert any(pin(body) == x['pin'] for x in ledger['entries']), path
    decoded[path] = body
    readbacks.append({'original_path': path, 'version': version, 'chunks': len(pieces),
                      'body': pin(body), 'original_sdk_paths': [x[2] for x in pieces]})
assert len(decoded) == 30

request = json.loads((D / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes())
assert pin((D / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes()) == {
    'bytes': 246727, 'sha256': '1737f34278a277d0d3003efdf6a9539e11e63d40326544542d81da024947aa16',
    'git_blob': '465e0eaa1f387ad6bb167a4931328e199a5bf793'}
assert request['timeout_seconds'] == 7200 if 'timeout_seconds' in request else request['timeout_s'] == 7200
packet = json.loads(request['stdin'])
assert len(packet['files']) == 8
for name, encoded in packet['files'].items():
    assert decoded[BASE + '/' + name] == base64.b64decode(encoded, validate=True)
assert decoded[BASE + '/ACTUAL_SOURCE_BOOTSTRAP.py'] == request['args'][2].encode()
assert decoded[BASE + '/ACTUAL_SOURCE_BOOTSTRAP_PAYLOAD.json'] == request['stdin'].encode()
assert json.loads(decoded[BASE + '/ACTUAL_SOURCE_BOOTSTRAP_ARGV.json']) == [request['executable'], *request['args']]
staging = json.loads(decoded[BASE + '/STAGING_READBACK.json'])
assert len(staging['files']) == 11
for entry in staging['files']:
    check(decoded[entry['path']], entry)

admission = sdk((D / 'MAIN_ADMISSION.original.json').read_bytes())
job = admission['job']
assert job['id'] == JOB and job['launch_state'] == 'launched' and job['env_keys'] == []
assert admission['launch']['ok'] is True and admission['reused'] is False
assert admission['local_record_pending'] is False
for key in ('host', 'cwd', 'executable', 'args', 'idempotency_key'):
    assert job[key] == request[key]
normal = sdk((D / 'STATUS_01.original.json').read_bytes())
assert normal['job_id'] == JOB and normal['state'] == 'failed' and normal['exit_code'] == 1
for key in ('timed_out', 'cancelled', 'automatic_retry'):
    assert normal[key] is False
for key in ('output_complete', 'output_durable', 'terminal_publication_confirmed'):
    assert normal[key] is True
streams = sdk((D / 'STREAM_READ_01.original.json').read_bytes())
assert streams['job_id'] == JOB
for stream, expected_size in [('stdout', 838), ('stderr', 0)]:
    item = streams[stream]
    body = bytes.fromhex(item['bytes_hex'])
    assert item['offset'] == 0 and item['size'] == item['next_offset'] == len(body) == expected_size
    assert item['eof'] is True and body == (D / (stream + '.complete')).read_bytes()
    assert normal['log_bytes'][stream] == {'seen': expected_size, 'stored': expected_size}
    assert normal['log_synced'][stream] is True and normal['log_truncated'][stream] is False

result = json.loads(decoded[BASE + '/source-handoff/RESULT.json'])
cfg = json.loads(decoded[BASE + '/APPROVED_QUALIFICATION_INPUT.json'])
assert result['status'] == 'failed' and result['qualification'] is False
assert result['driver_main_entered'] is False and result['driver_returncode'] is None
assert result['source'] == 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert result['tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
failed_path = cfg['isolated_materialization']['result_path']
assert result['error'] == "FileNotFoundError: [Errno 2] No such file or directory: '" + failed_path + "'"
assert result['final_evidence_error'] == 'SourceChanged: actual raw Git state changed during qualification'
after = decoded[BASE + '/source-handoff/admission/GIT_STATE.after.json']
check(after, {'bytes': 489, 'git_blob': '35c071ff79b5d932bd234c6e886ad8b18345e498',
              'sha256': '1de2b67a144e21ef6ca48bbf31a3138e39de902d459ca10ff70e45dc97f21b9c'})
assert json.loads(after) == cfg['current_final_git_state']
source = decoded[BASE + '/qualification-admission.py'].decode()
methods = {x.name: ast.get_source_segment(source, x) for x in ast.walk(ast.parse(source)) if isinstance(x, ast.FunctionDef)}
assert 'self.initial_git = None' in methods['__init__']
assert methods['acquire_and_validate'].index('self.validate_materialization(aligned)') < methods['acquire_and_validate'].index('self.initial_git = m.git_state()')
assert "if current_git != self.initial_git:\n            raise SourceChanged('actual raw Git state changed during qualification')" in methods['finish']
historical_path = Path('/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1/RESULT_READ_01.original.json')
historical_raw = historical_path.read_bytes()
check(historical_raw, {'bytes': 20047, 'git_blob': '31b73eb7a77109df0fb3e0b885f83a65712578e5',
                        'sha256': '421312eacadc5c842b8b426a24c2480d2eecfbcddee82f5bb6aa4361f3a0f09c'})
historical = sdk(historical_raw)
historical_body = base64.b64decode(historical['data_base64'], validate=True)
assert historical['path'] == failed_path and historical['offset'] == 0 and historical['eof'] is True
assert historical['next_offset'] == historical['size'] == len(historical_body) == 14663
assert hashlib.sha256(historical_body).hexdigest() == historical['chunk_sha256']

report = {
    'format': 'root-source65a-complete-original-failed-window-review-v1',
    'job_id': JOB, 'status': 'FAILED_PREFLIGHT_RETAINED_NO_QUALIFICATION',
    'actual_git_complete_body_checks': 94, 'closed_original_items': 88,
    'fixed_version_file_readbacks': readbacks,
    'complete_native_paths': 30, 'successful_binary_reads': 37, 'failed_original_binary_reads': failed,
    'source_request': pin((D / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes()),
    'actual_staging_files_equal_request': 11, 'normal_state': 'failed', 'exit_code': 1,
    'timed_out': False, 'retried_main': False, 'driver_main_entered': False,
    'source_gates_started': 0, 'native_phases_started': 0,
    'primary_error': result['error'], 'secondary_error': result['final_evidence_error'],
    'secondary_error_limit': 'initial_git was still None; this does not establish source mutation.',
    'partial_after_git_matches_actual_5a9': pin(after),
    'physical_inventory_and_live_environment_preflight_not_reached': True,
    'historical_failed_path_equals_original_successful_read': True,
    'original_historical_read': pin(historical_raw),
    'original_historical_body': pin(historical_body),
    'unknown': ['which path component was unavailable', 'cause or actor', 'filesystem continuity',
                'present availability of other historical files', 'complete current physical source equality'],
    'qualification': False, 'qualified_real_task_chains': 0,
    'execution_scope': 'Pure local review of already captured bytes; no H, import of admission code, source writes, retry or gate execution.'
}
output = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
target = R / 'ROOT_SOURCE65A_COMPLETE_FAILED_WINDOW_REVIEW.json'
assert not target.exists()
target.write_bytes(output)
print(json.dumps({'path': str(target), **pin(output)}, sort_keys=True))
