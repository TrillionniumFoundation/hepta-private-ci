import ast
import base64
import hashlib
import json
from pathlib import Path

D = Path('/tmp/hepta-36fa-final-source-qualification-b608-runtime-v1')
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'
JOB = '1a1d4f0c3d4-392-65a'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def exact(raw, pin):
    assert identity(raw) == {k: pin[k] for k in ('bytes', 'sha256', 'git_blob')}, pin

def body(path):
    sdk = json.loads(Path(path).read_bytes())
    assert sdk.get('isError') is not True, path
    return json.loads(next(x['text'] for x in sdk['content'] if x['type'] == 'text'))

def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, path
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'local_path': str(path), **identity(raw)}

initial = json.loads((D / 'CURRENT_JOB_READBACK_ATTEMPT1.json').read_bytes())
recovery = json.loads((D / 'CURRENT_JOB_READBACK_RECOVERY.json').read_bytes())['recovery']
plan = json.loads((D / 'FIXED_CURRENT_JOB_READBACK_PLAN.json').read_bytes())
assert len(plan['files']) == len(initial['files']) == 28
assert recovery['status'] == 'complete_chunk_coverage'
assert len(recovery['chunks']) == 2
failures = [x for x in initial['files'] if x['status'] != 'complete_chunk_coverage']
assert len(failures) == 1 and failures[0]['file']['relative_output'] == 'staging/qualification-admission.py'
assert failures[0]['version'] is None
failed_sdk_path = failures[0]['chunks'][0]['sdk']['path']
failed_raw = Path(failed_sdk_path).read_bytes()
exact(failed_raw, failures[0]['chunks'][0]['sdk'])
failed_sdk = json.loads(failed_raw)
assert failed_sdk['isError'] is True
assert 'failed with 255' in failed_sdk['content'][0]['text'] and 'Connection closed' in failed_sdk['content'][0]['text']

rows = []
decoded = {}
success_chunks = 0
for item in initial['files']:
    f = item['file']
    selected = item if item['status'] == 'complete_chunk_coverage' else recovery
    raw = bytearray()
    version = None
    originals = []
    for chunk in selected['chunks']:
        p = Path(chunk['sdk']['path'])
        sdkraw = p.read_bytes()
        exact(sdkraw, chunk['sdk'])
        b = body(p)
        assert b['path'] == f['native_path'] == chunk['request']['path']
        assert b['offset'] == chunk['request']['offset'] == len(raw)
        data = base64.b64decode(b['data_base64'], validate=True)
        assert hashlib.sha256(data).hexdigest() == b['chunk_sha256']
        assert b['next_offset'] == len(raw) + len(data)
        if version is None:
            version = b['version']
            assert 'expected_version' not in chunk['request']
        else:
            assert b['version'] == version == chunk['request']['expected_version']
        raw.extend(data)
        assert b['eof'] is (len(raw) == b['size'])
        originals.append({'sdk_path': str(p), **identity(sdkraw),
                          'offset': b['offset'], 'next_offset': b['next_offset'],
                          'chunk_sha256': b['chunk_sha256'], 'version': b['version']})
    raw = bytes(raw)
    assert b['eof'] is True and len(raw) == selected['next_offset'] == b['size']
    if f['expected'] is not None:
        exact(raw, f['expected'])
    final = put(D / 'native-readback' / f['relative_output'], raw)
    rows.append({'native_path': f['native_path'], 'relative_output': f['relative_output'],
                 'version': version, 'complete_original_bytes_verified': True,
                 'chunks': originals, 'decoded': final})
    decoded[f['relative_output']] = raw
    success_chunks += len(originals)
assert len(rows) == 28 and success_chunks == 35

