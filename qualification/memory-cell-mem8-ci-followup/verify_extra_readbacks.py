"""Offline root verification; never execute archived code or access a host."""
import base64
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def unpack(data, count):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as archive:
        members = archive.getmembers()
        assert len(members) == count
        assert sum(member.size for member in members) < 1024 * 1024
        out = {}
        for member in members:
            name = PurePosixPath(member.name)
            assert not name.is_absolute() and '..' not in name.parts
            assert member.isfile() and not member.issym() and not member.islnk()
            assert member.name not in out and member.size <= 65536
            out[member.name] = archive.extractfile(member).read()
            assert len(out[member.name]) == member.size
        return out

def manifest_check(files, name):
    manifest = json.loads(files[name])
    rows = manifest['members']
    assert len(rows) == len(files) - 1
    assert {row['path'] for row in rows} == set(files) - {name}
    for row in rows:
        data = files[row['path']]
        assert (len(data), sha(data), blob(data)) == (row['bytes'], row['sha256'], row['git_blob'])
    return manifest

objects = []
pins = []
for index in range(15):
    obj = json.loads((ROOT / 'readback' / f'EXTRA_READBACK_{index:02}.json').read_text())
    response = obj['response']
    assert response['encoding'] == 'base64'
    data = base64.b64decode(''.join(response['content'].split()), validate=True)
    assert blob(data) == response['sha'] == obj['expected']['sha']
    assert data == (ROOT / 'readback' / f'EXTRA_OBJECT_{index:02}').read_bytes()
    objects.append(data)
    pins.append({'path': obj['expected']['path'], 'bytes': len(data), 'sha256': sha(data), 'git_blob': blob(data)})

assert (len(objects[0]), sha(objects[0])) == (39852, '70c18d8ebe9ecb1bf63066752128a36867dc083d6f67ec20561fe4a87269396b')
prep = unpack(objects[0], 18)
outer = manifest_check(prep, 'BUNDLE_MANIFEST.json')
native = unpack(prep['PREP_EVIDENCE.tar.xz'], 18)
inner = manifest_check(native, 'MEMBER_MANIFEST.json')
assert outer['original_job_id'] == inner['job_id'] == '1a1ca0b560a-2564-42b'
exit_record = json.loads(native['job/exit.json'])
witness = json.loads(native['job/exit.witness.json'])
started = json.loads(native['job/started.json'])
assert exit_record['job_id'] == witness['job_id'] == started['job_id'] == inner['job_id']
assert exit_record['launch_nonce'] == witness['launch_nonce'] == started['launch_nonce']
assert witness['exit_sha256'] == sha(native['job/exit.json'])
assert started['supervisor_pid'] == json.loads(native['job/launch.json'])['launcher_pid'] == 4394
assert exit_record['exit_code'] == 1 and not exit_record['timed_out'] and not exit_record['cancelled']
assert exit_record['output_complete'] and exit_record['output_durable']
for stream in ('stdout', 'stderr'):
    raw = native[f'job/{stream}.log']
    assert exit_record['log_bytes'][stream] == {'seen': len(raw), 'stored': len(raw)}
    assert exit_record['log_errors'][stream] is None
    assert exit_record['log_synced'][stream] and not exit_record['log_truncated'][stream]
fetch = json.loads(native['dotslash-fetch.json'])
assert fetch['timed_out'] and fetch['exit_code'] == -9
for stream in ('stdout', 'stderr'):
    info = fetch[stream]
    raw = native[info['path']]
    assert len(raw) == info['bytes'] == 0
    assert sha(raw) == info['sha256'] and blob(raw) == info['git_blob']
result = json.loads(native['PREP_RESULT.json'])
assert result['status'] == 'INCOMPLETE_OR_FAILED'
assert result['download_cap_seconds'] == 300 and result['budget_seconds'] == 360
assert result['fetch_invocations'] == 1
assert result['zsh_controls_executed'] == result['model_requests_issued_by_driver'] == result['native_rust_tests_executed'] == 0
assert not result['escalation_ipc_used']
assert sha(native['DRIVER.py']) == result['driver']['sha256'] == sha(prep['prepare_artifact.py'])

assert (len(objects[1]), sha(objects[1])) == (8320, '2c8cf193476756d67be2a49e4b21c7221126af3c29c30a56d7aa468059481262')
head = unpack(objects[1], 5)
head_manifest = manifest_check(head, 'HEAD_EVIDENCE_MANIFEST.json')
assert head_manifest['supervisor_identity'] == 'UNKNOWN'
assert head_manifest['supervisor_terminal_receipt'] == 'NOT_RECOVERED'
head_result = json.loads(head['HEAD_RESULT.json'])
assert head_result['final_http_status'] == 200 and head_result['curl_exit_code'] == 0
assert head_result['logical_probe_invocations'] == 1 and head_result['caller_retries'] == 0
assert not head_result['bundle_download_attempted'] and not head_result['raw_headers_redirect_queries_stderr_saved']
assert head_result['zsh_controls_executed'] == head_result['model_requests_issued_by_driver'] == 0
assert head_result['driver_sha256'] == sha(head['release_head_diagnostic.py'])
assert head_result['elapsed_seconds'] < head_result['request_chain_budget_seconds'] == 15
assert head_result['total_budget_seconds'] == 20 and head_result['connect_budget_seconds'] == 5
assert head_result['redirects_followed_by_curl'] == 1

assert sha(objects[2]) == '8f95aab31d8124f22ae9ddd67ae78f05862ee707459637ce32285a79c4010898'
assert sha(objects[3]) == '58e47ce484afaba2b0336a8f3eb192956037afe85f943e8a16b5bcbf92878dd7'
assert len(json.loads(objects[3])['files']) == 23
assert blob(objects[14]) == '0295b921099f63f245953eafd9b377db435184a9'

audit = {
    'schema': 'hepta.mem8.root-extra-readback.v13',
    'verified_at': datetime.now(timezone.utc).isoformat(),
    'immutable_commit': '0307b9c436cd34c710972f2c3261aedbaff3c14d',
    'git_objects_verified': pins,
    'mac_preparation_archive_members': 18,
    'mac_original_nested_members': 18,
    'mac_preparation_original_exit_nonce_logs_verified': True,
    'mac_preparation_result': 'FETCH_TIMEOUT_AFTER_300_SECONDS_ZERO_ZSH_CONTROLS',
    'mac_head_archive_members': 5,
    'mac_head_result': 'CURRENT_HEAD_HTTP_200_ONLY',
    'mac_head_supervisor_identity': 'UNKNOWN_NOT_RECOVERED',
    'clock_and_model_candidates': 'STATIC_REVIEWED_NOT_NATIVE_QUALIFIED',
    'prior_failures_preserved': True,
    'archived_programs_executed': 0,
    'host_operations_executed': 0,
    'model_requests_executed': 0,
}
(ROOT / 'ROOT_EXTRA_READBACK_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps({key: value for key, value in audit.items() if key != 'git_objects_verified'}, indent=2))
