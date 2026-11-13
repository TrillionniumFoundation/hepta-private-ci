from pathlib import Path
import copy
import difflib
import hashlib
import json


BASE = Path(__file__).resolve().parent
OLD = BASE / 'review-candidate-v1'
OUT = BASE / 'execution-candidate-v1'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def serialized(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def save(name, raw):
    path = OUT / name
    with path.open('xb') as stream:
        stream.write(raw)
    assert path.read_bytes() == raw
    return {'name': name, **identity(raw)}


def main():
    old_manifest_raw = (OLD / 'MANIFEST.json').read_bytes()
    assert identity(old_manifest_raw)['git_blob'] == '7b7aa021cdc0f75f9a18edc210f7e540e55663c4'
    manifest = json.loads(old_manifest_raw)
    for row in manifest['files']:
        raw = (OLD / row['name']).read_bytes()
        assert identity(raw) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    old_input_raw = (OLD / 'STAGING_INPUT.HOLD.json').read_bytes()
    old_request_raw = (OLD / 'STAGING_PROCESS_INPUT.HOLD.json').read_bytes()
    old_input = json.loads(old_input_raw)
    old_request = json.loads(old_request_raw)
    assert serialized(old_input) == old_input_raw
    assert serialized(old_request) == old_request_raw
    assert old_input['status'] == 'HOLD_ROOT_EXACT_REVIEW_REQUIRED'
    assert old_input['root_execution_approved'] is False
    candidate_input = copy.deepcopy(old_input)
    candidate_input['status'] = 'ROOT_APPROVED_TO_STAGE_ONLY'
    candidate_input['root_execution_approved'] = True
    candidate_input_raw = serialized(candidate_input)
    candidate_request = copy.deepcopy(old_request)
    candidate_request['stdin'] = candidate_input_raw.decode()
    candidate_request_raw = serialized(candidate_request)
    assert set(candidate_request) == {'host', 'executable', 'args', 'cwd', 'stdin',
                                     'timeout_seconds', 'idempotency_key'}
    assert candidate_request['host'] == 'desktop' and candidate_request['timeout_seconds'] == 900
    assert candidate_request['args'] == ['-B', '-c', (OLD / 'TRANSPORT_STAGER.HOLD.py').read_text()]
    assert len(candidate_input_raw) < 1048576 and len(candidate_request_raw) < 1048576
    assert [key for key in old_input if old_input[key] != candidate_input[key]] == [
        'root_execution_approved', 'status']
    assert [key for key in old_request if old_request[key] != candidate_request[key]] == ['stdin']
    reversed_input = copy.deepcopy(candidate_input)
    reversed_input['status'] = old_input['status']
    reversed_input['root_execution_approved'] = False
    assert serialized(reversed_input) == old_input_raw
    reversed_request = copy.deepcopy(candidate_request)
    reversed_request['stdin'] = serialized(reversed_input).decode()
    assert serialized(reversed_request) == old_request_raw
    qualification = json.loads((OLD / 'QUALIFICATION_CONFIG.HOLD.json').read_bytes())
    source = json.loads((OLD / 'SOURCE_GATES_CONFIG.HOLD.json').read_bytes())
    assert qualification['root_execution_approved'] is False
    assert all(qualification['history_transport'][key] is None for key in (
        'staging_result', 'staging_supervisor', 'staging_payload', 'staging_job_id'))
    assert manifest['source_request'] is None and manifest['native_request'] is None
    writes = sorted((OLD / 'write-requests').glob('STAGE_*.REQUEST.HOLD.json'))
    assert len(writes) == 17
    write_refs = []
    for path in writes:
        raw = path.read_bytes()
        value = json.loads(raw)
        assert set(value) == {'host', 'path', 'data_base64', 'expected_version'}
        assert value['host'] == 'desktop' and value['expected_version'] == 'absent'
        write_refs.append({'path': str(path), **identity(raw)})
    OUT.mkdir(exist_ok=False)
    files = [save('STAGING_INPUT.execution-candidate.json', candidate_input_raw),
             save('STAGING_PROCESS_INPUT.execution-candidate.json', candidate_request_raw)]
    for name, before, after in [
        ('FROM_HOLD_STAGING_INPUT.patch', old_input_raw, candidate_input_raw),
        ('FROM_HOLD_REQUEST.patch', old_request_raw, candidate_request_raw),
    ]:
        patch = ''.join(difflib.unified_diff(before.decode().splitlines(keepends=True),
            after.decode().splitlines(keepends=True), fromfile='immutable-HOLD',
            tofile='not-an-execution-approval-candidate')).encode()
        files.append(save(name, patch))
    proof = {
        'format': 'hepta-transport-stage-execution-candidate-byte-review-v1',
        'not_an_execution_approval': True,
        'H_calls': 0,
        'source_request': None,
        'native_request': None,
        'actual_stage_fields': {key: qualification['history_transport'][key] for key in (
            'staging_result', 'staging_supervisor', 'staging_payload', 'staging_job_id')},
        'qualification_execution_approved': False,
        'qualification_config': identity((OLD / 'QUALIFICATION_CONFIG.HOLD.json').read_bytes()),
        'source_config': identity((OLD / 'SOURCE_GATES_CONFIG.HOLD.json').read_bytes()),
        'immutable_hold_manifest': identity(old_manifest_raw),
        'before_input': identity(old_input_raw), 'candidate_input': identity(candidate_input_raw),
        'before_request': identity(old_request_raw), 'candidate_request': identity(candidate_request_raw),
        'changed_staging_input_leaves': ['root_execution_approved', 'status'],
        'changed_typed_fields': ['stdin'],
        'exact_inverse_input_equal': True, 'exact_inverse_request_equal': True,
        'stager_and_args_bytes_unchanged': True,
        'unchanged_stager': identity((OLD / 'TRANSPORT_STAGER.HOLD.py').read_bytes()),
        'all_17_absent_requests_unchanged': write_refs,
        'no_environment_field': True, 'stage_outer_seconds_unchanged': 900,
        'approval_boundary': 'Candidate bytes only. Independent exact Root engineering approval remains required before any H write or process request.',
        'actual_success_or_gate_result_created': False,
    }
    files.append(save('STATIC_EXACT_REVIEW.json', serialized(proof)))
    files.append(save('build_execution_candidate_v1.py', Path(__file__).read_bytes()))
    result = {
        'format': 'hepta-transport-stage-execution-candidate-manifest-v1',
        'not_an_execution_approval': True, 'H_calls': 0,
        'source_request': None, 'native_request': None,
        'actual_stage_fields': proof['actual_stage_fields'],
        'immutable_hold_manifest': identity(old_manifest_raw),
        'files': files,
    }
    saved = save('MANIFEST.json', serialized(result))
    print(json.dumps({'manifest': saved, 'files': files, 'H_calls': 0,
                      'not_an_execution_approval': True}, sort_keys=True))


if __name__ == '__main__':
    main()