typed_raw = (D / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes()
exact(typed_raw, {'bytes': 246727, 'sha256': '1737f34278a277d0d3003efdf6a9539e11e63d40326544542d81da024947aa16',
                  'git_blob': '465e0eaa1f387ad6bb167a4931328e199a5bf793'})
typed = json.loads(typed_raw)
packet = json.loads(typed['stdin'])
for name, encoded in packet['files'].items():
    assert decoded['staging/' + name] == base64.b64decode(encoded, validate=True)
assert len(packet['files']) == 8
assert decoded['staging/ACTUAL_SOURCE_BOOTSTRAP.py'] == typed['args'][2].encode()
assert decoded['staging/ACTUAL_SOURCE_BOOTSTRAP_PAYLOAD.json'] == typed['stdin'].encode()
argv = json.loads(decoded['staging/ACTUAL_SOURCE_BOOTSTRAP_ARGV.json'])
assert argv == [typed['executable'], *typed['args']]
stage = json.loads((D / 'STAGING_READBACK.json').read_bytes())
assert len(stage['files']) == 11
for entry in stage['files']:
    name = Path(entry['path']).name
    assert entry['path'] == BASE + '/' + name
    exact(decoded['staging/' + name], entry)

cfg = json.loads(decoded['staging/APPROVED_QUALIFICATION_INPUT.json'])
result = json.loads((D / 'SOURCE_HANDOFF_RESULT.json').read_bytes())
exact(decoded['source-handoff/admission/CANONICAL_ALIGNMENT.RESULT.original.json'], cfg['canonical_alignment']['result'])
exact(decoded['source-handoff/admission/CANONICAL_ALIGNMENT.SUPERVISOR.original.json'], cfg['canonical_alignment']['supervisor'])
exact(decoded['source-handoff/admission/PLAN.original.json'], cfg['plan_pin'])
after_git = decoded['source-handoff/admission/GIT_STATE.after.json']
exact(after_git, {'bytes': 489, 'sha256': '1de2b67a144e21ef6ca48bbf31a3138e39de902d459ca10ff70e45dc97f21b9c',
                  'git_blob': '35c071ff79b5d932bd234c6e886ad8b18345e498'})
assert json.loads(after_git) == cfg['current_final_git_state']
assert json.loads(decoded['source-handoff/admission/historical-runtime/READONLY_COMMANDS.json']) == []
lock = json.loads(decoded['source-handoff/admission/SOURCE_COORDINATION_SH.json'])
for key in ('path', 'device', 'inode', 'uid', 'nlink', 'mode'):
    assert lock[key] == cfg['coordination_lock'][key]

source = decoded['staging/qualification-admission.py'].decode()
methods = {x.name: x for x in ast.walk(ast.parse(source)) if isinstance(x, ast.FunctionDef)}
init = ast.get_source_segment(source, methods['__init__'])
acquire = ast.get_source_segment(source, methods['acquire_and_validate'])
finish = ast.get_source_segment(source, methods['finish'])
assert 'self.initial_git = None' in init
assert acquire.index('self.validate_materialization(aligned)') < acquire.index('self.initial_git = m.git_state()')
assert "self.m.jwrite('GIT_STATE.after.json', current_git)" in finish
assert "if current_git != self.initial_git:\n            raise SourceChanged('actual raw Git state changed during qualification')" in finish
assert result['driver_main_entered'] is False and result['driver_returncode'] is None
assert result['error'] == "FileNotFoundError: [Errno 2] No such file or directory: '" + cfg['isolated_materialization']['result_path'] + "'"
assert result['status'] == 'failed' and result['qualification'] is False
assert result['final_evidence_error'] == 'SourceChanged: actual raw Git state changed during qualification'

listing = json.loads((D / 'SOURCE_HANDOFF_LISTING.original.json').read_bytes())['content'][0]['text']
listed = [line.split('\t')[0] for line in listing.strip().splitlines()]
assert len(listed) == 18
assert set('source-handoff/' + x for x in listed) == ({'source-handoff/RESULT.json'} | {x for x in decoded if x.startswith('source-handoff/')})
report = {
    'format': 'hepta-completed-source-failed-preflight-full-readback-v1',
    'job_id': JOB, 'status': 'ORIGINAL_FAILED_PRECONDITION_FULLY_RETAINED',
    'original_result_status_preserved': result['status'],
    'supervisor_exit_code': 1, 'supervisor_timed_out': False,
    'driver_main_entered': False, 'original_source_gates_started': 0, 'native_fourteen_phases_started': False,
    'primary_error': result['error'], 'secondary_error': result['final_evidence_error'],
    'secondary_control_flow': 'The materialization proof read occurs before initial_git assignment; finish records the actual current Git state and then compares it with the still-None initial field. This secondary error is preserved and is not independent evidence of source mutation.',
    'actual_after_git_equals_5a9_canonical_endpoint_bytes': True,
    'actual_after_git': identity(after_git),
    'current_full_physical_inventory_not_observed_in_this_attempt': True,
    'live_environment_preflight_not_reached_in_this_attempt': True,
    'current_actual_source_coordination_lock': lock,
    'staging_original_eleven_files_complete_external_readback': True,
    'eight_payloads_and_bootstrap_argv_stdin_equal_exact_approved_request': True,
    'all_eighteen_original_handoff_paths_read_completely': True,
    'additional_paths_decoded_in_this_report': 28,
    'total_complete_native_file_paths_including_result_and_staging_manifest': 30,
    'successful_binary_chunks_including_result_and_staging_manifest': 37,
    'total_binary_read_calls_including_one_transport_failure': 38,
    'transport_failure': {'sdk_path': failed_sdk_path, **identity(failed_raw),
                          'initial_version_was_unknown': True, 'same_file_read_reconciled': True,
                          'first_successful_version': recovery['version'], 'original_error_preserved': True},
    'whole_stdout_bytes': 838, 'whole_stderr_bytes': 0,
    'historical_materialization_path_new_native_probe': False,
    'new_process_dispatches_for_recovery': 0, 'source_or_index_or_ref_repairs': 0,
    'qualification': False, 'file_readbacks': rows,
    'limitations': ['The failure identifies current unavailability at the configured historical record path; it does not identify the cause.',
                    'Matching raw Git state is not a new full physical source inventory or qualification result.',
                    'The completed wrapper status remains failed; original source driver main and all three source gates were not entered.']}
raw = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
print(json.dumps(put(D / 'COMPLETE_FAILED_PREFLIGHT_READBACK_REVIEW.json', raw), sort_keys=True))
